"""
The BuzzcafAI -> BuzzEdit video-production bridge (roadmap: BuzzEdit bridge).

BuzzcafAI's agents write a script and a structured per-scene `visual_plan.json`
(the "Visual Plan" workflow step, `runtime/workflow.py`); this router turns
those into a BuzzEdit-ready directive-annotated script and drives BuzzEdit's
own HTTP API end-to-end -- import the recording, transcribe it, set the
annotated script, enqueue a presentation-pass render, and poll it to done.

    POST /api/projects/{id}/produce_video {recording_path, settings_override?, mode?}
        Entry A (BuzzcafAI drives). Runs on a background thread -- there is no
        job queue in this repo, so progress lives in the module-level
        `_produce_status` dict and on the SSE bus (`video_progress` /
        `video_ready` / `video_failed`), the same idiom `active_executions`
        and `event_bus` already use for workflow steps.
    GET  /api/projects/{id}/produce_video/status
        Poll the run above.
    POST /api/produce/plan {brand, script_text?, transcript?}
        Entry B (BuzzEdit drives): a synchronous reverse endpoint BuzzEdit's
        own backend calls after it transcribes a recording, to get back an
        annotated script + settings + the raw visual plan.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.events import bus as event_bus
from core.models.project import Project
from integrations.buzzedit_client import BuzzEditClient, BuzzEditUnavailable
from integrations.buzzedit_script import to_directive_script
from integrations.buzzedit_settings import settings_for_brand

logger = logging.getLogger("buzzcaf_ai.produce_api")

router = APIRouter(tags=["Produce"])

# No job queue in this repo (see runtime/workflow.py's engine): a project's
# produce_video state lives here, keyed by BuzzcafAI project id, guarded by a
# lock since the background thread and the status-poll route both touch it.
_produce_status: Dict[str, Dict[str, Any]] = {}
_produce_lock = threading.Lock()

#: How often the poll loop checks BuzzEdit's job list.
_POLL_INTERVAL_SECONDS = 4.0
#: How often (in elapsed seconds) a `video_progress` SSE event is actually
#: published during the poll loop, so a multi-hour render does not flood the
#: event bus with one message every 4 seconds.
_PROGRESS_EVENT_EVERY_SECONDS = 30.0
#: A render is a one-GPU, minutes-per-clip job (source plan: "one 16GB GPU,
#: overnight pass"); this is a backstop against a silently wedged BuzzEdit job,
#: not an expected ceiling.
_MAX_RENDER_SECONDS = 3 * 60 * 60


def _set_status(project_id: str, **fields: Any) -> None:
    with _produce_lock:
        current = dict(_produce_status.get(project_id) or {})
        current.update(fields)
        _produce_status[project_id] = current


def _get_status(project_id: str) -> Dict[str, Any]:
    with _produce_lock:
        return dict(_produce_status.get(project_id) or {"state": "idle"})


def _has_script_first_assets(project: Project) -> bool:
    return bool(project.assets.get("script")) and bool(project.assets.get("visual_plan"))


def _read_project_text_asset(project: Project, asset_names: list) -> Optional[str]:
    """The text of the first asset in `asset_names` that the project actually
    has on disk (e.g. prefer `script/final.md` over `script/draft.md`)."""
    for name in asset_names:
        rel_path = project.assets.get(name)
        if not rel_path:
            continue
        full_path = os.path.join(project.get_project_dir(), rel_path)
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
    return None


class ProduceVideoSchema(BaseModel):
    recording_path: str
    settings_override: Optional[Dict[str, Any]] = None
    mode: Optional[str] = None  # "script_first" | "record_first" | None (auto)


@router.post("/api/projects/{project_id}/produce_video")
def produce_video(project_id: str, payload: ProduceVideoSchema):
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.main import active_executions

    if project_id in active_executions or _get_status(project_id).get("state") in ("starting", "running"):
        raise HTTPException(status_code=409, detail="This project already has work running.")

    mode = payload.mode or ("script_first" if _has_script_first_assets(project) else "record_first")

    _set_status(project_id, state="starting", message="Queued...", progress=0.0, error=None)
    active_executions.add(project_id)
    thread = threading.Thread(
        target=_run_produce_video,
        name=f"produce-video-{project_id}",
        args=(project_id, payload.recording_path, payload.settings_override, mode),
        daemon=True,
    )
    thread.start()
    return {"status": "started", "project_id": project_id, "mode": mode}


@router.get("/api/projects/{project_id}/produce_video/status")
def produce_video_status(project_id: str):
    return _get_status(project_id)


def _run_produce_video(
    project_id: str,
    recording_path: str,
    settings_override: Optional[Dict[str, Any]],
    mode: str,
) -> None:
    """The whole produce_video pipeline. Runs on a background daemon thread --
    must never let an exception escape uncaught, or the thread just dies
    silently with the status dict stuck on "running"."""
    from app.main import active_executions

    try:
        _produce_video_steps(project_id, recording_path, settings_override, mode)
    except BuzzEditUnavailable as exc:
        logger.warning("produce_video(%s): BuzzEdit unavailable: %s", project_id, exc)
        _set_status(project_id, state="failed", error=str(exc))
        event_bus.publish("video_failed", {"project_id": project_id, "error": str(exc)})
    except Exception as exc:  # noqa: BLE001 - a background thread must not die silently
        logger.exception("produce_video(%s) failed", project_id)
        _set_status(project_id, state="failed", error=str(exc))
        event_bus.publish("video_failed", {"project_id": project_id, "error": str(exc)})
    finally:
        active_executions.discard(project_id)


def _produce_video_steps(
    project_id: str,
    recording_path: str,
    settings_override: Optional[Dict[str, Any]],
    mode: str,
) -> None:
    project = Project.load(project_id)
    client = BuzzEditClient()

    # 1. Sentinel -- advisory only. BuzzEdit runs its own ComfyUI/VRAM checks
    # once the render actually starts; this is purely a logged heads-up.
    try:
        from integrations.sentinel_client import client as sentinel_client

        granted, details = sentinel_client().query(mib=8192)  # ComfyUI ballpark, ECOSYSTEM.md
        if not granted:
            logger.warning("produce_video(%s): Sentinel flagged tight VRAM: %s", project_id, details)
    except Exception as exc:
        logger.debug("produce_video(%s): Sentinel query failed (%s); proceeding.", project_id, exc)

    # 2. BuzzEdit must be up, and ComfyUI must be online -- fail fast and
    # clearly rather than hang on a transcribe/enqueue call that will never
    # produce a usable render.
    _set_status(project_id, state="running", message="Checking BuzzEdit and ComfyUI...", progress=0.02)
    health = client.health()
    if health is None:
        raise BuzzEditUnavailable("BuzzEdit is not reachable. Start BuzzEdit before producing a video.")
    if not health.get("comfyui_connected"):
        raise BuzzEditUnavailable("ComfyUI is not reachable. Start ComfyUI in BuzzEdit before producing a video.")

    # 3. Import the recording.
    _set_status(project_id, message="Importing the recording into BuzzEdit...", progress=0.05)
    imported = client.import_recording(recording_path)
    buzzedit_project_id = imported.get("id")
    if not buzzedit_project_id:
        raise RuntimeError(f"BuzzEdit did not return a project id for the imported recording: {imported}")
    project.metadata["buzzedit_project_id"] = buzzedit_project_id
    project.save()
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "imported", "progress": 0.05})

    # 4. Transcribe (blocks on BuzzEdit's side until Whisper + auto-edit
    # planning finish).
    _set_status(project_id, message="Transcribing on BuzzEdit (Whisper)...", progress=0.15)
    client.transcribe(buzzedit_project_id)
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "transcribed", "progress": 0.25})

    # 5. Build the directive-annotated script.
    _set_status(project_id, message="Annotating the script with the visual plan...", progress=0.3)
    if mode == "script_first":
        script_text = _read_project_text_asset(project, ["script"])
        if script_text is None:
            raise RuntimeError("No script asset found for this project (script/draft.md or script/final.md).")
        visual_plan_text = _read_project_text_asset(project, ["visual_plan"])
        visual_plan = json.loads(visual_plan_text) if visual_plan_text else {"beats": []}
        annotated_text, skipped = to_directive_script(script_text, visual_plan)
    else:
        # record_first: no pre-written script -- take BuzzEdit's own
        # transcript, run the visual-plan agent on it directly, and annotate.
        script_resp = client.get_script(buzzedit_project_id)
        transcript_text = script_resp.get("text") or ""
        if not transcript_text.strip():
            raise RuntimeError("BuzzEdit returned no transcript text to plan visuals from.")

        from core.agent import AgentFactory
        from integrations.llm import LLMService, clean_json_response
        from runtime.workflow import VISUAL_PLAN_JSON_INSTRUCTION

        agent = AgentFactory.get_agent("PromptEngineer", LLMService())
        raw = agent.execute(transcript_text + "\n\n" + VISUAL_PLAN_JSON_INSTRUCTION, require_json=True)
        try:
            visual_plan = json.loads(clean_json_response(str(raw)))
        except Exception:
            logger.warning("produce_video(%s): visual-plan agent did not return usable JSON; no beats annotated.", project_id)
            visual_plan = {"beats": []}
        annotated_text, skipped = to_directive_script(transcript_text, visual_plan)

        # Persisted for inspectability, same as the script_first path already has.
        prod_dir = os.path.join(project.get_project_dir(), "production")
        os.makedirs(prod_dir, exist_ok=True)
        with open(os.path.join(prod_dir, "visual_plan.json"), "w", encoding="utf-8") as f:
            json.dump(visual_plan, f, indent=2, ensure_ascii=False)
        project.assets["visual_plan"] = "production/visual_plan.json"

    if skipped:
        logger.warning("produce_video(%s): %d visual-plan beat(s) could not be placed: %s",
                        project_id, len(skipped), [b.get("kind") for b in skipped])

    script_dir = os.path.join(project.get_project_dir(), "script")
    os.makedirs(script_dir, exist_ok=True)
    annotated_path = os.path.join(script_dir, "buzzedit_script.md")
    with open(annotated_path, "w", encoding="utf-8") as f:
        f.write(annotated_text)
    project.assets["buzzedit_script"] = "script/buzzedit_script.md"
    project.save()

    # 6. Push the annotated script onto the BuzzEdit project (aligns to the
    # transcript now that step 4 has run).
    _set_status(project_id, message="Sending the annotated script to BuzzEdit...", progress=0.35)
    client.set_script(buzzedit_project_id, annotated_text)

    # 7. Enqueue the presentation-pass render.
    settings = settings_for_brand(project.brand, settings_override)
    _set_status(project_id, message=f"Enqueuing the render (genre={settings.get('genre')})...", progress=0.4)
    enqueue_resp = client.enqueue_presentation(buzzedit_project_id, settings, start_at="")
    job = enqueue_resp.get("job") or {}
    job_id = job.get("id")
    if not job_id:
        raise RuntimeError(f"BuzzEdit did not return a job id for the enqueued render: {enqueue_resp}")
    event_bus.publish("video_progress", {"project_id": project_id, "stage": "enqueued", "progress": 0.4, "buzzedit_job_id": job_id})

    # 8. Poll BuzzEdit's scheduler until the job finishes or fails.
    deadline = time.monotonic() + _MAX_RENDER_SECONDS
    last_event_at = 0.0
    started_at = time.monotonic()
    final_job: Optional[Dict[str, Any]] = None
    while True:
        if time.monotonic() > deadline:
            raise RuntimeError(f"Timed out waiting for BuzzEdit render job {job_id} after {_MAX_RENDER_SECONDS}s.")
        jobs_resp = client.get_jobs()
        matching = next((j for j in (jobs_resp.get("jobs") or []) if j.get("id") == job_id), None)
        if matching is None:
            # The job may have already rolled off an in-memory list; treat as
            # still running and keep polling until the deadline.
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        status = matching.get("status")
        job_progress = matching.get("progress")
        overall_progress = 0.4 + 0.55 * float(job_progress or 0.0)
        _set_status(
            project_id,
            message=matching.get("message") or f"Rendering ({status})...",
            progress=min(overall_progress, 0.95),
            buzzedit_job_id=job_id,
        )
        elapsed = time.monotonic() - started_at
        if elapsed - last_event_at >= _PROGRESS_EVENT_EVERY_SECONDS:
            last_event_at = elapsed
            event_bus.publish("video_progress", {
                "project_id": project_id, "stage": "rendering", "progress": min(overall_progress, 0.95),
                "buzzedit_job_id": job_id, "buzzedit_status": status,
            })
        if status == "completed":
            final_job = matching
            break
        if status == "failed":
            raise RuntimeError(f"BuzzEdit render job {job_id} failed: {matching.get('error') or 'no error detail given'}")
        time.sleep(_POLL_INTERVAL_SECONDS)

    # 9. Fetch the report and record where the finished video landed.
    _set_status(project_id, message="Fetching the render report...", progress=0.97)
    report = client.get_report(buzzedit_project_id)
    output_path = None
    if report:
        output_path = report.get("output_path")
    if not output_path:
        buzzedit_project = client.get_project(buzzedit_project_id)
        output_path = (buzzedit_project or {}).get("output_path")

    project = Project.load(project_id)  # reload: the annotator step already saved once
    project.metadata["buzzedit_report"] = report
    project.metadata["output_path"] = output_path
    project.save()

    _set_status(project_id, state="ready", message="Video ready.", progress=1.0, report=report, output_path=output_path)
    event_bus.publish("video_ready", {
        "project_id": project_id, "output_path": output_path,
        "report_summary": {
            "genre": (report or {}).get("genre"),
            "assets_generated": (report or {}).get("assets_generated"),
            "script_directives": (report or {}).get("script_directives"),
        } if report else None,
    })


# ─────────────────────────── Entry B: BuzzEdit drives ───────────────────────────


class ProducePlanSchema(BaseModel):
    brand: str
    script_text: Optional[str] = None
    transcript: Optional[str] = None


@router.post("/api/produce/plan")
def produce_plan(payload: ProducePlanSchema):
    """A synchronous plan request from BuzzEdit (or anyone else): given a
    script or a transcript and a brand, return the directive-annotated
    script, the derived BuzzEdit settings, and the raw visual plan."""
    text = (payload.script_text or payload.transcript or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="script_text or transcript is required.")

    from core.agent import AgentFactory
    from integrations.llm import LLMService, clean_json_response
    from runtime.workflow import VISUAL_PLAN_JSON_INSTRUCTION

    agent = AgentFactory.get_agent("PromptEngineer", LLMService())
    raw = agent.execute(text + "\n\n" + VISUAL_PLAN_JSON_INSTRUCTION, require_json=True)
    try:
        visual_plan = json.loads(clean_json_response(str(raw)))
    except Exception:
        raise HTTPException(status_code=502, detail="The model did not return a usable visual plan.")

    annotated_text, skipped = to_directive_script(text, visual_plan)
    settings = settings_for_brand(payload.brand)
    return {
        "annotated_script": annotated_text,
        "settings": settings,
        "visual_plan": visual_plan,
        "skipped_beats": skipped,
    }
