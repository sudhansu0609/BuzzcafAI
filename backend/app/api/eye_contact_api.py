"""Teleprompter eye-contact correction, driven from the Studio, done by BuzzEdit.

BuzzEdit owns the work (`routes/eyecontact.py`): it renders a corrected copy of
the recording on the GPU and swaps it in everywhere the original was used,
keeping the original for a revert. The Studio keeps a per-project setup --
whether production should run it, and the prompter geometry -- and either runs
it as a production step (right after the recording is imported, so the
transcript, the cut and the render all use the corrected video) or on demand.

    GET  /api/eye_contact/defaults                 BuzzEdit's saved setup + whether it can run
    GET  /api/projects/{id}/eye_contact            this project's setup and last result
    PUT  /api/projects/{id}/eye_contact            save the setup (enabled, angle, side, ...)
    POST /api/projects/{id}/eye_contact/run        correct the BuzzEdit recording now
    POST /api/projects/{id}/eye_contact/revert     put the original recording back

The setup is stored in `project.metadata["eye_contact"]`, not with the video
style settings: those are forwarded to BuzzEdit's render, which has no use for
prompter geometry.
"""
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.models.project import Project
from integrations.buzzedit_client import BuzzEditClient, BuzzEditUnavailable

logger = logging.getLogger("buzzcaf_ai.eye_contact")
router = APIRouter()

# The fields BuzzEdit's EyeContactSetup accepts (same names and ranges).
SETUP_FIELDS = ("prompter_side", "angle_deg", "prompter_cm", "camera_cm", "steadiness", "aim_deg", "pitch_deg",
                "quality")
# Studio defaults on top of BuzzEdit's saved setup, until a project sets its own.
# aim_deg is in the viewer's terms: - moves the pupils toward the viewer's left,
# + toward the viewer's right (BuzzEdit's "+ = toward the speaker's left" is the
# same direction). -10 is the creator's current prompter rig.
# angle_deg is how far the prompter sits off the lens, i.e. how far the eyes
# swing: 15 since 2026-10-08 (the saved 10 under-corrected; the rig's own
# geometry, 30 cm beside a lens 110 cm away, is 15.3).
STUDIO_DEFAULTS: Dict[str, Any] = {"aim_deg": -10.0, "angle_deg": 15.0}
POLL_S = 2.0
# Generous: a 30-minute 4K take at "max" quality is a long GPU job.
MAX_WAIT_S = 3 * 3600
# How long BuzzEdit may go without answering a status poll before the job is
# given up on. Its event loop stalls for ~20 s while the corrected file is
# finalised, and one 15 s read timeout used to abandon a job that finished
# seconds later -- the video was then produced from the uncorrected original.
STATUS_GRACE_S = 300.0

_runs: Dict[str, Dict[str, Any]] = {}   # project_id -> live state of an on-demand run
_lock = threading.Lock()


class EyeContactSchema(BaseModel):
    enabled: Optional[bool] = None
    prompter_side: Optional[str] = Field(None, pattern="^(left|right|auto)$")
    angle_deg: Optional[float] = Field(None, ge=0.0, le=45.0)
    prompter_cm: Optional[float] = Field(None, ge=0.0, le=200.0)
    camera_cm: Optional[float] = Field(None, ge=20.0, le=1000.0)
    steadiness: Optional[float] = Field(None, ge=0.0, le=1.0)
    aim_deg: Optional[float] = Field(None, ge=-15.0, le=15.0)
    # Up/down re-aim in degrees: + = the pupils sit lower (looking down), - = higher. An
    # older BuzzEdit ignores it.
    pitch_deg: Optional[float] = Field(None, ge=-10.0, le=10.0)
    quality: Optional[str] = Field(None, pattern="^(standard|high|max)$")


def project_setup(project: Project) -> Dict[str, Any]:
    """`{enabled, ...overrides}` saved on the project (overrides may be partial:
    anything left out comes from BuzzEdit's own saved prompter setup)."""
    return dict(project.metadata.get("eye_contact") or {})


def _overrides(setup: Dict[str, Any]) -> Dict[str, Any]:
    """What is sent to BuzzEdit: the Studio defaults, then this project's own values."""
    return {**STUDIO_DEFAULTS, **{k: setup[k] for k in SETUP_FIELDS if setup.get(k) is not None}}


