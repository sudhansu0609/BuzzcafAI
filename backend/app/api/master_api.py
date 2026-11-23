"""The master pause / resume API (docs/STUDIO_DIRECTOR_PLAN.md Part 1).

GET  /api/master/state   -- {paused, since, reason, mode, held, ram_free_mb,
                             vram_free_mb, vram_total_mb, loaded_models, buzzedit}
POST /api/master/pause   {mode?: "soft"|"now", reason?: str}
POST /api/master/resume

The Dashboard's Pause/Resume control, Dexter, the tray icon, the nightly
Windows task and the research/long-script loops all read this. See
`app/services/master_control.py` for what pausing and resuming actually do.
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import master_control

router = APIRouter(prefix="/api/master", tags=["master"])


class PauseBody(BaseModel):
    mode: Optional[str] = "soft"
    reason: Optional[str] = ""
    #: Who asked -- the Dashboard, Dexter, the tray, a username. Recorded on
    #: the state for the Health row and the Dashboard, never enforced.
    by: Optional[str] = ""
    #: An optional ISO instant for the UI's reference only -- nothing resumes
    #: the pause but an explicit `POST /api/master/resume` (no auto-resume).
    resume_at: Optional[str] = None


@router.get("/state")
def get_state() -> Dict[str, Any]:
    data = master_control.state()
    data.update(master_control._memory_snapshot())
    try:
        from integrations.buzzedit_client import BuzzEditClient
        data["buzzedit"] = BuzzEditClient().master_state()
    except Exception:  # noqa: BLE001 - BuzzEdit down: the Studio's own state still answers
        data["buzzedit"] = None
    return data


@router.post("/pause")
def post_pause(body: PauseBody) -> Dict[str, Any]:
    return master_control.pause(mode=body.mode or "soft", reason=body.reason or "",
                                by=body.by or "", resume_at=body.resume_at)


@router.post("/resume")
def post_resume() -> Dict[str, Any]:
    return master_control.resume()
