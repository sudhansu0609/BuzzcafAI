"""
The control surface Dexter drives (roadmap v5, 3.1).

    GET  /api/studio/state    one call that answers "what is going on in the Studio"
    POST /api/studio/chat     a Studio Assistant turn (same engine as /api/topics/agent_chat)
    GET  /api/studio/events   SSE: project_created, step_started, step_completed,
                              approval_needed, step_failed, buzzbrain_snapshot
    POST /api/studio/shutdown close the Studio down from the outside (loopback only)

The approve alias lives in app/main.py next to the execute route it wraps.
"""

import ipaddress
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.events import bus
from app.services import topic_store
from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.studio_api")

router = APIRouter(prefix="/api/studio", tags=["Studio control"])


class StudioChatSchema(BaseModel):
    message: str
    channel: Optional[str] = None
    agent_name: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    context_topic: Optional[Dict[str, Any]] = None


class ResearchAndSaveSchema(BaseModel):
    topic: str
    channel: Optional[str] = None


class TopicSaveSchema(BaseModel):
    topic: str
    channel: Optional[str] = None
    category: Optional[str] = None
    notes: Optional[str] = None
    stage: Optional[str] = None

    class Config:
        extra = "allow"


class TopicUpdateSchema(BaseModel):
    id: str
    stage: Optional[str] = None

    class Config:
        extra = "allow"


class TopicDeleteSchema(BaseModel):
    id: Optional[str] = None
    topic: Optional[str] = None


class StudioSearchSchema(BaseModel):
    query: str
    kind: Optional[str] = "web"


def _dexter_event(action: str, detail: Dict[str, Any]) -> None:
    """Publish a `dexter_action` event; the bus must never take a route down."""
    try:
        bus.publish("dexter_action", {"action": action, **detail})
    except Exception:
        pass


def _last_step(project: Dict[str, Any]) -> Dict[str, Any]:
    history = project.get("steps_history") or []
    return history[-1] if history else {}


