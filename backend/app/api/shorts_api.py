"""Shorts Desk API (app/services/shorts_desk.py).

GET  /api/shorts/formats            channels -> formats -> filters
POST /api/shorts/find               {channel, format, filters, count} -> job
POST /api/shorts/build              {channel, format, candidate} -> job (result: project)
GET  /api/shorts/jobs/{job_id}      job progress / result
GET  /api/shorts/finds              recent find results
GET  /api/shorts/daily              daily-batch settings + last run
POST /api/shorts/daily              update daily-batch settings
POST /api/shorts/daily/run          run the daily batch now -> job
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import shorts_desk

router = APIRouter(prefix="/api/shorts", tags=["shorts"])


class FindSchema(BaseModel):
    channel: str
    format: str
    filters: Dict[str, str] = {}
    count: int = 6


class BuildSchema(BaseModel):
    channel: str
    format: str
    candidate: Dict[str, Any]


class DailySchema(BaseModel):
    enabled: Optional[bool] = None
    time: Optional[str] = None
    per_channel: Optional[int] = None
    min_score: Optional[int] = None


def _check(channel: str, fmt: str) -> None:
    if fmt not in shorts_desk.FORMATS.get(channel, {}):
        raise HTTPException(status_code=400, detail=f"Unknown format {channel}/{fmt}")


@router.get("/formats")
def formats():
    return shorts_desk.formats()


@router.post("/find")
def find(payload: FindSchema):
    _check(payload.channel, payload.format)
    count = max(1, min(12, payload.count))
    return shorts_desk.start_job("find", shorts_desk.find, payload.channel, payload.format, payload.filters, count)


@router.post("/build")
def build(payload: BuildSchema):
    _check(payload.channel, payload.format)
    return shorts_desk.start_job("build", shorts_desk.build, payload.channel, payload.format, payload.candidate)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = shorts_desk.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown job")
    return found


@router.get("/finds")
def finds():
    return shorts_desk.recent_finds()


@router.get("/daily")
def daily():
    return {**shorts_desk.daily_settings(), "last": shorts_desk._read("daily.json", {})}


@router.post("/daily")
def set_daily(payload: DailySchema):
    from integrations.llm import load_config, save_config
    cfg = load_config()
    data = payload.model_dump(exclude_unset=True)
    if "time" in data and data["time"] is not None:
        parts = str(data["time"]).split(":")
        if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]) or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise HTTPException(status_code=400, detail="time must be HH:MM")
    for key, value in data.items():
        if value is not None:
            cfg[f"shorts_daily_{key}"] = value
    save_config(cfg)
    return shorts_desk.daily_settings()


@router.post("/daily/run")
def run_daily():
    return shorts_desk.start_job("daily", shorts_desk.run_daily)


# --- nightly run (wake the PC, run the batch, hibernate) ----------------------------

class NightlySchema(BaseModel):
    enabled: Optional[bool] = None
    time: Optional[str] = None
    hibernate: Optional[bool] = None
    idle_minutes: Optional[int] = None


def _nightly_state() -> Dict[str, Any]:
    """The Shorts scheduler's own settings; the long-form scheduler has its own
    (api/longform_api.py)."""
    import json
    import os
    from core.paths import KNOWLEDGE_DIR
    from integrations import nightly_task
    from integrations.llm import load_config
    cfg = load_config()
    last = {}
    try:
        with open(os.path.join(KNOWLEDGE_DIR, "nightly", "last_run.json"), encoding="utf-8") as f:
            last = json.load(f)
    except Exception:
        pass
    return {
        "enabled": bool(cfg.get("nightly_enabled", False)),
        "time": str(cfg.get("nightly_time", "03:00")),
        "hibernate": bool(cfg.get("nightly_hibernate", True)),
        "idle_minutes": int(cfg.get("nightly_idle_minutes", 10)),
        "task": nightly_task.status("shorts"),
        "last_run": last,
    }


@router.get("/nightly")
def nightly():
    return _nightly_state()


@router.post("/nightly")
def set_nightly(payload: NightlySchema):
    from integrations import nightly_task
    from integrations.llm import load_config, save_config
    data = payload.model_dump(exclude_unset=True)
    if data.get("time") is not None:
        parts = str(data["time"]).split(":")
        if len(parts) < 2 or not all(p.isdigit() for p in parts[:2]) or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
            raise HTTPException(status_code=400, detail="time must be HH:MM")
        data["time"] = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    cfg = load_config()
    for key, value in data.items():
        if value is not None:
            cfg[f"nightly_{key}"] = value
    save_config(cfg)
    try:
        if cfg.get("nightly_enabled"):
            nightly_task.register(str(cfg.get("nightly_time", "03:00")), "shorts")
        else:
            nightly_task.unregister("shorts")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not update the Windows task: {exc}")
    return _nightly_state()


@router.post("/nightly/run")
def nightly_run_now():
    """Start the nightly task now (it will not hibernate while you are at the PC)."""
    from integrations import nightly_task
    if not nightly_task.run_now("shorts"):
        raise HTTPException(status_code=400, detail="The nightly task is not registered -- enable it first.")
    return {"started": True}
