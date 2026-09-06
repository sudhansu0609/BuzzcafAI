"""
The control surface Dexter drives (roadmap v5, 3.1).

    GET  /api/studio/state    one call that answers "what is going on in the Studio"
    POST /api/studio/chat     a Studio Assistant turn (same engine as /api/topics/agent_chat)
    GET  /api/studio/events   SSE: project_created, step_started, step_completed,
                              approval_needed, step_failed, buzzbrain_snapshot

The approve alias lives in app/main.py next to the execute route it wraps.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.services.events import bus
from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.studio_api")

router = APIRouter(prefix="/api/studio", tags=["Studio control"])


class StudioChatSchema(BaseModel):
    message: str
    channel: Optional[str] = None
    agent_name: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None
    context_topic: Optional[Dict[str, Any]] = None


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


@router.get("/events")
async def studio_events():
    queue = bus.subscribe()
    return StreamingResponse(
        bus.stream(queue),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