def _saved_topics_count() -> int:
    path = os.path.join(KNOWLEDGE_DIR, "saved_topics.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        topics = data.get("topics", data) if isinstance(data, dict) else data
        return len(topics) if isinstance(topics, list) else 0
    except Exception:
        return 0


def _buzzbrain_summary() -> Dict[str, Any]:
    path = os.path.join(KNOWLEDGE_DIR, "buzzbrain", "index.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            index = json.load(handle)
        return {
            "last_snapshot_at": index.get("last_snapshot_at"),
            "channels": len(index.get("channels", {})),
            "videos": len(index.get("videos", {})),
        }
    except Exception:
        return {"last_snapshot_at": None, "channels": 0, "videos": 0}


@router.get("/state")
def studio_state():
    # Imported lazily: app.main mounts this router, so a top-level import would
    # be circular.
    from app.main import STUDIO_VERSION, get_brands, list_projects
    from integrations.llm import load_config

    projects = list_projects()
    pending = []
    counts = {"total": len(projects), "in_progress": 0, "paused_for_approval": 0, "done": 0}
    for project in projects:
        step = _last_step(project)
        if project.get("status") == "completed":
            counts["done"] += 1
        else:
            counts["in_progress"] += 1
        if step.get("status") == "paused_for_approval":
            counts["paused_for_approval"] += 1
            pending.append({
                "project_id": project.get("id"),
                "name": project.get("name"),
                "brand": project.get("brand"),
                "step": step.get("step_name"),
                "agent": step.get("agent_name"),
                "since": step.get("started_at"),
            })

    active = next((p for p in projects if p.get("status") != "completed"), None)
    config = load_config()
    return {
        "app": "buzzcaf",
        "version": STUDIO_VERSION,
        "llm_provider": config.get("selected_provider") or ("gemini" if config.get("prefer_gemini", True) else "lm_studio"),
        "brands": get_brands(),
        "projects": counts,
        "active_project": (
            {
                "id": active.get("id"), "name": active.get("name"), "brand": active.get("brand"),
                "status": active.get("status"), "current_step": active.get("current_step"),
            } if active else None
        ),
        "pending_approvals": pending,
        "saved_topics_count": _saved_topics_count(),
        "buzzbrain": _buzzbrain_summary(),
        "events": {"subscribers": bus.subscriber_count, "last": {k: v["ts"] for k, v in bus.last.items()}},
    }


@router.post("/chat")
def studio_chat(payload: StudioChatSchema):
    from app.services.studio_chat import run_chat, strategist_for

    channel = (payload.channel or "").strip() or "Beyond3Baje"
    agent_name = (payload.agent_name or "").strip() or strategist_for(channel)
    try:
        return run_chat(
            message=payload.message,
            channel=channel,
            agent_name=agent_name,
            history=payload.history,
            context_topic=payload.context_topic,
        )
    except Exception as exc:
        logger.error("studio chat failed for %s: %s", agent_name, exc, exc_info=True)
        detail = f"{agent_name} could not be reached: {exc}"
        return JSONResponse(
            status_code=502,
            content={
                "status": "error", "simulated": True, "error": str(exc), "detail": detail,
                "agent_name": agent_name, "channel": channel, "reply": detail,
            },
        )


@router.get("/capabilities")
def studio_capabilities():
    """The full manifest of every action Dexter can invoke, from the registry
    (single source of truth shared with POST /api/studio/invoke)."""
    from app.services import dexter_registry

    return dexter_registry.manifest()


class InvokeSchema(BaseModel):
    action: str
    params: Optional[Dict[str, Any]] = {}
    allow_dangerous: Optional[bool] = False


@router.post("/invoke")
def studio_invoke(payload: InvokeSchema):
    """Dexter's single entry point: run any registered Studio action by name.

    Reuses the app's own handlers, tags writes as ``dexter``, and emits a
    ``dexter_action`` event so the Studio reflects the change live. Destructive
    actions require ``allow_dangerous: true``. See GET /api/studio/capabilities
    for the action list and their params.
    """
    from app.services import dexter_registry

    result = dexter_registry.invoke(
        payload.action,
        payload.params or {},
        allow_dangerous=bool(payload.allow_dangerous),
    )
    if result.get("status") == "error":
        return JSONResponse(status_code=int(result.get("code", 400)), content=result)
    return result


@router.post("/topics/research_and_save")
def studio_research_and_save(payload: ResearchAndSaveSchema):
    from app.services.topic_validation import validate_topic

    channel = payload.channel or ""
    try:
        result = validate_topic(payload.topic, channel)
    except Exception as exc:
        logger.error("research_and_save validate_topic failed: %s", exc, exc_info=True)
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})

    verdict = (result or {}).get("verdict") or {}
    demand = verdict.get("demand") if isinstance(verdict, dict) else None
    notes = demand.get("reason", "") if isinstance(demand, dict) else ""
    row = topic_store.add_topic(
        {
            "topic": payload.topic,
            "channel": channel,
            "category": "General",
            "notes": notes,
            "validation": verdict,
        },
        added_by="dexter",
        stage="researching",
    )
    _dexter_event("research_and_save", {"topic": payload.topic, "channel": channel})
    return {"status": "success", "topic": row, "validation": result}


@router.post("/topics/save")
def studio_topic_save(payload: TopicSaveSchema):
    row = topic_store.add_topic(payload.dict(exclude_none=True), added_by="dexter")
    _dexter_event("topics_save", {"topic": payload.topic, "channel": payload.channel or ""})
    return {"status": "success", "topic": row}


@router.post("/topics/update")
def studio_topic_update(payload: TopicUpdateSchema):
    fields = payload.dict(exclude_none=True, exclude={"id"})
    if "stage" in fields and fields["stage"] not in topic_store.STAGES:
        return JSONResponse(status_code=400, content={"status": "error", "message": "invalid stage"})
    row = topic_store.update_topic(payload.id, fields)
    if row is None:
        return JSONResponse(status_code=404, content={"status": "error", "message": "topic not found"})
    _dexter_event("topics_update", {"id": payload.id})
    return {"status": "success", "topic": row}


