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
    POST /api/projects/{id}/eye_contact/analyse    measure the take (no render): where the
                                                   prompter is, how far the eyes will move
    POST /api/projects/{id}/eye_contact/preview    before/after clips of three moments
    GET  /api/projects/{id}/eye_contact/preview    their state and files
    GET  /api/eye_contact/file?path=               stream one of those files to the browser

Mode "auto" (the default since 2026-10-20) measures the target from the
speaker's own looks into the lens -- where each iris sits then, sideways and
up/down -- and moves every reading frame there. The prompter geometry
(side, angle, aim, pitch) is the "manual" mode, and the fallback for a take
with no such looks.

Eye gaze v2 (BuzzEdit, 2026-10-24): auto mode now measures the lens from head + eye
gaze, and `aim_deg` / `pitch_deg` add on top of that measurement while `angle_deg > 0`
overrides its sideways size. Before v2 those three were dead in auto mode, and the
nudges saved then (and the old -10 / 15 defaults) compensated a measurement that
under-read by about 3x; sent now they would overshoot. So in auto mode they are
dropped unless the project's setup carries `nudges_v2: true`, which a save of any of
them sets (clearing the other pre-v2 ones), and `lens_marks` (seconds where the
speaker looks into the lens) are forwarded so BuzzEdit measures the lens there.
Manual mode sends everything as before.

