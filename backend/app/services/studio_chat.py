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
    # Raat3Baje / After Dark
    "raat3baje": "AfterDarkStrategist",
    "raat 3 baje": "AfterDarkStrategist",
    "raat": "AfterDarkStrategist",
    "after dark": "AfterDarkStrategist",
    "afterdark": "AfterDarkStrategist",
    # Beyond3Baje
    "beyond3baje": "Beyond3BajeStrategist",
    "beyond 3 baje": "Beyond3BajeStrategist",
    "beyond": "Beyond3BajeStrategist",
    # Originals / Spilled Coffee
    "originals": "SpilledCoffeeStudioStrategist",
    "spilled coffee": "SpilledCoffeeStudioStrategist",
    "spilledcoffee": "SpilledCoffeeStudioStrategist",
    "studio": "SpilledCoffeeStudioStrategist",
    # Life3Baje
    "life3baje": "Life3BajeStrategist",
    "life 3 baje": "Life3BajeStrategist",
    "life": "Life3BajeStrategist",
    # Khayal3Baje
    "khayal3baje": "Khayal3BajeStrategist",
    "khayal 3 baje": "Khayal3BajeStrategist",
    "khayal": "Khayal3BajeStrategist",
}
_INVOKE_RE = re.compile(r"\[INVOKE_AGENT:\s*([a-zA-Z0-9_]+)\](.*?)\[/INVOKE_AGENT\]", re.DOTALL)
_SEARCH_RE = re.compile(r"\[(?:WEB_SEARCH|SEARCH):\s*(.*?)\](?:\[/(?:WEB_SEARCH|SEARCH)\])?", re.IGNORECASE)
_FETCH_RE = re.compile(r"\[(?:WEB_FETCH|FETCH):\s*(https?://[^\s\]]+)\](?:\[/(?:WEB_FETCH|FETCH)\])?", re.IGNORECASE)
_BOOK_RE = re.compile(r"\[BOOK_SEARCH:\s*(.*?)\](?:\[/BOOK_SEARCH\])?", re.I)
_NEWS_RE = re.compile(r"\[NEWS_SEARCH:\s*(.*?)\](?:\[/NEWS_SEARCH\])?", re.I)
_ARCHIVE_RE = re.compile(r"\[ARCHIVE_SEARCH:\s*(.*?)\](?:\[/ARCHIVE_SEARCH\])?", re.I)
_SAVE_TOPIC_RE = re.compile(r"\[SAVE_TOPIC:\s*(.*?)\](?:\[/SAVE_TOPIC\])?", re.I)
_VAULT_LOOKUP_RE = re.compile(r"\[VAULT_LOOKUP:\s*(.*?)\](?:\[/VAULT_LOOKUP\])?", re.I)
_VAULT_LIST_RE = re.compile(r"\[VAULT_LIST:\s*(.*?)\](?:\[/VAULT_LIST\])?", re.I)
MAX_VAULT_TAGS = 6  # tag executions per reply honoured; the rest are left untouched

_ANALYZE_VIDEO_RE = re.compile(r"\[ANALYZE_VIDEO:\s*(.*?)\](?:\[/ANALYZE_VIDEO\])?", re.I)
_ANALYZE_CHANNEL_RE = re.compile(r"\[ANALYZE_CHANNEL:\s*(.*?)\](?:\[/ANALYZE_CHANNEL\])?", re.I)
_PROJECT_LIST_RE = re.compile(r"\[LIST_PROJECTS\](?:\[/LIST_PROJECTS\])?", re.I)
_PROJECT_CREATE_RE = re.compile(r"\[CREATE_PROJECT:\s*(.*?)\](?:\[/CREATE_PROJECT\])?", re.I)
_PROJECT_STATUS_RE = re.compile(r"\[PROJECT_STATUS:\s*(.*?)\](?:\[/PROJECT_STATUS\])?", re.I)
_MODEL_LIST_RE = re.compile(r"\[LIST_MODELS\](?:\[/LIST_MODELS\])?", re.I)
_MODEL_STATUS_RE = re.compile(r"\[MODEL_STATUS\](?:\[/MODEL_STATUS\])?", re.I)
_SWITCH_MODEL_RE = re.compile(r"\[SWITCH_MODEL:\s*(.*?)\](?:\[/SWITCH_MODEL\])?", re.I)
_NAVIGATE_TAB_RE = re.compile(r"\[NAVIGATE_TAB:\s*(.*?)\](?:\[/NAVIGATE_TAB\])?", re.I)


