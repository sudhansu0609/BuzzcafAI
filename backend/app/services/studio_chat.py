"""
The Studio Assistant conversation (roadmap v5, 2.4).

One function, `run_chat`, builds a proper chat for a channel strategist and
runs it. Before v5 the chat endpoint concatenated everything - persona, the
115-agent roster (twice), thirty verbatim memory dumps (injected twice), a
"you remember everything" directive and a mandatory Hinglish rule - into a
single user-role string, then handed the reply to the model with no real
turn structure. This module:

- keeps the persona as the system prompt (roster included once, for
  strategists, by BaseAgent);
- adds the channel's brand guide and up to six *relevant* memories once;
- passes the last eight turns as real user/assistant messages;
- lets the model answer in the language the user writes in (Hinglish is
  still required for content assets produced by workflow steps);
- stores the full exchange instead of a 300-character snippet.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.events import bus
from core.agent import AgentFactory
from core.paths import PROMPTS_DIR

logger = logging.getLogger("buzzcaf_ai.studio_chat")

HISTORY_TURNS = 8          # user+assistant messages kept from the client history
MEMORY_LIMIT = 6           # relevant past exchanges injected into the system prompt
GUIDE_CHARS = 1800         # how much of the brand guide rides along
MEMORY_REPLY_CHARS = 600   # per remembered reply, in the prompt
MAX_INVOCATIONS = 3        # delegations honoured per reply; the rest are logged as skipped

_STRATEGISTS = {
    # Brand names first (Originals / Raat3Baje), legacy spellings kept so old
    # localStorage values and saved topics still resolve to the same agent.
    "raat3baje": "AfterDarkStrategist",
    "after dark": "AfterDarkStrategist",
    "originals": "SpilledCoffeeStudioStrategist",
    "studio": "SpilledCoffeeStudioStrategist",
    "life": "Life3BajeStrategist",
    "khayal": "Khayal3BajeStrategist",
}
_INVOKE_RE = re.compile(r"\[INVOKE_AGENT:\s*([a-zA-Z0-9_]+)\](.*?)\[/INVOKE_AGENT\]", re.DOTALL)


def strategist_for(channel: str) -> str:
    lower = (channel or "").lower()
    for needle, name in _STRATEGISTS.items():
        if needle in lower:
            return name
    return "Beyond3BajeStrategist"


def channel_guide(channel: str) -> str:
    """The first part of prompts/channels/<Brand>.md, or '' when there is none."""
    if not channel:
        return ""
    slug = re.sub(r"[^A-Za-z0-9]", "", channel)
    path = os.path.join(PROMPTS_DIR, "channels", f"{slug}.md")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
    except OSError:
        return ""
    return text[:GUIDE_CHARS]


def _memory_lines(agent_name: str, channel: str, message: str) -> List[str]:
    """Past exchanges that share words with this message, newest first among ties."""
    try:
        from memory.memory import memory_system

        items = memory_system.retrieve(scope="agent", owner=agent_name, query=message, limit=MEMORY_LIMIT)
    except Exception as exc:  # memory must never take the chat down
        logger.warning("memory retrieval failed: %s", exc)
        return []
    lines: List[str] = []
    for item in items:
        content = item.content
        if isinstance(content, dict) and "user" in content:
            user = str(content.get("user", ""))[:200]
            reply = str(content.get("reply", ""))[:MEMORY_REPLY_CHARS]
            lines.append(f"- [{item.updated[:10]}] You were asked: {user!s}\n  You replied: {reply}")
        else:
            text = json.dumps(content) if isinstance(content, (dict, list)) else str(content)
            lines.append(f"- [{item.updated[:10]}] {text[:MEMORY_REPLY_CHARS]}")
    return lines


def _topic_block(topic: Optional[Dict[str, Any]], channel: str) -> str:
    if not topic:
        return ""

    def join(value: Any) -> str:
        return ", ".join(value) if isinstance(value, list) else str(value or "")

    return (
        "\n\n## Topic on the table\n"
        f"- Title: {topic.get('topic')}\n"
        f"- Category: {topic.get('category')}\n"
        f"- Channel: {topic.get('channel', channel)}\n"
        f"- Viral potential: {topic.get('viral_potential')}/10\n"
        f"- Sources: {join(topic.get('sources_used'))}\n"
        f"- Visuals: {join(topic.get('visual_requirements'))}\n"
    )


def build_system_extra(agent_name: str, channel: str, message: str, topic: Optional[Dict[str, Any]]) -> str:
    parts = [f"\n\n## You are speaking as {agent_name} for the channel '{channel}'."]
    guide = channel_guide(channel)
    if guide:
        parts.append(f"\n\n## Brand guide for {channel}\n{guide}")
    memories = _memory_lines(agent_name, channel, message)
    if memories:
        parts.append("\n\n## Relevant past exchanges with the creator\n" + "\n".join(memories))
    parts.append(_topic_block(topic, channel))
    parts.append(
        "\n\n## How to answer\n"
        "- Reply in the language the creator writes in. When you produce content "
        "assets (titles, hooks, narration, dialogue) for this channel, write those in "
        "Hinglish (conversational Hindi in Roman script) unless asked otherwise.\n"
        "- Be specific to this channel's voice and the topic on the table.\n"
        "- To hand work to a specialist, write "
        "`[INVOKE_AGENT: AgentName] instructions [/INVOKE_AGENT]` and it will run."
    )
    return "".join(parts)


def build_messages(history: Optional[List[Dict[str, str]]], message: str) -> List[Dict[str, str]]:
    turns: List[Dict[str, str]] = []
    for turn in (history or [])[-HISTORY_TURNS:]:
        role = "user" if (turn.get("role") or "").lower() == "user" else "assistant"
        content = str(turn.get("content") or "").strip()
        if content:
            turns.append({"role": role, "content": content})
    turns.append({"role": "user", "content": message})
    return turns


def strip_invocations(text: str) -> str:
    """The text with every `[INVOKE_AGENT: ...]` block removed."""
    return _INVOKE_RE.sub("", text).strip()


def process_agent_invocations(
    reply_text: str,
    llm_service: Optional[Any] = None,
    caller: str = "the strategist",
) -> Tuple[str, List[Dict[str, Any]]]:
    """Run `[INVOKE_AGENT: X] task [/INVOKE_AGENT]` blocks and report what ran.

    Returns the reply with each tag replaced by the delegated output, plus one
    record per tag so the UI and the event bus can show who did what (roadmap
    v9, B1). At most `MAX_INVOCATIONS` run per reply and the delegated output is
    never scanned again, so a model cannot spend the studio in a loop.
    """
    matches = list(_INVOKE_RE.finditer(reply_text))
    if not matches:
        return reply_text, []

    final_text = reply_text
    records: List[Dict[str, Any]] = []
    for index, match in enumerate(matches):
        full_tag = match.group(0)
        target = match.group(1).strip()
        task = match.group(2).strip()

        if index >= MAX_INVOCATIONS:
            logger.warning(
                "Skipping delegation to %s: %s already delegated %d times in one reply",
                target, caller, MAX_INVOCATIONS,
            )
            records.append({"agent": target, "task": task, "output": "", "simulated": False, "skipped": True})
            final_text = final_text.replace(
                full_tag,
                f"\n*`{target}` was not run: at most {MAX_INVOCATIONS} delegations per reply.*\n",
            )
            continue

        logger.info("%s delegated to %s", caller, target)
        simulated = False
        try:
            agent = AgentFactory.get_agent(target, llm_service)
            output = str(agent.execute(
                f"You have been invoked by {caller} to perform the following task:\n\n{task}"
            ))
            simulated = bool(getattr(agent.llm_service, "last_response_simulated", False))
            # Depth 1: whatever the specialist emitted is text, not a new order.
            output = strip_invocations(output)
            replacement = (
                f"\n\n---\n🤖 **[Delegated to `{target}`]**\n> *Task*: {task}\n\n{output}\n---\n\n"
            )
            records.append({"agent": target, "task": task, "output": output, "simulated": simulated})
        except Exception as exc:
            logger.error("Delegated agent %s failed: %s", target, exc)
            replacement = f"\n*⚠️ `{target}` could not complete the delegated task: {exc}*\n"
            records.append({"agent": target, "task": task, "output": "", "simulated": False, "error": str(exc)})
        final_text = final_text.replace(full_tag, replacement)

    for record in records:
        if record.get("skipped"):
            continue
        try:
            bus.publish("agent_invoked", {
                "agent": record["agent"],
                "task_preview": record["task"][:200],
                "simulated": record["simulated"],
            })
        except Exception as exc:  # the bus must never take a chat turn down
            logger.warning("could not publish agent_invoked: %s", exc)

    return final_text, records


def run_chat(
    message: str,
    channel: str,
    agent_name: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    context_topic: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One Studio Assistant turn. Raises on provider failure; the route maps that to 502."""
    channel = (channel or "").strip() or "Beyond3Baje"
    agent_name = (agent_name or "").strip() or strategist_for(channel)
    message = (message or "").strip()
    if not message:
        raise ValueError("message is empty")

    try:
        agent = AgentFactory.get_agent(agent_name)
    except Exception:
        agent = AgentFactory.get_agent("TopicVaultManager")

    system_extra = build_system_extra(agent_name, channel, message, context_topic)
    messages = build_messages(history, message)

    reply_text = str(agent.execute_messages(messages, system_extra=system_extra))
    simulated = bool(getattr(agent.llm_service, "last_response_simulated", False))
    reply_text, invocations = process_agent_invocations(
        reply_text, llm_service=agent.llm_service, caller=agent_name
    )

    try:
        from memory.memory import memory_system

        record = {"user": message, "reply": reply_text, "agent": agent_name, "channel": channel}
        memory_system.save(scope="agent", owner=agent_name, tags=["chat", channel], content=record)
        memory_system.save(scope="session", owner=channel, tags=["chat", agent_name], content=record)
        # Delegated work is stored against the specialist that did it, tagged so
        # it can be told apart from what the creator asked directly.
        for item in invocations:
            if item.get("skipped"):
                continue
            memory_system.save(
                scope="agent",
                owner=item["agent"],
                tags=["delegated", agent_name, channel],
                content={"user": item["task"], "reply": item["output"], "agent": item["agent"], "channel": channel},
            )
    except Exception as exc:
        logger.error("could not store the exchange: %s", exc)

    return {
        "status": "simulated" if simulated else "success",
        "simulated": simulated,
        "agent_name": agent_name,
        "channel": channel,
        "reply": reply_text,
        "invocations": invocations,
    }