@router.post("/topics/delete")
def studio_topic_delete(payload: TopicDeleteSchema):
    remaining = topic_store.delete_topic(topic_id=payload.id, topic=payload.topic)
    _dexter_event("topics_delete", {"id": payload.id or "", "topic": payload.topic or ""})
    return {"status": "success", "remaining": remaining}


@router.get("/topics")
def studio_topics_list():
    return {"status": "success", "topics": topic_store.load_topics()}


@router.post("/search")
def studio_search(payload: StudioSearchSchema):
    kind = (payload.kind or "web").strip().lower()
    try:
        if kind == "web":
            from app.services.web_research import web_research_service

            results = web_research_service.search(payload.query, max_results=5)
        else:
            from app.services.deep_research import deep_research

            results = deep_research(payload.query, kinds=(kind,), per_source=3)
    except Exception as exc:
        logger.error("studio search failed for '%s' (%s): %s", payload.query, kind, exc, exc_info=True)
        return JSONResponse(status_code=502, content={"status": "error", "message": str(exc)})
    return {"status": "success", "kind": kind, "results": results}


# ───────────────────────────── shutdown (roadmap v10, S1) ─────────────────────────────

#: How long the reply is given to reach the caller before the process goes. The
#: response is already handed to the transport when the background task runs, so
#: this only covers the flush.
SHUTDOWN_GRACE_SECONDS = 0.4


def _is_loopback(host: str) -> bool:
    """Did this request come from this machine?

    `/api/studio/shutdown` is the one route that can end the process, so it is
    restricted to the loopback interface — the Studio binds 127.0.0.1 today, but
    a future `--host 0.0.0.0` (BuzzEdit and MidnightBuzz both do it) must not
    silently turn "quit" into something the network can call. Hostnames are not
    trusted: only an address that parses and is loopback passes.
    """
    host = (host or "").strip()
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _shutdown_process() -> None:
    """Bring the Studio down the way closing its window does.

    Destroying the pywebview window runs `on_closing` (geometry saved, the Vite
    dev server stopped), returns from `webview.start()`, and lets `main()` fall
    off the end — which is what runs the `atexit` hook that removes
    `studio.runtime.json`. Reusing that path rather than calling `os._exit`
    means "shut down from Dexter" and "click the X" leave the machine in exactly
    the same state.

    When there is no window — the backend started headless by `uvicorn` — there
    is nothing to close, so the runtime record is cleared directly and the
    process ends. Factored out on its own so tests can exercise the route
    without taking the interpreter with them.
    """
    windows = []
    try:
        import webview

        windows = [w for w in (getattr(webview, "windows", None) or [])]
    except Exception:
        logger.debug("shutdown: no pywebview to ask for windows", exc_info=True)

    if windows:
        for window in windows:
            try:
                window.destroy()
            except Exception:
                logger.warning("shutdown: could not destroy a window", exc_info=True)
        return

    try:
        from desktop_app import _clear_runtime

        _clear_runtime()
    except Exception:
        logger.warning("shutdown: could not clear the runtime record", exc_info=True)
    os._exit(0)


def _deferred_shutdown() -> None:
    """Let the `{"ok": true}` reach the caller, then go."""
    if SHUTDOWN_GRACE_SECONDS > 0:
        time.sleep(SHUTDOWN_GRACE_SECONDS)
    # Looked up on the module rather than captured, so a test can replace it.
    _shutdown_process()


@router.post("/shutdown")
def studio_shutdown(request: Request, background: BackgroundTasks):
    """Close the Studio. Dexter calls this instead of killing the process tree,
    so the runtime record is removed and the window's own cleanup runs."""
    host = request.client.host if request.client else ""
    if not _is_loopback(host):
        logger.warning("Refused a shutdown from %s", host or "an unknown address")
        return JSONResponse(
            status_code=403,
            content={"ok": False, "error": "shutdown is only accepted from this machine"},
        )
    logger.info("Shutdown requested by %s; closing the Studio.", host)
    background.add_task(_deferred_shutdown)
    return {"ok": True, "message": "Buzzcaf Studio is shutting down."}


@router.get("/events")
async def studio_events():
    queue = bus.subscribe()
    return StreamingResponse(
        bus.stream(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