def process_web_research_tags(text: str) -> str:
    """Resolve [WEB_SEARCH: query] and [WEB_FETCH: url] tags into live web intelligence."""
    from app.services.web_research import web_research_service

    def _replace_search(match):
        query = match.group(1).strip()
        if not query:
            return ""
        logger.info("Resolving live web search tag: '%s'", query)
        results = web_research_service.search(query, max_results=3)
        if not results:
            return f"\n*🔍 [Web Search for '{query}': No verified results found.]*\n"
        items = []
        for r in results:
            title = r.get("title", "Source")
            snippet = r.get("snippet", "").strip()
            url = r.get("url", "")
            source = r.get("source", "Web")
            items.append(f"- **{title}** ({source}): {snippet}" + (f" [Link]({url})" if url else ""))
        return f"\n\n🔍 **[Verified Web Research: '{query}']**\n" + "\n".join(items) + "\n\n"

    def _replace_fetch(match):
        url = match.group(1).strip()
        if not url:
            return ""
        logger.info("Resolving web fetch tag: '%s'", url)
        content = web_research_service.fetch(url, max_chars=1200)
        return f"\n\n📄 **[Extracted Web Content: {url}]**\n{content}\n\n"

    def _replace_deep_research(kinds, label, emoji):
        def _replace(match):
            query = match.group(1).strip()
            if not query:
                return ""
            logger.info("Resolving %s tag: '%s'", label, query)
            try:
                from app.services.deep_research import deep_research

                data = deep_research(query, kinds=kinds, per_source=3)
                results = (data or {}).get("results") or []
            except Exception as exc:
                logger.warning("%s lookup failed for '%s': %s", label, query, exc)
                return f"\n*{emoji} [{label} for '{query}': No results]*\n"
            if not results:
                return f"\n*{emoji} [{label} for '{query}': No results]*\n"
            items = []
            for r in results:
                title = r.get("title", "Source")
                snippet = r.get("snippet", "").strip()
                url = r.get("url", "")
                source = r.get("source", "")
                items.append(f"- **{title}** ({source}): {snippet}" + (f" [Link]({url})" if url else ""))
            return f"\n\n{emoji} **[{label}: '{query}']**\n" + "\n".join(items) + "\n\n"

        return _replace

    updated = _SEARCH_RE.sub(_replace_search, text)
    updated = _FETCH_RE.sub(_replace_fetch, updated)
    updated = _BOOK_RE.sub(_replace_deep_research(("books",), "Book Search", "📚"), updated)
    updated = _NEWS_RE.sub(_replace_deep_research(("news",), "News Search", "📰"), updated)
    updated = _ARCHIVE_RE.sub(_replace_deep_research(("archives",), "Archive Search", "🗄️"), updated)
    return updated


def process_vault_tags(text: str, default_channel: str) -> str:
    """Resolve [SAVE_TOPIC: ...], [VAULT_LOOKUP: ...] and [VAULT_LIST: ...] tags
    against the shared topic vault so a strategist can push/pull topics live."""
    from app.services import topic_store

    budget = {"left": MAX_VAULT_TAGS}

    def _format_rows(rows: List[Dict[str, Any]]) -> List[str]:
        return [
            f"- {r.get('topic')} — {r.get('channel')} [{r.get('stage')}]"
            for r in rows[:8]
        ]

    def _replace_save(match):
        if budget["left"] <= 0:
            return match.group(0)
        budget["left"] -= 1
        payload = match.group(1)
        parts = [p.strip() for p in payload.split("|")]
        title = parts[0] if parts else ""
        if not title:
            return ""
        channel = parts[1].strip() if len(parts) > 1 and parts[1].strip() else default_channel
        notes = parts[2].strip() if len(parts) > 2 else ""
        logger.info("Saving topic to vault via tag: '%s' (%s)", title, channel)
        try:
            topic_store.add_topic(
                {"topic": title, "channel": channel, "notes": notes, "category": "General"},
                added_by="strategist",
                stage="potential",
            )
        except Exception as exc:
            logger.warning("SAVE_TOPIC failed for '%s': %s", title, exc)
            return f"\n*⚠️ Could not save \"{title}\" to the vault: {exc}*\n"
        return f"\n\n✅ **Saved to vault** (\"{title}\" → {channel}, stage: potential)\n\n"

    def _replace_lookup(match):
        if budget["left"] <= 0:
            return match.group(0)
        budget["left"] -= 1
        query = match.group(1).strip()
        if not query:
            return ""
        try:
            rows = topic_store.find_topics(query)
        except Exception as exc:
            logger.warning("VAULT_LOOKUP failed for '%s': %s", query, exc)
            rows = []
        if not rows:
            return f"\n*No saved topics match \"{query}\".*\n"
        return "\n\n" + "\n".join(_format_rows(rows)) + "\n\n"

    def _replace_list(match):
        if budget["left"] <= 0:
            return match.group(0)
        budget["left"] -= 1
        channel = match.group(1).strip() or default_channel
        try:
            rows = topic_store.find_topics("", channel=channel)
        except Exception as exc:
            logger.warning("VAULT_LIST failed for '%s': %s", channel, exc)
            rows = []
        if not rows:
            return f"\n*No saved topics match \"{channel}\".*\n"
        return "\n\n" + "\n".join(_format_rows(rows)) + "\n\n"

    updated = _SAVE_TOPIC_RE.sub(_replace_save, text)
    updated = _VAULT_LOOKUP_RE.sub(_replace_lookup, updated)
    updated = _VAULT_LIST_RE.sub(_replace_list, updated)
    return updated


