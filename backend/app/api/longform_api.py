"""Nightly long-form batch API (app/services/longform_nightly.py).

GET  /api/longform/nightly       settings, this scheduler's own wake time / hibernate settings, last run, live status of a run
POST /api/longform/nightly       update {enabled, time, hibernate, idle_minutes, channels, per_channel, minutes: {channel: n},
                                 instructions: {channel: text}}; enabled/time (re)register the long-form Windows task
POST /api/longform/nightly/run   run the batch now, in the background
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import longform_nightly

router = APIRouter(prefix="/api/longform", tags=["longform"])


class LongformSchema(BaseModel):
    enabled: Optional[bool] = None
    channels: Optional[List[str]] = None
    per_channel: Optional[int] = None
    minutes: Optional[Dict[str, float]] = None
    instructions: Optional[Dict[str, str]] = None
    time: Optional[str] = None
    hibernate: Optional[bool] = None
    idle_minutes: Optional[int] = None


def _schedule(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The long-form scheduler's own Windows task; it falls back to the shorts
    wake time until a time of its own is set."""
    import json
    import os
    from core.paths import KNOWLEDGE_DIR
    from integrations import nightly_task
    last = {}
    try:
        with open(os.path.join(KNOWLEDGE_DIR, "nightly", "last_run_longform.json"), encoding="utf-8") as f:
            last = json.load(f)
    except Exception:
        pass
    return {
        "time": str(cfg.get("longform_time") or cfg.get("nightly_time", "03:00")),
        "hibernate": bool(cfg.get("longform_hibernate", True)),
        "idle_minutes": int(cfg.get("longform_idle_minutes", 10)),
        "task": nightly_task.status("longform"),
        "last_run": last,
    }


def _state() -> Dict[str, Any]:
    from app.services.studio_chat import channel_guide
    from integrations.llm import load_config
    cfg = load_config()
    record = longform_nightly._read_record()
    return {
        **longform_nightly.settings(),
        "all_channels": list(longform_nightly.WORKFLOWS),
        "schedule": _schedule(cfg),
        "last": {k: record.get(k) for k in ("ran_at", "built", "skipped")},
        "history": record.get("history", [])[:10],
        "running": longform_nightly.running(),
        "status": longform_nightly.read_status(),
        "strategists": {ch: longform_nightly.strategist_for(ch) for ch in longform_nightly.WORKFLOWS},
        "guides": {ch: channel_guide(ch, full=True) for ch in longform_nightly.WORKFLOWS},
    }


@router.get("/nightly")
def get_nightly():
    return _state()


@router.post("/nightly")
def set_nightly(payload: LongformSchema):
    from integrations.llm import load_config, save_config
    data = payload.model_dump(exclude_unset=True)
    cfg = load_config()
    if data.get("time") is not None:
        parts = str(data["time"]).split(":")
        if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]) or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise HTTPException(status_code=400, detail="time must be HH:MM")
        cfg["longform_time"] = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    if data.get("hibernate") is not None:
        cfg["longform_hibernate"] = bool(data["hibernate"])
    if data.get("idle_minutes") is not None:
        cfg["longform_idle_minutes"] = max(1, min(120, int(data["idle_minutes"])))
    if data.get("enabled") is not None:
        cfg["longform_nightly_enabled"] = bool(data["enabled"])
    if data.get("channels") is not None:
        bad = [c for c in data["channels"] if c not in longform_nightly.WORKFLOWS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown channel(s): {', '.join(bad)}")
        cfg["longform_nightly_channels"] = data["channels"]
    if data.get("per_channel") is not None:
        cfg["longform_nightly_per_channel"] = max(1, min(5, int(data["per_channel"])))
    if data.get("minutes") is not None:
        bad = [c for c in data["minutes"] if c not in longform_nightly.WORKFLOWS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown channel(s): {', '.join(bad)}")
        merged = longform_nightly._minutes(cfg.get("longform_nightly_minutes"))
        merged.update({c: max(1.0, min(180.0, float(m))) for c, m in data["minutes"].items()})
        cfg["longform_nightly_minutes"] = merged
    if data.get("instructions") is not None:
        bad = [c for c in data["instructions"] if c not in longform_nightly.WORKFLOWS]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown channel(s): {', '.join(bad)}")
        merged = longform_nightly._instructions(cfg.get("longform_nightly_instructions"))
        merged.update({c: str(t)[:8000] for c, t in data["instructions"].items()})
        cfg["longform_nightly_instructions"] = merged
    save_config(cfg)
    if data.get("enabled") is not None or data.get("time") is not None:
        from integrations import nightly_task
        try:
            if cfg.get("longform_nightly_enabled", True):
                nightly_task.register(_schedule(cfg)["time"], "longform")
            else:
                nightly_task.unregister("longform")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not update the Windows task: {exc}")
    return _state()


@router.post("/continue/{project_id}")
def continue_project(project_id: str):
    """Run a long-form project's remaining planning steps (up to the first that needs the creator)."""
    longform_nightly.continue_preproduction(project_id)
    return {"started": True, "project_id": project_id}


@router.post("/nightly/run")
def run_now():
    try:
        longform_nightly.start_now()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _state()
