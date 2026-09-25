"""Dexter control gateway: one registry of every action the Studio can perform,
invoked uniformly through ``/api/studio/invoke`` and introspected through
``/api/studio/capabilities``.

Design
------
Rather than hand-write a Dexter wrapper for each of the ~45 endpoints, every
action is one entry in ``CAPABILITIES`` whose ``handler`` reuses the existing
route function / service. Handlers lazily import ``app.main`` (and routers)
inside their bodies so importing this module never triggers the circular
import that mounting the routers would.

- ``invoke(action, params, allow_dangerous=...)`` looks the action up, gates
  destructive ones, stamps ``dexter`` provenance on writes, runs the handler,
  normalises errors, and emits a ``dexter_action`` event so the Studio reflects
  the change live over the existing SSE stream.
- ``manifest()`` is the same registry minus the callables -- the single source
  of truth for ``/api/studio/capabilities``.

Later work packages add domains by defining a ``_register_<domain>(reg)``
function and calling it in ``_build()``; they never edit existing entries.
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional

from starlette.responses import Response as _Response

from app.services.events import bus

logger = logging.getLogger("buzzcaf_ai.dexter_registry")

DEXTER = "dexter"


# ───────────────────────── event + result plumbing ─────────────────────────


def _event(action: str, detail: Dict[str, Any]) -> None:
    """Publish a ``dexter_action`` event; the bus must never take a call down."""
    try:
        bus.publish("dexter_action", {"action": action, **detail})
    except Exception:  # pragma: no cover - defensive
        logger.debug("could not publish dexter_action for %s", action, exc_info=True)


def _coerce_result(raw: Any) -> tuple[int, Any]:
    """Normalise a handler's return into ``(status_code, data)``.

    Most route functions return a plain dict; a few return a Starlette/JSON
    ``Response`` (e.g. a 400/404 body) instead of raising, so unwrap those and
    surface their status so ``invoke`` can report the error uniformly.
    """
    if isinstance(raw, _Response):
        body = getattr(raw, "body", b"") or b""
        try:
            data = json.loads(body.decode("utf-8")) if body else None
        except Exception:
            data = None
        return int(getattr(raw, "status_code", 200)), data
    return 200, raw


# ───────────────────────────── projects domain ─────────────────────────────


def _h_project_list(p: Dict[str, Any]) -> Any:
    from app.main import list_projects
    return list_projects()


def _h_project_get(p: Dict[str, Any]) -> Any:
    from app.main import get_project
    return get_project(p["project_id"])


def _h_project_create(p: Dict[str, Any]) -> Any:
    from app.main import create_project, ProjectCreateSchema
    fields = {k: v for k, v in p.items() if k != "created_by"}
    data = create_project(ProjectCreateSchema(**fields))
    # Provenance: projects keep extras in project.metadata.
    try:
        from core.models.project import Project
        proj = Project.load(data["id"])
        proj.metadata["created_by"] = DEXTER
        proj.save()
        return proj.to_dict()
    except Exception:  # pragma: no cover - provenance is best-effort
        return data


def _h_project_delete(p: Dict[str, Any]) -> Any:
    from app.main import delete_project
    return delete_project(p["project_id"])


def _h_project_set_duration(p: Dict[str, Any]) -> Any:
    from app.main import set_project_duration, DurationSchema
    return set_project_duration(p["project_id"], DurationSchema(minutes=p.get("minutes")))


def _h_project_execute_step(p: Dict[str, Any]) -> Any:
    from app.main import execute_project_step, ExecuteStepSchema
    return execute_project_step(p["project_id"], ExecuteStepSchema(feedback=p.get("feedback"), allow_all=p.get("allow_all")))


def _h_project_approve_step(p: Dict[str, Any]) -> Any:
    from app.main import approve_project_step, ExecuteStepSchema
    return approve_project_step(p["project_id"], ExecuteStepSchema(feedback=p.get("feedback"), allow_all=p.get("allow_all")))


def _h_project_allow_all(p: Dict[str, Any]) -> Any:
    from app.main import allow_all_and_advance
    return allow_all_and_advance(p["project_id"])


def _h_project_toggle_allow_all(p: Dict[str, Any]) -> Any:
    from app.main import toggle_project_allow_all
    return toggle_project_allow_all(p["project_id"])


def _h_project_run_all(p: Dict[str, Any]) -> Any:
    from app.main import run_all_project_steps
    return run_all_project_steps(p["project_id"])


def _h_project_logs(p: Dict[str, Any]) -> Any:
    from app.main import get_project_execution_logs
    return get_project_execution_logs(p["project_id"])


def _h_project_asset(p: Dict[str, Any]) -> Any:
    from app.main import get_project_asset
    return get_project_asset(p["project_id"], p["asset_name"])


def _register_projects(reg: List[Dict[str, Any]]) -> None:
    reg.extend([
        {"name": "project_list", "domain": "projects", "method": "GET", "path": "/api/projects",
         "kind": "read", "params": {}, "summary": "List every project.", "handler": _h_project_list},
        {"name": "project_get", "domain": "projects", "method": "GET", "path": "/api/projects/{id}",
         "kind": "read", "params": {"project_id": "str"}, "summary": "Get one project.", "handler": _h_project_get},
        {"name": "project_create", "domain": "projects", "method": "POST", "path": "/api/projects",
         "kind": "write", "params": {"name": "str", "brand": "str", "workflow_name": "str", "target_duration_minutes": "float?", "allow_all": "bool?"},
         "summary": "Create a project (tagged created_by=dexter).", "handler": _h_project_create},
        {"name": "project_delete", "domain": "projects", "method": "DELETE", "path": "/api/projects/{id}",
         "kind": "dangerous", "params": {"project_id": "str"}, "summary": "Delete a project.", "handler": _h_project_delete},
        {"name": "project_set_duration", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/duration",
         "kind": "write", "params": {"project_id": "str", "minutes": "float?"}, "summary": "Set/clear target runtime.", "handler": _h_project_set_duration},
        {"name": "project_execute_step", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/execute",
         "kind": "write", "params": {"project_id": "str", "feedback": "str?", "allow_all": "bool?"}, "summary": "Run the current workflow step.", "handler": _h_project_execute_step},
        {"name": "project_approve_step", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/approve",
         "kind": "write", "params": {"project_id": "str", "feedback": "str?", "allow_all": "bool?"}, "summary": "Approve a paused step.", "handler": _h_project_approve_step},
        {"name": "project_allow_all", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/allow_all",
         "kind": "write", "params": {"project_id": "str"}, "summary": "Approve all and advance.", "handler": _h_project_allow_all},
        {"name": "project_toggle_allow_all", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/toggle_allow_all",
         "kind": "write", "params": {"project_id": "str"}, "summary": "Toggle auto-approve.", "handler": _h_project_toggle_allow_all},
        {"name": "project_run_all", "domain": "projects", "method": "POST", "path": "/api/projects/{id}/run_all",
         "kind": "write", "params": {"project_id": "str"}, "summary": "Run every remaining step.", "handler": _h_project_run_all},
        {"name": "project_logs", "domain": "projects", "method": "GET", "path": "/api/projects/{id}/logs",
         "kind": "read", "params": {"project_id": "str"}, "summary": "Execution logs.", "handler": _h_project_logs},
        {"name": "project_asset", "domain": "projects", "method": "GET", "path": "/api/projects/{id}/asset/{asset_name}",
         "kind": "read", "params": {"project_id": "str", "asset_name": "str"}, "summary": "Read a project asset.", "handler": _h_project_asset},
    ])


# ────────────────────────────── topics domain ──────────────────────────────


def _h_topic_discover(p: Dict[str, Any]) -> Any:
    from app.main import discover_channel_topics, TopicDiscoverSchema
    return discover_channel_topics(TopicDiscoverSchema(**p))


def _h_topic_validate(p: Dict[str, Any]) -> Any:
    from app.main import validate_topic_endpoint, TopicValidateSchema
    return validate_topic_endpoint(TopicValidateSchema(**p))


def _h_topic_list(p: Dict[str, Any]) -> Any:
    from app.main import get_saved_topics
    return get_saved_topics(p.get("channel"))


def _h_topic_save(p: Dict[str, Any]) -> Any:
    from app.main import save_topic, SavedTopicSchema
    return save_topic(SavedTopicSchema(**p))


def _h_topic_update(p: Dict[str, Any]) -> Any:
    from app.main import update_saved_topic, TopicUpdateSchema
    return update_saved_topic(TopicUpdateSchema(**p))


def _h_topic_delete(p: Dict[str, Any]) -> Any:
    from app.main import delete_saved_topic
    return delete_saved_topic(p)


def _h_topic_research_and_save(p: Dict[str, Any]) -> Any:
    from app.api.studio_api import studio_research_and_save, ResearchAndSaveSchema
    return studio_research_and_save(ResearchAndSaveSchema(**p))


def _h_topic_chat_history(p: Dict[str, Any]) -> Any:
    from app.main import get_chat_history
    return get_chat_history(p["channel"], p["agent_name"])


def _h_topic_agent_chat(p: Dict[str, Any]) -> Any:
    from app.main import agent_chat, AgentChatSchema
    return agent_chat(AgentChatSchema(**p))


def _register_topics(reg: List[Dict[str, Any]]) -> None:
    reg.extend([
        {"name": "topic_discover", "domain": "topics", "method": "POST", "path": "/api/topics/discover",
         "kind": "read", "params": {"channel": "str"}, "summary": "Ask the strategist for fresh topics.", "handler": _h_topic_discover},
        {"name": "topic_validate", "domain": "topics", "method": "POST", "path": "/api/topics/validate",
         "kind": "read", "params": {"topic": "str", "channel": "str?", "force": "bool?"}, "summary": "Demand-validate a topic.", "handler": _h_topic_validate},
        {"name": "topic_list", "domain": "topics", "method": "GET", "path": "/api/topics/saved",
         "kind": "read", "params": {"channel": "str?"}, "summary": "List saved vault topics.", "handler": _h_topic_list},
        {"name": "topic_save", "domain": "topics", "method": "POST", "path": "/api/topics/save",
         "kind": "write", "params": {"topic": "str", "channel": "str", "category": "str?", "stage": "str?", "notes": "str?"},
         "summary": "Save a topic to the vault (tagged dexter).", "handler": _h_topic_save, "provenance": "added_by"},
        {"name": "topic_update", "domain": "topics", "method": "POST", "path": "/api/topics/update",
         "kind": "write", "params": {"id": "str", "stage": "str?"}, "summary": "Move a topic's Kanban stage / edit it.", "handler": _h_topic_update},
        {"name": "topic_delete", "domain": "topics", "method": "POST", "path": "/api/topics/delete",
         "kind": "dangerous", "params": {"id": "str?", "topic": "str?"}, "summary": "Delete a vault topic.", "handler": _h_topic_delete},
        {"name": "topic_research_and_save", "domain": "topics", "method": "POST", "path": "/api/studio/topics/research_and_save",
         "kind": "write", "params": {"topic": "str", "channel": "str?"}, "summary": "Research a topic and save it tagged dexter, stage=researching.", "handler": _h_topic_research_and_save},
        {"name": "topic_chat_history", "domain": "topics", "method": "GET", "path": "/api/topics/chat_history",
         "kind": "read", "params": {"channel": "str", "agent_name": "str"}, "summary": "Strategist chat history.", "handler": _h_topic_chat_history},
        {"name": "topic_agent_chat", "domain": "topics", "method": "POST", "path": "/api/topics/agent_chat",
         "kind": "write", "params": {"agent_name": "str", "channel": "str", "message": "str", "context_topic": "dict?", "chat_history": "list?"},
         "summary": "One strategist chat turn.", "handler": _h_topic_agent_chat},
    ])


# ─────────────────────────────── assembly ───────────────────────────────


def _build() -> List[Dict[str, Any]]:
    reg: List[Dict[str, Any]] = []
    _register_projects(reg)
    _register_topics(reg)
    # The remaining domains (produce, catalog, research, studio, agents,
    # departments, buzzbrain, video_intel, system) live in a sibling module so
    # this file stays small; they follow the exact same entry shape.
    from app.services.dexter_domains_extra import register_all as _register_extra
    _register_extra(reg)
    return reg


CAPABILITIES: List[Dict[str, Any]] = _build()
_BY_NAME: Dict[str, Dict[str, Any]] = {c["name"]: c for c in CAPABILITIES}


# ─────────────────────────────── public API ───────────────────────────────


def manifest() -> Dict[str, Any]:
    """The registry as data (no callables) — powers /api/studio/capabilities."""
    keys = ("name", "domain", "method", "path", "kind", "params", "summary")
    return {
        "app": "buzzcaf",
        "count": len(CAPABILITIES),
        "actor": DEXTER,
        "actions": [{k: c.get(k) for k in keys} for c in CAPABILITIES],
    }


def invoke(
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    actor: str = DEXTER,
    allow_dangerous: bool = False,
) -> Dict[str, Any]:
    """Run one registered action and return a normalised envelope.

    Never raises: an unknown action, a gated destructive action, or a handler
    failure all come back as ``{"status": "error", "code": ..., "error": ...}``.
    """
    params = dict(params or {})
    cap = _BY_NAME.get(action)
    if cap is None:
        return {"status": "error", "code": 404, "error": f"unknown action '{action}'"}

    kind = cap["kind"]
    if kind == "dangerous" and not allow_dangerous:
        return {"status": "error", "code": 403, "error": f"'{action}' is destructive; pass allow_dangerous=true to run it"}

    if kind in ("write", "dangerous") and cap.get("provenance"):
        params.setdefault(cap["provenance"], actor)

    try:
        raw = cap["handler"](params)
    except KeyError as exc:  # a required param was missing
        return {"status": "error", "code": 422, "error": f"missing parameter: {exc}"}
    except Exception as exc:
        code = int(getattr(exc, "status_code", 500) or 500)
        detail = getattr(exc, "detail", None)
        return {"status": "error", "code": code, "error": str(detail if detail is not None else exc)}

    code, data = _coerce_result(raw)
    if code >= 400:
        msg = data
        if isinstance(data, dict):
            msg = data.get("message") or data.get("detail") or data
        return {"status": "error", "code": code, "error": msg}

    if kind in ("write", "dangerous"):
        _event(action, {"kind": kind, "id": (data.get("id") if isinstance(data, dict) else None)})

    return {"status": "success", "action": action, "kind": kind, "result": data}
