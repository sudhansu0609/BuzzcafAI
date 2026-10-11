"""An unattended strategist: a tool loop instead of one reply.

The Studio Assistant (studio_chat.run_chat) resolves a strategist's tool tags
once and shows the result to the creator -- the strategist never reads what its
own tools returned. Unattended work (the nightly long-form planner) needs the
strategist to look things up, read the answers and then decide, so `run()`
loops: the strategist replies, every tool tag in the reply is executed, the
results go back as the next user turn, and it continues until it writes its
`[FINAL_PLAN]{...json...}[/FINAL_PLAN]` or runs out of turns.

Tools it can call (the same tag syntax as the Studio Assistant, so the personas
need no new training):

- every registered agent (all 105 personas) via `[INVOKE_AGENT: Name] task [/INVOKE_AGENT]`;
- web / book / news / archive search and page fetch;
- the Topic Vault (save, look up, list) and the creator's Idea Dump;
- competitor video and channel analysis, the project list and project status,
  the local model list and status;
- every Studio action (the Dexter registry) that reads, plus the few writes
  that are safe unattended, via `[STUDIO_ACTION: name | {json params}]`.

Left out on purpose, because they would act on the creator's machine or data
without them: switching the active model, changing settings (and reading them
-- they hold API keys), creating/deleting/running projects (the caller owns the
project), starting a GPU render, deleting anything, and chatting with another
strategist (no recursion).
"""
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("buzzcaf_ai.strategist_runner")

MAX_TURNS = 8
MAX_CALLS_PER_TURN = 6
RESULT_CHARS = 3500

#: Studio actions (app/services/dexter_registry.py) a strategist may run
#: unattended: every "read" except the settings/diagnostics dumps, plus these writes.
BLOCKED_READS = {"settings_get", "diagnostics", "searxng_test"}
ALLOWED_WRITES = {"topic_save", "topic_update", "topic_research_and_save", "department_execute", "video_analyze",
                  "apply_audio_rack_preset", "set_character_voice"}

_FINAL_RE = re.compile(r"\[FINAL_PLAN\](.*?)\[/FINAL_PLAN\]", re.DOTALL | re.I)
_IDEA_DUMP_RE = re.compile(r"\[IDEA_DUMP:\s*(.*?)\](?:\[/IDEA_DUMP\])?", re.I)
_STUDIO_ACTION_RE = re.compile(r"\[STUDIO_ACTION:\s*([a-z_]+)\s*(?:\|\s*(\{.*?\}))?\s*\](?:\[/STUDIO_ACTION\])?",
                               re.I | re.DOTALL)
#: Chat-only tags that are not honoured here; named back to the strategist.
_REFUSED_RE = re.compile(r"\[(CREATE_PROJECT|SWITCH_MODEL|NAVIGATE_TAB)\b[^\]]*\](?:\[/\1\])?", re.I)


def allowed_actions() -> List[Dict[str, Any]]:
    from app.services import dexter_registry
    out = []
    for cap in dexter_registry.CAPABILITIES:
        ok = (cap["kind"] == "read" and cap["name"] not in BLOCKED_READS) or cap["name"] in ALLOWED_WRITES
        if ok:
            out.append({"name": cap["name"], "params": cap.get("params") or {}})
    return out


def tool_guide() -> str:
    actions = "\n".join(f"  - {a['name']} {json.dumps(a['params'], ensure_ascii=False)}" for a in allowed_actions())
    return (
        "\n\n## Tools (you are working unattended; the results come back to you in the next message)\n"
        "Write any of these tags; up to "
        f"{MAX_CALLS_PER_TURN} run per reply. Think briefly, call tools, read the results, then decide.\n"
        "- Hand work to any Studio agent: `[INVOKE_AGENT: AgentName] the task [/INVOKE_AGENT]` "
        "(researchers, FactChecker, ScriptWriter, HorrorWriter, TitleGenerator, CompetitorAnalyst, TrendAnalyst ... "
        "-- the full directory is above).\n"
        "- Web: `[WEB_SEARCH: keywords]`, `[WEB_FETCH: https://url]`, `[NEWS_SEARCH: keywords]`, "
        "`[BOOK_SEARCH: keywords]`, `[ARCHIVE_SEARCH: keywords]`.\n"
        "- Topic Vault: `[VAULT_LIST: Channel]`, `[VAULT_LOOKUP: keywords]`, `[SAVE_TOPIC: title | Channel | notes]`.\n"
        "- The creator's Idea Dump: `[IDEA_DUMP: Channel]` (or `[IDEA_DUMP: Channel | keywords]`).\n"
        "- YouTube: `[ANALYZE_VIDEO: url_or_id]`, `[ANALYZE_CHANNEL: handle]`.\n"
        "- Projects and models: `[LIST_PROJECTS]`, `[PROJECT_STATUS: projectId]`, `[LIST_MODELS]`, `[MODEL_STATUS]`.\n"
        "- Any Studio action: `[STUDIO_ACTION: name | {\"param\": \"value\"}]`. Available:\n"
        f"{actions}\n"
        "Not available unattended: creating/running/deleting projects, switching models, changing settings.\n"
    )