The setup is stored in `project.metadata["eye_contact"]`, not with the video
style settings: those are forwarded to BuzzEdit's render, which has no use for
prompter geometry.
"""
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from core.models.project import Project
from integrations.buzzedit_client import BuzzEditClient, BuzzEditUnavailable

logger = logging.getLogger("buzzcaf_ai.eye_contact")
router = APIRouter()

# The fields BuzzEdit's EyeContactSetup accepts (same names and ranges).
SETUP_FIELDS = ("mode", "prompter_side", "angle_deg", "prompter_cm", "camera_cm", "steadiness", "aim_deg",
                "pitch_deg", "quality", "lens_marks")
# In auto mode these are nudges on top of BuzzEdit's measurement (v2); see the docstring.
NUDGE_FIELDS = ("aim_deg", "angle_deg", "pitch_deg")
# Studio defaults on top of BuzzEdit's saved setup, until a project sets its own.
# Since eye gaze v2 (2026-10-24) only the mode: the old aim -10 / angle 15 made up
# for an auto measurement that under-read, and would now overshoot it.
STUDIO_DEFAULTS: Dict[str, Any] = {"mode": "auto"}
#: The preview: this many moments of the take, each this long, spread over the take and
#: never its first/last seconds (an intro to camera or a sign-off would show no change).
PREVIEW_MOMENTS = 3
PREVIEW_SECONDS = 6.0
PREVIEW_FRACTIONS = (0.15, 0.5, 0.85)
#: What each preview clip keeps of BuzzEdit's report (the analysis keeps the whole report).
PREVIEW_REPORT_FIELDS = ("corrected_pct", "median_shift_px", "auto_measured", "measured_shift_deg", "eyes_raised_deg",
                         "lens_source", "camera_look_candidates", "side_check", "median_shift_px_per_eye",
                         "contact_sheet")
POLL_S = 2.0
# Generous: a 30-minute 4K take at "max" quality is a long GPU job.
MAX_WAIT_S = 3 * 3600
# How long BuzzEdit may go without answering a status poll before the job is
# given up on. Its event loop stalls for ~20 s while the corrected file is
# finalised, and one 15 s read timeout used to abandon a job that finished
# seconds later -- the video was then produced from the uncorrected original.
STATUS_GRACE_S = 300.0

_runs: Dict[str, Dict[str, Any]] = {}   # project_id -> live state of an on-demand run
_analyses: Dict[str, Dict[str, Any]] = {}   # project_id -> live state of an analysis
_previews: Dict[str, Dict[str, Any]] = {}   # project_id -> live state of a preview
_lock = threading.Lock()


class EyeContactSchema(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = Field(None, pattern="^(auto|manual)$")
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
    # Seconds where the speaker looks into the lens; BuzzEdit measures the lens there.
    lens_marks: Optional[List[float]] = Field(None, max_length=50)

    @field_validator("lens_marks")
    @classmethod
    def _marks_non_negative(cls, v: Optional[List[float]]) -> Optional[List[float]]:
        if v is not None and any(t < 0 for t in v):
            raise ValueError("lens_marks must be >= 0 seconds")
        return v


def project_setup(project: Project) -> Dict[str, Any]:
    """`{enabled, ...overrides}` saved on the project (overrides may be partial:
    anything left out comes from BuzzEdit's own saved prompter setup)."""
    return dict(project.metadata.get("eye_contact") or {})


def _overrides(setup: Dict[str, Any]) -> Dict[str, Any]:
    """What is sent to BuzzEdit: the Studio defaults, then this project's own values.
    In auto mode the nudges saved before eye gaze v2 are dropped (see the docstring)."""
    out = {**STUDIO_DEFAULTS, **{k: setup[k] for k in SETUP_FIELDS if setup.get(k) is not None}}
    if out.get("mode", "auto") == "auto" and not setup.get("nudges_v2"):
        for k in NUDGE_FIELDS:
            out.pop(k, None)
    return out


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
    applied to this BuzzEdit project by eye gaze v2 (its report has
    `lens_source`), so a resumed production does not redo a long GPU job; a
    pre-v2 result is redone once. Raises on failure; the caller decides whether
    that stops it.
    """
    project = Project.load(project_id)
    setup = project_setup(project)
    overrides = _overrides(setup)
    applied = project.metadata.get("eye_contact_applied") or {}
    if (not force and applied.get("buzzedit_project_id") == buzzedit_project_id
            and applied.get("setup") == overrides and (applied.get("report") or {}).get("lens_source")):
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


def _wait_job(client: BuzzEditClient, job_id: str, progress: Optional[Callable[[str, float], None]] = None,
              max_wait_s: float = MAX_WAIT_S) -> Dict[str, Any]:
    """Follow one BuzzEdit eye-contact job (analyse, preview or run) to its end."""
    deadline = time.monotonic() + max_wait_s
    last_answer, job = time.monotonic(), {}
    while True:
        try:
            job = client.eye_contact_status(job_id)
        except BuzzEditUnavailable as exc:
            if time.monotonic() - last_answer > STATUS_GRACE_S:
                raise RuntimeError(f"BuzzEdit stopped answering during eye contact work: {exc}")
            if progress:
                progress("BuzzEdit is busy, waiting", float(job.get("progress") or 0.0))
            time.sleep(POLL_S)
            continue
        last_answer = time.monotonic()
        if progress:
            progress(job.get("stage") or job.get("status") or "", float(job.get("progress") or 0.0))
        if job.get("status") == "completed":
            return job
        if job.get("status") in ("failed", "cancelled"):
            raise RuntimeError(f"Eye contact job {job.get('status')}: {job.get('error') or job.get('stage')}")
        if time.monotonic() > deadline:
            raise RuntimeError("The eye contact job did not finish in time.")
        time.sleep(POLL_S)


def analyse_recording(project_id: str, client: BuzzEditClient, buzzedit_project_id: str,
                      progress: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """Measure the take on BuzzEdit (tracks it once; cached there) and keep the numbers
    on the project (`eye_contact_analysis`)."""
    project = Project.load(project_id)
    overrides = _overrides(project_setup(project))
    entry = _source_media(client, buzzedit_project_id)
    job_id = client.start_eye_contact_analyse(buzzedit_project_id, entry["id"], overrides)
    job = _wait_job(client, job_id, progress)
    result = {"buzzedit_project_id": buzzedit_project_id, "media_id": entry["id"], "setup": overrides,
              "report": job.get("result") or {}, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    project = Project.load(project_id)
    project.metadata["eye_contact_analysis"] = result
    project.save()
    return result


def _preview_file_url(path: str) -> str:
    from urllib.parse import quote
    return f"/api/eye_contact/file?path={quote(path, safe='')}"


def preview_recording(project_id: str, client: BuzzEditClient, buzzedit_project_id: str,
                      progress: Optional[Callable[[str, float], None]] = None) -> List[Dict[str, Any]]:
    """Before/after clips of PREVIEW_MOMENTS moments of the take, corrected with the
    project's setup. In auto mode the take is analysed first when it has not been
    (the measurement needs the whole recording; a 6 s clip holds no look into the lens)."""
    project = Project.load(project_id)
    overrides = _overrides(project_setup(project))
    analysis = project.metadata.get("eye_contact_analysis") or {}
    if (overrides.get("mode", "auto") == "auto"
            and (analysis.get("buzzedit_project_id") != buzzedit_project_id or analysis.get("setup") != overrides)):
        if progress:
            progress("Measuring your looks into the lens over the whole take", 0.0)
        analysis = analyse_recording(project_id, client, buzzedit_project_id,
                                     lambda stage, f: progress(f"Measuring: {stage}", 0.3 * f) if progress else None)
    report = analysis.get("report") or {}
    duration = float(report.get("duration_s") or 0.0)
    if duration <= 0:
        duration = _recording_duration(project)
    entry = _source_media(client, buzzedit_project_id)
    clips: List[Dict[str, Any]] = []
    for i, frac in enumerate(PREVIEW_FRACTIONS[:PREVIEW_MOMENTS]):
        start = max(0.0, min(duration * frac, max(duration - PREVIEW_SECONDS, 0.0))) if duration > 0 else 30.0 * (i + 1)
        if progress:
            progress(f"Preview {i + 1} of {PREVIEW_MOMENTS}: {int(start // 60)}:{int(start % 60):02d}",
                     0.3 + 0.7 * i / PREVIEW_MOMENTS)
        job_id = client.start_eye_contact_preview(buzzedit_project_id, entry["id"], overrides, start, PREVIEW_SECONDS)
        job = _wait_job(client, job_id,
                        (lambda stage, f, i=i: progress(f"Preview {i + 1} of {PREVIEW_MOMENTS}: {stage}",
                                                        0.3 + 0.7 * (i + f) / PREVIEW_MOMENTS)) if progress else None,
                        max_wait_s=1800)
        res = job.get("result") or {}
        clips.append({"start_s": round(start, 1), "duration_s": PREVIEW_SECONDS,
                      "before_path": res.get("before_path"), "after_path": res.get("after_path"),
                      "before_url": _preview_file_url(res.get("before_path") or ""),
                      "after_url": _preview_file_url(res.get("after_path") or ""),
                      "contact_sheet_url": _preview_file_url(res["contact_sheet"]) if res.get("contact_sheet") else None,
                      "report": {k: res.get(k) for k in PREVIEW_REPORT_FIELDS}})
    project = Project.load(project_id)
    project.metadata["eye_contact_preview"] = {"setup": overrides, "clips": clips,
                                               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    project.save()
    return clips


def _recording_duration(project: Project) -> float:
    """Seconds of the project's recording, from ffprobe, or 0."""
    import json
    path = str(project.metadata.get("recording_path") or "")
    if not path or not os.path.isfile(path):
        return 0.0
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", path],
                             capture_output=True, text=True, timeout=30, check=True, creationflags=_NO_WINDOW).stdout
        return float((json.loads(out).get("format") or {}).get("duration") or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _preview_dir_ok(path: str) -> bool:
    """Only BuzzEdit's eye-contact preview cache is served, never any other file: the
    clips and their contact sheets (`<clip>_eyes.jpg`, next to them)."""
    norm = os.path.normcase(os.path.abspath(path))
    parts = norm.replace("/", os.sep).split(os.sep)
    return (norm.endswith((".mp4", "_eyes.jpg")) and os.path.isfile(norm)
            and any(parts[i:i + 3] == ["cache", "eyecontact", "preview"] for i in range(len(parts) - 2)))


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
    with _lock:
        analysing = dict(_analyses.get(project_id) or {})
        previewing = dict(_previews.get(project_id) or {})
    return {"setup": project_setup(project), "applied": project.metadata.get("eye_contact_applied"),
            "run": run or None, "analysis": project.metadata.get("eye_contact_analysis"),
            "analysing": analysing or None, "preview": project.metadata.get("eye_contact_preview"),
            "previewing": previewing or None}


@router.put("/api/projects/{project_id}/eye_contact")
def put_eye_contact(project_id: str, payload: EyeContactSchema):
    """Save this project's setup. A field sent as null falls back to BuzzEdit's saved value."""
    project = _load(project_id)
    setup = project_setup(project)
    sent = payload.model_dump(exclude_unset=True)
    if any(sent.get(k) is not None for k in NUDGE_FIELDS) and not setup.get("nudges_v2"):
        # The first nudge saved since v2: the pre-v2 ones it does not set go, or they
        # would come back to life with the marker.
        for k in NUDGE_FIELDS:
            setup.pop(k, None)
        setup["nudges_v2"] = True
    for key, value in sent.items():
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


def _background(project_id: str, table: Dict[str, Dict[str, Any]], name: str,
                work: Callable[[Callable[[str, float], None]], Any]) -> Dict[str, Any]:
    """Run `work` on a thread with live state in `table[project_id]`; one at a time."""
    with _lock:
        if (table.get(project_id) or {}).get("state") == "running":
            return dict(table[project_id])
        table[project_id] = {"state": "running", "stage": "Starting", "progress": 0.0, "error": None}

    def progress(stage: str, fraction: float) -> None:
        with _lock:
            table[project_id].update(stage=stage, progress=round(fraction, 3))

    def run() -> None:
        try:
            work(progress)
            with _lock:
                table[project_id].update(state="done", stage="Done", progress=1.0)
        except Exception as exc:  # noqa: BLE001 - reported to the panel
            logger.warning("Eye contact %s for %s failed: %s", name, project_id, exc)
            with _lock:
                table[project_id].update(state="failed", error=str(exc)[:400])

    threading.Thread(target=run, name=f"eye-{name}-{project_id[:24]}", daemon=True).start()
    with _lock:
        return dict(table[project_id])


def _buzzedit_project_or_400(project: Project) -> str:
    buzzedit_project_id = project.metadata.get("buzzedit_project_id")
    if not buzzedit_project_id:
        raise HTTPException(status_code=400,
                            detail="This project has no BuzzEdit recording yet. Start video production once "
                                   "(it imports the recording), or import it in BuzzEdit.")
    return buzzedit_project_id


@router.post("/api/projects/{project_id}/eye_contact/analyse")
def analyse_eye_contact(project_id: str):
    """Measure the take in BuzzEdit (no render): prompter offset, looks into the lens,
    how far the eyes will move. Runs in the background; GET .../eye_contact shows it."""
    project = _load(project_id)
    buzzedit_project_id = _buzzedit_project_or_400(project)

    def work(progress):
        from app.api.produce_api import ensure_buzzedit_running
        ensure_buzzedit_running()
        analyse_recording(project_id, BuzzEditClient(), buzzedit_project_id, progress)

    return _background(project_id, _analyses, "analyse", work)


@router.post("/api/projects/{project_id}/eye_contact/preview")
def preview_eye_contact(project_id: str):
    """Before/after clips of three moments of the take with the current setup, in the
    background; GET .../eye_contact/preview shows the state and the files."""
    project = _load(project_id)
    buzzedit_project_id = _buzzedit_project_or_400(project)

    def work(progress):
        from app.api.produce_api import ensure_buzzedit_running
        ensure_buzzedit_running()
        preview_recording(project_id, BuzzEditClient(), buzzedit_project_id, progress)

    return _background(project_id, _previews, "preview", work)


@router.get("/api/projects/{project_id}/eye_contact/preview")
def get_eye_contact_preview(project_id: str):
    project = _load(project_id)
    with _lock:
        state = dict(_previews.get(project_id) or {})
    return {"previewing": state or None, "preview": project.metadata.get("eye_contact_preview")}


@router.get("/api/eye_contact/file")
def eye_contact_file(path: str):
    """Stream a before/after preview clip (or its contact sheet) from BuzzEdit's preview
    cache to the browser."""
    if not _preview_dir_ok(path):
        raise HTTPException(status_code=404, detail="That preview file is not available.")
    media_type = "image/jpeg" if path.lower().endswith(".jpg") else "video/mp4"
    return FileResponse(os.path.abspath(path), media_type=media_type)


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
