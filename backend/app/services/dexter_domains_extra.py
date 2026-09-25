"""Additional Dexter capability domains, kept out of ``dexter_registry`` so the
registry stays small and this file can grow without churn. Every handler is a
module-level function that lazily imports the existing route function / schema
and calls it -- the exact pattern established in ``dexter_registry`` for the
projects and topics domains.

``register_all(reg)`` appends every entry here; ``dexter_registry._build()``
calls it.
"""

from typing import Any, Dict, List


# ────────────────────────────── produce ──────────────────────────────


def _h_produce_start(p: Dict[str, Any]) -> Any:
    from app.api.produce_api import produce_video, ProduceVideoSchema
    return produce_video(p["project_id"], ProduceVideoSchema(**{k: v for k, v in p.items() if k != "project_id"}))


def _h_produce_status(p: Dict[str, Any]) -> Any:
    from app.api.produce_api import produce_video_status
    return produce_video_status(p["project_id"])


def _h_produce_plan(p: Dict[str, Any]) -> Any:
    from app.api.produce_api import produce_plan, ProducePlanSchema
    return produce_plan(ProducePlanSchema(**p))


# ────────────────────────────── catalog ──────────────────────────────


def _h_brands(p: Dict[str, Any]) -> Any:
    from app.main import get_brands
    return get_brands()


def _h_workflows(p: Dict[str, Any]) -> Any:
    from app.main import get_workflows
    return get_workflows()


def _h_assets_list(p: Dict[str, Any]) -> Any:
    from app.main import get_assets
    return get_assets(type=p.get("type"), tag=p.get("tag"), query=p.get("query"))


def _h_asset_register(p: Dict[str, Any]) -> Any:
    from app.main import register_asset, AssetRegisterSchema
    return register_asset(AssetRegisterSchema(**p))


def _h_settings_get(p: Dict[str, Any]) -> Any:
    from app.main import get_settings
    return get_settings()


def _h_settings_set(p: Dict[str, Any]) -> Any:
    from app.main import update_settings, SettingsSchema
    return update_settings(SettingsSchema(**p))


def _h_local_models(p: Dict[str, Any]) -> Any:
    from app.main import get_local_models
    return get_local_models()


# ────────────────────────────── research ──────────────────────────────


def _h_research_search(p: Dict[str, Any]) -> Any:
    from app.main import run_research_search
    return run_research_search(q=p["q"], limit=int(p.get("limit", 5)))


def _h_research_fetch(p: Dict[str, Any]) -> Any:
    from app.main import run_research_fetch
    return run_research_fetch(url=p["url"])


def _h_research_sources(p: Dict[str, Any]) -> Any:
    from app.main import run_source_research
    return run_source_research(q=p["q"], kinds=p.get("kinds", "news,archives,books"), limit=int(p.get("limit", 5)))


def _h_searxng_test(p: Dict[str, Any]) -> Any:
    from app.main import test_searxng_connection
    return test_searxng_connection(url=p.get("url"))


# ────────────────────────────── studio ──────────────────────────────


def _h_studio_state(p: Dict[str, Any]) -> Any:
    from app.api.studio_api import studio_state
    return studio_state()


def _h_studio_chat(p: Dict[str, Any]) -> Any:
    from app.api.studio_api import studio_chat, StudioChatSchema
    return studio_chat(StudioChatSchema(**p))


def _h_studio_search(p: Dict[str, Any]) -> Any:
    from app.api.studio_api import studio_search, StudioSearchSchema
    return studio_search(StudioSearchSchema(**p))


# ────────────────────────── agents workbench ──────────────────────────


def _h_agent_list(p: Dict[str, Any]) -> Any:
    from app.api.agents_api import list_all_agents
    return list_all_agents()


def _h_agent_save(p: Dict[str, Any]) -> Any:
    from app.api.agents_api import create_or_update_agent, AgentSchema
    return create_or_update_agent(AgentSchema(**p))