def _idea_dump(arg: str, default_channel: str) -> str:
    import os
    from core.paths import KNOWLEDGE_DIR
    parts = [p.strip() for p in arg.split("|")]
    channel = parts[0] or default_channel
    words = [w for w in (parts[1] if len(parts) > 1 else "").lower().split() if w]
    try:
        with open(os.path.join(str(KNOWLEDGE_DIR), "idea_dump.json"), encoding="utf-8") as f:
            ideas = [d for d in json.load(f) if isinstance(d, dict) and d.get("channel") == channel]
    except Exception:
        ideas = []
    if words:
        ideas = [d for d in ideas if all(w in str(d.get("title", "")).lower() for w in words)]
    ideas.sort(key=lambda d: d.get("createdAt") or "")
    if not ideas:
        return f"No Idea Dump entries for {channel}" + (f" matching '{parts[1]}'" if words else "") + "."
    lines = [f"- [dump:{d.get('id')}] {d.get('title')}" + (f" -- {d['notes']}" if d.get("notes") else "")
             for d in ideas[:40]]
    return f"{len(ideas)} Idea Dump entries for {channel} (oldest first, first 40):\n" + "\n".join(lines)


def _studio_action(name: str, raw_params: Optional[str]) -> str:
    from app.services import dexter_registry
    if name not in {a["name"] for a in allowed_actions()}:
        return f"'{name}' is not available unattended."
    try:
        params = json.loads(raw_params) if raw_params else {}
    except json.JSONDecodeError as exc:
        return f"Could not parse the params JSON: {exc}"
    out = dexter_registry.invoke(name, params, actor="strategist")
    return json.dumps(out.get("result") if out.get("status") == "success" else out, ensure_ascii=False, default=str)


def _collect(reply: str, channel: str, llm: Any, caller: str) -> List[tuple]:
    from app.services import studio_chat as sc
    found: List[tuple] = []

    def add(regex, label, run_fn):
        for m in regex.finditer(reply):
            found.append((m.start(), label(m), (lambda m=m: run_fn(m))))

    def agent(m):
        text, records = sc.process_agent_invocations(m.group(0), llm_service=llm, caller=caller)
        return text
    add(sc._INVOKE_RE, lambda m: f"agent {m.group(1).strip()}: {m.group(2).strip()[:120]}", agent)
    for regex, name in ((sc._SEARCH_RE, "web search"), (sc._FETCH_RE, "fetch"), (sc._BOOK_RE, "book search"),
                        (sc._NEWS_RE, "news search"), (sc._ARCHIVE_RE, "archive search")):
        add(regex, lambda m, n=name: f"{n}: {m.group(1).strip()[:120]}", lambda m: sc.process_web_research_tags(m.group(0)))
    for regex, name in ((sc._SAVE_TOPIC_RE, "save topic"), (sc._VAULT_LOOKUP_RE, "vault lookup"),
                        (sc._VAULT_LIST_RE, "vault list")):
        add(regex, lambda m, n=name: f"{n}: {m.group(1).strip()[:120]}", lambda m: sc.process_vault_tags(m.group(0), channel))
    for regex, name in ((sc._ANALYZE_VIDEO_RE, "analyze video"), (sc._ANALYZE_CHANNEL_RE, "analyze channel"),
                        (sc._PROJECT_STATUS_RE, "project status")):
        add(regex, lambda m, n=name: f"{n}: {m.group(1).strip()[:120]}",
            lambda m: sc.process_studio_tools_tags(m.group(0), channel))
    for regex, name in ((sc._PROJECT_LIST_RE, "list projects"), (sc._MODEL_LIST_RE, "list models"),
                        (sc._MODEL_STATUS_RE, "model status")):
        add(regex, lambda m, n=name: n, lambda m: sc.process_studio_tools_tags(m.group(0), channel))
    add(_IDEA_DUMP_RE, lambda m: f"idea dump: {m.group(1).strip()[:120]}", lambda m: _idea_dump(m.group(1), channel))
    add(_STUDIO_ACTION_RE, lambda m: f"studio action {m.group(1)}", lambda m: _studio_action(m.group(1).lower(), m.group(2)))
    add(_REFUSED_RE, lambda m: f"refused {m.group(1).upper()}",
        lambda m: f"{m.group(1).upper()} is not available unattended; the scheduler handles projects itself.")
    found.sort(key=lambda f: f[0])
    return found