def _source_media(client: BuzzEditClient, buzzedit_project_id: str) -> Dict[str, Any]:
    """The BuzzEdit library entry of the imported recording."""
    data = client.get_project(buzzedit_project_id) or {}
    pool = [m for m in (data.get("media_pool") or []) if m.get("kind") == "video"]
    source = (data.get("source_video") or "").lower()
    entry = next((m for m in pool if (m.get("path") or "").lower() == source), None)
    # Already corrected: the entry now points at the corrected file and keeps
    # the original under eye_contact.original_path.
    entry = entry or next((m for m in pool if m.get("eye_contact")), None) or (pool[0] if pool else None)
    if not entry:
        raise RuntimeError("BuzzEdit has no video recording in this project to correct.")
    return entry


def correct_recording(project_id: str, client: BuzzEditClient, buzzedit_project_id: str,
                      progress: Optional[Callable[[str, float], None]] = None,
                      force: bool = False) -> Dict[str, Any]:
    """Run BuzzEdit's correction on the project's recording and wait for it.

    Skipped (returns the earlier result) when the same setup was already
    applied to this BuzzEdit project, so a resumed production does not redo a
    long GPU job. Raises on failure; the caller decides whether that stops it.
    """
    project = Project.load(project_id)
    setup = project_setup(project)
    overrides = _overrides(setup)
    applied = project.metadata.get("eye_contact_applied") or {}
    if (not force and applied.get("buzzedit_project_id") == buzzedit_project_id
            and applied.get("setup") == overrides):
        return applied

    try:
        available = client.eye_contact_available()
    except BuzzEditUnavailable:
        # BuzzEdit stopped since the last step (a pause, a crash): start it
        # in the background and carry on rather than failing the correction.
        from app.api.produce_api import ensure_buzzedit_running
        if progress:
            progress("Starting BuzzEdit in the background", 0.0)
        ensure_buzzedit_running(timeout=90.0)
        available = client.eye_contact_available()
    if not available.get("available"):
        raise RuntimeError(f"Eye contact correction is unavailable in BuzzEdit: {available.get('reason')}")
    entry = _source_media(client, buzzedit_project_id)
    job_id = client.start_eye_contact(buzzedit_project_id, entry["id"], overrides)
    deadline = time.monotonic() + MAX_WAIT_S
    last_answer, job = time.monotonic(), {}
    while True:
        try:
            job = client.eye_contact_status(job_id)
        except BuzzEditUnavailable as exc:
            if time.monotonic() - last_answer > STATUS_GRACE_S:
                raise RuntimeError(f"BuzzEdit stopped answering during eye contact correction: {exc}")
            logger.info("Eye contact job %s: no status answer yet (%s); still waiting.", job_id, exc)
            if progress:
                progress("BuzzEdit is busy, waiting", float(job.get("progress") or 0.0))
            time.sleep(POLL_S)
            continue
        last_answer = time.monotonic()
        if progress:
            progress(job.get("stage") or job.get("status") or "", float(job.get("progress") or 0.0))
        if job.get("status") == "completed":
            break
        if job.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"Eye contact correction {job.get('status')}: {job.get('error') or job.get('stage')}")
        if time.monotonic() > deadline:
            raise RuntimeError("Eye contact correction did not finish in time.")
        time.sleep(POLL_S)

    result = {"buzzedit_project_id": buzzedit_project_id, "media_id": entry["id"], "setup": overrides,
              "report": job.get("result"), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    project = Project.load(project_id)
    project.metadata["eye_contact_applied"] = result
    project.save()
    return result


# ------------------------------------------------------------------ routes


def _load(project_id: str) -> Project:
    try:
        return Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/api/eye_contact/defaults")
def eye_contact_defaults():
    """BuzzEdit's saved prompter setup, whether BuzzEdit is running, whether
    correction can run, and whether the Studio keeps BuzzEdit running."""
    from app.services import buzzedit_keepalive
    client = BuzzEditClient()
    keep_alive = buzzedit_keepalive.enabled()
    if client.health() is None:
        # Not an error: "Fix now" and production start BuzzEdit themselves.
        return {"setup": dict(STUDIO_DEFAULTS), "buzzedit_running": False, "available": None,
                "reason": "BuzzEdit is not running; it starts automatically when needed.",
                "keep_alive": keep_alive}
    try:
        return {"setup": {**client.eye_contact_settings(), **STUDIO_DEFAULTS}, "buzzedit_running": True,
                **client.eye_contact_available(), "keep_alive": keep_alive}
    except BuzzEditUnavailable as exc:
        return {"setup": dict(STUDIO_DEFAULTS), "buzzedit_running": False, "available": None,
                "reason": f"BuzzEdit did not answer ({exc})", "keep_alive": keep_alive}


class KeepAliveSchema(BaseModel):
    enabled: bool


@router.put("/api/produce/buzzedit/keep_alive")
def put_buzzedit_keep_alive(payload: KeepAliveSchema):
    """Keep BuzzEdit running in the background (started now, and again
    whenever it stops, while the Studio is open)."""
    from app.services import buzzedit_keepalive
    return {"keep_alive": buzzedit_keepalive.set_enabled(payload.enabled)}


@router.get("/api/projects/{project_id}/eye_contact")
def get_eye_contact(project_id: str):
    project = _load(project_id)
    with _lock:
        run = dict(_runs.get(project_id) or {})
    return {"setup": project_setup(project), "applied": project.metadata.get("eye_contact_applied"),
            "run": run or None}


@router.put("/api/projects/{project_id}/eye_contact")
def put_eye_contact(project_id: str, payload: EyeContactSchema):
    """Save this project's setup. A field sent as null falls back to BuzzEdit's saved value."""
    project = _load(project_id)
    setup = project_setup(project)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            setup.pop(key, None)
        else:
            setup[key] = value
    project.metadata["eye_contact"] = setup
    project.save()
    return {"setup": setup, "applied": project.metadata.get("eye_contact_applied")}


@router.post("/api/projects/{project_id}/eye_contact/run")
def run_eye_contact(project_id: str):
    """Correct this project's BuzzEdit recording now (in the background).
    The next render uses the corrected video; a finished video needs a re-render."""
    project = _load(project_id)
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise HTTPException(status_code=400,
                            detail="This project has no BuzzEdit recording yet. Turn on 'Fix eye contact' "
                                   "and start video production; it runs right after the import.")
    with _lock:
        if (_runs.get(project_id) or {}).get("state") == "running":
            return _runs[project_id]
        _runs[project_id] = {"state": "running", "stage": "Starting", "progress": 0.0, "error": None}

    def progress(stage: str, fraction: float) -> None:
        with _lock:
            _runs[project_id].update(stage=stage, progress=round(fraction, 3))

    def work() -> None:
        try:
            from app.api.produce_api import ensure_buzzedit_running
            ensure_buzzedit_running()
            correct_recording(project_id, BuzzEditClient(), buzzedit_project_id, progress, force=True)
            with _lock:
                _runs[project_id].update(state="done", stage="Done", progress=1.0)
        except Exception as exc:  # noqa: BLE001 - reported to the panel
            logger.warning("Eye contact for %s failed: %s", project_id, exc)
            with _lock:
                _runs[project_id].update(state="failed", error=str(exc)[:400])

    threading.Thread(target=work, name=f"eye-contact-{project_id[:24]}", daemon=True).start()
    with _lock:
        return dict(_runs[project_id])


@router.post("/api/projects/{project_id}/eye_contact/revert")
def revert_eye_contact(project_id: str):
    """Put the original recording back in BuzzEdit (the corrected file stays on disk)."""
    project = _load(project_id)
    applied = project.metadata.get("eye_contact_applied") or {}
    buzzedit_project_id = applied.get("buzzedit_project_id") or project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise HTTPException(status_code=400, detail="Nothing to revert: no BuzzEdit recording.")
    client = BuzzEditClient()
    try:
        media_id = applied.get("media_id") or _source_media(client, buzzedit_project_id)["id"]
        client.revert_eye_contact(buzzedit_project_id, media_id)
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"BuzzEdit is not running: {exc}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not revert: {exc}")
    project.metadata.pop("eye_contact_applied", None)
    project.save()
    return {"status": "reverted"}