def _h_agent_delete(p: Dict[str, Any]) -> Any:
    from app.api.agents_api import delete_agent
    return delete_agent(p["agent_id"])


def _h_group_chat(p: Dict[str, Any]) -> Any:
    from app.api.agents_api import execute_group_chat, GroupChatRequestSchema
    return execute_group_chat(GroupChatRequestSchema(**p))


def _h_agents_all(p: Dict[str, Any]) -> Any:
    from app.main import get_all_agents
    return get_all_agents(department=p.get("department"))


# ──────────────────────────── departments ────────────────────────────


def _h_department_list(p: Dict[str, Any]) -> Any:
    from app.api.departments_api import get_departments
    return get_departments()


def _h_department_execute(p: Dict[str, Any]) -> Any:
    from app.api.departments_api import execute_department_task, DepartmentTaskSchema
    return execute_department_task(p["name"], DepartmentTaskSchema(**{k: v for k, v in p.items() if k != "name"}))


# ───────────────────────────── buzzbrain ─────────────────────────────


def _h_buzzbrain_snapshot(p: Dict[str, Any]) -> Any:
    from app.api.buzzbrain_api import ingest_snapshot, SnapshotSchema
    return ingest_snapshot(SnapshotSchema(**p))


def _h_buzzbrain_latest(p: Dict[str, Any]) -> Any:
    from app.api.buzzbrain_api import latest
    return latest(n=int(p.get("n", 5)), mine=p.get("mine"))


def _h_buzzbrain_channels(p: Dict[str, Any]) -> Any:
    from app.api.buzzbrain_api import channels
    return channels()


def _h_buzzbrain_video(p: Dict[str, Any]) -> Any:
    from app.api.buzzbrain_api import video_history
    return video_history(p["video_id"], limit=int(p.get("limit", 50)))


# ──────────────────────────── video intel ────────────────────────────


def _h_video_analyze(p: Dict[str, Any]) -> Any:
    from app.api.video_intel_api import analyze, AnalyzeSchema
    return analyze(AnalyzeSchema(**p))


def _h_video_recent(p: Dict[str, Any]) -> Any:
    from app.api.video_intel_api import recent
    return recent()


def _h_video_one(p: Dict[str, Any]) -> Any:
    from app.api.video_intel_api import one
    return one(p["item_id"])


# ────────────────────────── memory / system ──────────────────────────


def _h_memory_get(p: Dict[str, Any]) -> Any:
    from app.main import get_memory_logs
    return get_memory_logs(scope=p.get("scope", "agent"), owner=p.get("owner", "Beyond3BajeStrategist"), limit=int(p.get("limit", 10)))


def _h_memory_clear(p: Dict[str, Any]) -> Any:
    from app.main import clear_memory_logs
    return clear_memory_logs(scope=p.get("scope", "agent"), owner=p.get("owner", "Beyond3BajeStrategist"))


def _h_diagnostics(p: Dict[str, Any]) -> Any:
    from app.main import get_diagnostics
    return get_diagnostics()


# ─────────────────────────────── registration ───────────────────────────────