def _parse_final(reply: str) -> Optional[Dict[str, Any]]:
    m = _FINAL_RE.search(reply)
    if not m:
        return None
    body = m.group(1).strip().strip("`")
    if body.lower().startswith("json"):
        body = body[4:]
    try:
        data = json.loads(body[body.find("{"): body.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError):
        try:
            from app.services.shorts_desk import _parse_json
            data = _parse_json(body)
        except Exception:
            data = None
    return data if isinstance(data, dict) else None


def run(agent_name: str, channel: str, task: str, *, system_extra: str = "",
        on_event: Optional[Callable[[str], None]] = None, llm: Any = None,
        max_turns: int = MAX_TURNS) -> Dict[str, Any]:
    """Loop the strategist over its tools until it writes FINAL_PLAN.
    Returns {"plan": dict, "turns": n, "calls": [labels]}; raises RuntimeError
    when no model answers or no plan comes back."""
    from core.agent import AgentFactory
    from integrations.llm import LLMService
    say = on_event or (lambda m: None)
    agent = AgentFactory.get_agent(agent_name, llm or LLMService())
    extra = system_extra + tool_guide() + (
        "\n\n## Finishing\nWhen you have decided, reply with the plan inside "
        "`[FINAL_PLAN]{...json...}[/FINAL_PLAN]` and nothing that still needs a tool.\n")
    messages: List[Dict[str, str]] = [{"role": "user", "content": task}]
    calls_made: List[str] = []

    for turn in range(1, max_turns + 2):
        last_chance = turn > max_turns
        if last_chance:  # appended to the pending user turn, so roles still alternate
            messages[-1]["content"] += ("\n\nStop researching now. Reply with only the "
                                        "[FINAL_PLAN]{...}[/FINAL_PLAN] block, using what you already have.")
        say(f"{agent_name} thinking (turn {turn})")
        reply = str(agent.execute_messages(messages, system_extra=extra))
        if getattr(agent.llm_service, "last_response_simulated", False):
            raise RuntimeError("no model answered the strategist")
        plan = _parse_final(reply)
        if plan:
            say(f"{agent_name} wrote the plan")
            return {"plan": plan, "turns": turn, "calls": calls_made}
        if last_chance:
            break
        calls = _collect(reply, channel, agent.llm_service, agent_name)
        messages.append({"role": "assistant", "content": reply})
        if not calls:
            messages.append({"role": "user", "content": "You neither called a tool nor wrote the FINAL_PLAN. "
                             "Call the tools you need, or write the [FINAL_PLAN] now."})
            continue
        results = []
        for i, (_, label, fn) in enumerate(calls):
            if i >= MAX_CALLS_PER_TURN:
                results.append(f"### {label}\nNot run: at most {MAX_CALLS_PER_TURN} tool calls per reply.")
                continue
            say(label)
            calls_made.append(label)
            try:
                out = str(fn()).strip()
            except Exception as exc:  # noqa: BLE001 - reported back to the strategist
                logger.warning("strategist tool '%s' failed: %s", label, exc)
                out = f"failed: {exc}"
            results.append(f"### {label}\n{out[:RESULT_CHARS]}")
        messages.append({"role": "user", "content": "## Tool results\n\n" + "\n\n".join(results)
                         + "\n\nContinue: more tools if you still need them, otherwise the [FINAL_PLAN]."})
    raise RuntimeError(f"{agent_name} did not produce a plan in {max_turns} turns")