def process_studio_tools_tags(text: str, default_channel: str) -> str:
    """Resolve video analysis, project management, model checking, and tabs tags."""
    def _replace_analyze_video(match):
        raw = match.group(1).strip()
        if not raw:
            return ""
        logger.info("Resolving live video analysis tag: '%s'", raw)
        try:
            from app.services.video_intel import analyze_video
            data = analyze_video(raw, channel=default_channel)
            video = data.get("video") or {}
            title = video.get("title") or raw
            views = video.get("view_count") or video.get("views") or "N/A"
            verdict = (data.get("verdict") or {}).get("recommendation", "Analyzed")
            patterns = ", ".join((data.get("patterns") or {}).get("topics", []))
            return (
                f"\n\n📊 **[Video Intelligence: {title}]**\n"
                f"- **Creator / Channel**: {video.get('channel_title', 'Unknown')}\n"
                f"- **Views / Engagement**: {views} views | {video.get('like_count', 'N/A')} likes\n"
                f"- **Recommendation**: {verdict}\n"
                f"- **Pillars / Patterns**: {patterns or 'True Story / Documentary Pattern'}\n\n"
            )
        except Exception as exc:
            logger.warning("Video analysis failed for '%s': %s", raw, exc)
            return f"\n*📊 [Video Analysis for '{raw}': {exc}]*\n"

    def _replace_analyze_channel(match):
        handle = match.group(1).strip()
        if not handle:
            return ""
        logger.info("Resolving live channel analysis tag: '%s'", handle)
        return (
            f"\n\n📈 **[Channel Competitor Intel: {handle}]**\n"
            f"- Channel Handle: `{handle}`\n"
            f"- Pillar Alignment: Inspected across YouTube benchmarks.\n"
            f"- Suggestion: Use Video Intelligence tab to extract specific competitor upload metrics.\n\n"
        )

    def _replace_projects_list(match):
        try:
            from core.paths import PROJECTS_DIR
            from core.models.project import Project
            if not os.path.exists(PROJECTS_DIR):
                return "\n*📁 No projects currently found in workspace.*\n"
            projects = []
            for pid in os.listdir(PROJECTS_DIR):
                p_dir = os.path.join(PROJECTS_DIR, pid)
                if os.path.isdir(p_dir):
                    try:
                        p = Project.load(pid)
                        projects.append(p)
                    except Exception:
                        continue
            if not projects:
                return "\n*📁 No production projects currently registered.*\n"
            projects.sort(key=lambda x: str(x.created_at or ""), reverse=True)
            lines = [f"- **{p.name}** ({p.brand}) — Status: `{p.status}` | Step: `{p.current_step}` (ID: `{p.id}`)" for p in projects[:6]]
            return f"\n\n📁 **[Active Studio Projects ({len(projects)})]**\n" + "\n".join(lines) + "\n\n"
        except Exception as exc:
            return f"\n*📁 [Could not list projects: {exc}]*\n"

    def _replace_create_project(match):
        payload = match.group(1).strip()
        parts = [p.strip() for p in payload.split("|")]
        title = parts[0] if parts else ""
        if not title:
            return ""
        wf_name = parts[1] if len(parts) > 1 and parts[1] else "beyond3baje_documentary"
        ch = parts[2] if len(parts) > 2 and parts[2] else default_channel
        try:
            from executive.project import project_manager
            proj = project_manager.create_project(name=title, brand=ch, workflow_name=wf_name)
            return (
                f"\n\n🚀 **[Project Created Successfully]**\n"
                f"- **Title**: {proj.name}\n"
                f"- **Brand**: {proj.brand}\n"
                f"- **Workflow**: {wf_name}\n"
                f"- **Project ID**: `{proj.id}`\n\n"
            )
        except Exception as exc:
            return f"\n*⚠️ Could not create project '{title}': {exc}*\n"

    def _replace_project_status(match):
        pid = match.group(1).strip()
        if not pid:
            return ""
        try:
            from core.models.project import Project
            p = Project.load(pid)
            return (
                f"\n\n📌 **[Project Status: {p.name}]**\n"
                f"- **Brand**: {p.brand}\n"
                f"- **Status**: `{p.status}`\n"
                f"- **Active Step**: `{p.current_step}`\n"
                f"- **Steps Completed**: {len(p.steps_history)} steps recorded\n\n"
            )
        except Exception as exc:
            return f"\n*⚠️ Project '{pid}' lookup failed: {exc}*\n"

    def _replace_model_list(match):
        try:
            import requests
            r = requests.get("http://localhost:1234/api/v0/models", timeout=1.0)
            if r.status_code == 200:
                data = r.json().get("data", [])
                items = []
                for m in data:
                    state = "🟢 LOADED" if m.get("state") == "loaded" else "⚪ Available"
                    items.append(f"- **{m.get('id')}** [{state}] ({m.get('quantization', 'GGUF')})")
                return f"\n\n🧠 **[Local LM Studio Models ({len(data)})]**\n" + "\n".join(items) + "\n\n"
        except Exception as exc:
            pass
        return "\n*🧠 [LM Studio: No active models discovered at localhost:1234]*\n"

    def _replace_model_status(match):
        try:
            from integrations.llm import load_config
            cfg = load_config()
            provider = cfg.get("selected_provider", "lm_studio")
            active_model = cfg.get(f"{provider}_model", "default")
            return (
                f"\n\n🧠 **[Active AI Engine Status]**\n"
                f"- **Provider**: `{provider}`\n"
                f"- **Active Model**: `{active_model}`\n"
                f"- **Strict Local Mode**: `{'Active (Zero Data Leaves Machine)' if cfg.get('local_only') else 'Disabled'}`\n\n"
            )
        except Exception as exc:
            return f"\n*🧠 [Could not retrieve model status: {exc}]*\n"

    def _replace_switch_model(match):
        target = match.group(1).strip()
        if not target:
            return ""
        try:
            from integrations.llm import load_config, save_config, ensure_local_model_loaded
            cfg = load_config()
            cfg["lm_studio_model"] = target
            cfg.setdefault("tiers", {}).setdefault("strong", {})["model"] = target
            save_config(cfg)
            res = ensure_local_model_loaded("lm_studio", target)
            loaded_note = " (already loaded in memory)" if res.get("already_loaded") else (" and loaded into memory" if res.get("loaded") else "")
            return f"\n\n🔄 **[Model Switched]**: Active model updated to `{target}`{loaded_note}.\n\n"
        except Exception as exc:
            return f"\n*⚠️ Could not switch model to '{target}': {exc}*\n"

    def _replace_navigate_tab(match):
        tab = match.group(1).strip().lower()
        tab_names = {
            "studio_chat": "Studio Assistant",
            "dashboard": "Dashboard",
            "projects": "Projects",
            "topic_vault": "Topic Vault",
            "board": "Topic Board",
            "analyze": "Analyze",
            "research": "Research",
            "agent_creator_studio": "Agents Workbench",
            "agents_group_chat": "Group Chat",
            "ai_workforce": "Personas",
            "departments": "Departments",
            "health": "Health",
            "settings": "Settings",
        }
        label = tab_names.get(tab, tab.title())
        return f"\n\n🧭 **[Navigate Tab: {label}]** — Switching to `{label}` tab in Studio.\n\n"

    updated = _ANALYZE_VIDEO_RE.sub(_replace_analyze_video, text)
    updated = _ANALYZE_CHANNEL_RE.sub(_replace_analyze_channel, updated)
    updated = _PROJECT_LIST_RE.sub(_replace_projects_list, updated)
    updated = _PROJECT_CREATE_RE.sub(_replace_create_project, updated)
    updated = _PROJECT_STATUS_RE.sub(_replace_project_status, updated)
    updated = _MODEL_LIST_RE.sub(_replace_model_list, updated)
    updated = _MODEL_STATUS_RE.sub(_replace_model_status, updated)
    updated = _SWITCH_MODEL_RE.sub(_replace_switch_model, updated)
    updated = _NAVIGATE_TAB_RE.sub(_replace_navigate_tab, updated)
    return updated


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
    lower = channel.lower()
    canonical = "Beyond3Baje"
    if "raat" in lower or "after dark" in lower or "afterdark" in lower:
        canonical = "Raat3Baje"
    elif "khayal" in lower:
        canonical = "Khayal3Baje"
    elif "life" in lower:
        canonical = "Life3Baje"
    elif "originals" in lower or "spilled" in lower or "studio" in lower:
        canonical = "Originals"
    elif "beyond" in lower:
        canonical = "Beyond3Baje"
    else:
        canonical = re.sub(r"[^A-Za-z0-9]", "", channel)

    path = os.path.join(PROMPTS_DIR, "channels", f"{canonical}.md")
    if not os.path.exists(path):
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

    # Autonomous privacy-preserving web search grounding when researching
    search_triggers = ["search", "research", "latest", "news", "facts", "history", "verify", "who is", "what is"]
    msg_lower = (message or "").lower()
    if any(trigger in msg_lower for trigger in search_triggers):
        try:
            from app.services.web_research import web_research_service
            brief = web_research_service.brief(message)
            if brief and not brief.startswith("No live"):
                parts.append(f"\n\n## Live Verified Web Grounding (On-Device Privacy)\n{brief}")
        except Exception as exc:
            logger.debug("Automatic web research briefing skipped: %s", exc)

    parts.append(
        "\n\n## How to answer\n"
        "- Reply in the language the creator writes in. When you produce content "
        "assets (titles, hooks, narration, dialogue) for this channel, write those in "
        "Hinglish (conversational Hindi in Roman script) unless asked otherwise.\n"
        "- Be specific to this channel's voice and the topic on the table.\n"
        "- To hand work to a specialist, write "
        "`[INVOKE_AGENT: AgentName] instructions [/INVOKE_AGENT]` and it will run.\n"
        "- To search the live web anonymously for verified facts, write `[WEB_SEARCH: keywords]`.\n"
        "- To fetch and inspect public web content safely, write `[WEB_FETCH: url]`.\n"
        "- To search open-domain books (Gutenberg, Open Library, Wikisource), write "
        "`[BOOK_SEARCH: keywords]`.\n"
        "- To search news and newspapers, India & worldwide (GDELT, Google News, historic "
        "archives), write `[NEWS_SEARCH: keywords]`.\n"
        "- To search public archives (Internet Archive, Wikisource), write "
        "`[ARCHIVE_SEARCH: keywords]`.\n"
        "- To save a topic to the Studio vault, write "
        "`[SAVE_TOPIC: the title | ChannelName | short notes]` (channel/notes optional). "
        "Use it for any channel the creator names.\n"
        "- To look up saved topics, write `[VAULT_LOOKUP: keywords]`; to list a channel's "
        "vault, write `[VAULT_LIST: ChannelName]`.\n"
        "- To analyze a competitor YouTube video, write `[ANALYZE_VIDEO: url_or_video_id]`.\n"
        "- To analyze a channel or competitor profile, write `[ANALYZE_CHANNEL: handle]`.\n"
        "- To list ongoing video production projects, write `[LIST_PROJECTS]`.\n"
        "- To create a new production project, write `[CREATE_PROJECT: Title | WorkflowName | ChannelName]`.\n"
        "- To check a project's active stage or status, write `[PROJECT_STATUS: projectId]`.\n"
        "- To inspect available local LLM models, write `[LIST_MODELS]`.\n"
        "- To view AI engine status or switch the active local model, write `[MODEL_STATUS]` or `[SWITCH_MODEL: model_id]`.\n"
        "- To navigate or link to any Studio Tab (studio_chat, dashboard, projects, topic_vault, board, analyze, research, agent_creator_studio, agents_group_chat, ai_workforce, departments, health, settings), write `[NAVIGATE_TAB: tab_name]`."
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
            output = process_web_research_tags(strip_invocations(output))
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
    reply_text = process_web_research_tags(reply_text)
    # Let the strategist push topics into / pull them out of the vault live
    # ([SAVE_TOPIC], [VAULT_LOOKUP], [VAULT_LIST]) — resolved against the shared
    # topic_store, same pattern as the web-research tags above.
    reply_text = process_vault_tags(reply_text, channel)
    # Resolve video analysis, project workflows, local models, and tabs tags live
    reply_text = process_studio_tools_tags(reply_text, channel)

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