def register_all(reg: List[Dict[str, Any]]) -> None:
    reg.extend([
        # produce
        {"name": "produce_start", "domain": "produce", "method": "POST", "path": "/api/projects/{id}/produce_video",
         "kind": "write", "params": {"project_id": "str", "recording_path": "str", "mode": "str?", "settings_override": "dict?"},
         "summary": "Kick off video production for a project.", "handler": _h_produce_start},
        {"name": "produce_status", "domain": "produce", "method": "GET", "path": "/api/projects/{id}/produce_video/status",
         "kind": "read", "params": {"project_id": "str"}, "summary": "Production status.", "handler": _h_produce_status},
        {"name": "produce_plan", "domain": "produce", "method": "POST", "path": "/api/produce/plan",
         "kind": "read", "params": {"brand": "str", "script_text": "str?", "transcript": "str?"}, "summary": "Plan a video's visuals.", "handler": _h_produce_plan},
        # catalog
        {"name": "brands", "domain": "catalog", "method": "GET", "path": "/api/brands",
         "kind": "read", "params": {}, "summary": "List brands/channels.", "handler": _h_brands},
        {"name": "workflows", "domain": "catalog", "method": "GET", "path": "/api/workflows",
         "kind": "read", "params": {}, "summary": "List workflow definitions.", "handler": _h_workflows},
        {"name": "assets_list", "domain": "catalog", "method": "GET", "path": "/api/assets",
         "kind": "read", "params": {"type": "str?", "tag": "str?", "query": "str?"}, "summary": "List/search the asset library.", "handler": _h_assets_list},
        {"name": "asset_register", "domain": "catalog", "method": "POST", "path": "/api/assets",
         "kind": "write", "params": {"title": "str", "type": "str", "tags": "list", "file_path": "str"}, "summary": "Register an asset.", "handler": _h_asset_register},
        {"name": "settings_get", "domain": "catalog", "method": "GET", "path": "/api/settings",
         "kind": "read", "params": {}, "summary": "Read Studio settings.", "handler": _h_settings_get},
        {"name": "settings_set", "domain": "catalog", "method": "POST", "path": "/api/settings",
         "kind": "write", "params": {"selected_provider": "str?", "local_only": "bool?", "...": "any SettingsSchema field"}, "summary": "Update Studio settings.", "handler": _h_settings_set},
        {"name": "local_models", "domain": "catalog", "method": "GET", "path": "/api/settings/local-models",
         "kind": "read", "params": {}, "summary": "List local models available.", "handler": _h_local_models},
        # research
        {"name": "research_search", "domain": "research", "method": "GET", "path": "/api/research/search",
         "kind": "read", "params": {"q": "str", "limit": "int?"}, "summary": "Anonymous web search.", "handler": _h_research_search},
        {"name": "research_fetch", "domain": "research", "method": "GET", "path": "/api/research/fetch",
         "kind": "read", "params": {"url": "str"}, "summary": "Fetch+extract a URL.", "handler": _h_research_fetch},
        {"name": "research_sources", "domain": "research", "method": "GET", "path": "/api/research/sources",
         "kind": "read", "params": {"q": "str", "kinds": "str?", "limit": "int?"}, "summary": "News/archives/books search.", "handler": _h_research_sources},
        {"name": "searxng_test", "domain": "research", "method": "GET", "path": "/api/research/searxng-test",
         "kind": "read", "params": {"url": "str?"}, "summary": "Test a SearXNG endpoint.", "handler": _h_searxng_test},
        # studio
        {"name": "studio_state", "domain": "studio", "method": "GET", "path": "/api/studio/state",
         "kind": "read", "params": {}, "summary": "What is going on in the Studio.", "handler": _h_studio_state},
        {"name": "studio_chat", "domain": "studio", "method": "POST", "path": "/api/studio/chat",
         "kind": "write", "params": {"message": "str", "channel": "str?", "agent_name": "str?", "history": "list?", "context_topic": "dict?"},
         "summary": "Run a Studio Assistant turn.", "handler": _h_studio_chat},
        {"name": "studio_search", "domain": "studio", "method": "POST", "path": "/api/studio/search",
         "kind": "read", "params": {"query": "str", "kind": "str?"}, "summary": "Live web/news/books/archives search.", "handler": _h_studio_search},
        # agents workbench
        {"name": "agent_list", "domain": "agents", "method": "GET", "path": "/api/agents-workbench/agents",
         "kind": "read", "params": {}, "summary": "List custom agents.", "handler": _h_agent_list},
        {"name": "agent_save", "domain": "agents", "method": "POST", "path": "/api/agents-workbench/agents",
         "kind": "write", "params": {"name": "str", "role": "str", "systemPrompt": "str", "id": "str?"}, "summary": "Create/update a custom agent.", "handler": _h_agent_save},
        {"name": "agent_delete", "domain": "agents", "method": "DELETE", "path": "/api/agents-workbench/agents/{id}",
         "kind": "dangerous", "params": {"agent_id": "str"}, "summary": "Delete a custom agent.", "handler": _h_agent_delete},
        {"name": "group_chat", "domain": "agents", "method": "POST", "path": "/api/agents-workbench/chat/group-chat",
         "kind": "read", "params": {"agentIds": "list", "userMessage": "str"}, "summary": "Run a multi-agent group chat.", "handler": _h_group_chat},
        {"name": "agents_all", "domain": "agents", "method": "GET", "path": "/api/agents",
         "kind": "read", "params": {"department": "str?"}, "summary": "List the whole persona roster.", "handler": _h_agents_all},
        # departments
        {"name": "department_list", "domain": "departments", "method": "GET", "path": "/api/departments",
         "kind": "read", "params": {}, "summary": "List departments.", "handler": _h_department_list},
        {"name": "department_execute", "domain": "departments", "method": "POST", "path": "/api/departments/{name}/execute",
         "kind": "write", "params": {"name": "str", "task": "str", "role": "str?", "require_json": "bool?"}, "summary": "Run a task through a department.", "handler": _h_department_execute},
        # buzzbrain
        {"name": "buzzbrain_snapshot", "domain": "buzzbrain", "method": "POST", "path": "/api/buzzbrain/snapshot",
         "kind": "write", "params": {"videoMeta": "dict", "metrics": "dict", "captured_at": "str?"}, "summary": "Ingest a BuzzBrain snapshot.", "handler": _h_buzzbrain_snapshot},
        {"name": "buzzbrain_latest", "domain": "buzzbrain", "method": "GET", "path": "/api/buzzbrain/latest",
         "kind": "read", "params": {"n": "int?", "mine": "bool?"}, "summary": "Latest snapshots.", "handler": _h_buzzbrain_latest},
        {"name": "buzzbrain_channels", "domain": "buzzbrain", "method": "GET", "path": "/api/buzzbrain/channels",
         "kind": "read", "params": {}, "summary": "Channels BuzzBrain has seen.", "handler": _h_buzzbrain_channels},
        {"name": "buzzbrain_video", "domain": "buzzbrain", "method": "GET", "path": "/api/buzzbrain/videos/{id}",
         "kind": "read", "params": {"video_id": "str", "limit": "int?"}, "summary": "One video's snapshot history.", "handler": _h_buzzbrain_video},
        # video intel
        {"name": "video_analyze", "domain": "video_intel", "method": "POST", "path": "/api/video-intel/analyze",
         "kind": "write", "params": {"url": "str", "channel": "str?", "force": "bool?"}, "summary": "Analyse a YouTube video/channel.", "handler": _h_video_analyze},
        {"name": "video_recent", "domain": "video_intel", "method": "GET", "path": "/api/video-intel/recent",
         "kind": "read", "params": {}, "summary": "Recently analysed videos.", "handler": _h_video_recent},
        {"name": "video_one", "domain": "video_intel", "method": "GET", "path": "/api/video-intel/{id}",
         "kind": "read", "params": {"item_id": "str"}, "summary": "One analysis dossier.", "handler": _h_video_one},
        # memory / system
        {"name": "memory_get", "domain": "system", "method": "GET", "path": "/api/memory",
         "kind": "read", "params": {"scope": "str?", "owner": "str?", "limit": "int?"}, "summary": "Read agent/session memory.", "handler": _h_memory_get},
        {"name": "memory_clear", "domain": "system", "method": "POST", "path": "/api/memory/clear",
         "kind": "dangerous", "params": {"scope": "str?", "owner": "str?"}, "summary": "Clear a memory scope.", "handler": _h_memory_clear},
        {"name": "diagnostics", "domain": "system", "method": "GET", "path": "/api/diagnostics",
         "kind": "read", "params": {}, "summary": "System diagnostics.", "handler": _h_diagnostics},
    ])
