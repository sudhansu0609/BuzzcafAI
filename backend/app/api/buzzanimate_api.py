"""
Studio -> BuzzAnimate (step E5 of `BuzzAnimate/docs/ECOSYSTEM_BRIDGE_PLAN.md`).

* `GET  /api/buzzanimate/status[?start=true]` -- is BuzzAnimate up, where,
  what it has open.
* `POST /api/buzzanimate/call {tool, args, start?}` -- one BuzzAnimate tool
  call (`GET /api/catalog` on BuzzAnimate lists them).
* `POST /api/projects/{id}/animate {casting_path?, scenes?, render?,
  to_buzzedit?, start?}` -- a background run: the project's script asset goes
  to BuzzAnimate's `POST /api/episode` (BuzzAnimate turns a narration script
  into a narrator's screenplay itself) with `out_dir = <project>/animation`;
  with `render` each built scene's preview MP4 is waited for; the result is
  stored on the project as `metadata["animation_output"]` (as `produce_video`
  stores `output_path`); SSE `animation_progress` / `animation_ready` /
  `animation_failed`. `to_buzzedit` (implies `render`) hands the MP4s to
  BuzzEdit through `integrations.buzzedit_client`: the first becomes a new
  BuzzEdit project, the rest join its media.
* `GET  /api/projects/{id}/animate/status` -- the in-memory run status, else
  the stored `animation_output`.

BuzzAnimate not running is a 503 that says so; `start: true` launches its
`.vbs` and waits (bounded) for its health route.
"""

from __future__ import annotations

import logging
import re
import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.events import bus as event_bus
from core.models.project import Project
from integrations import buzzanimate_client as animate

logger = logging.getLogger("buzzcaf_ai.buzzanimate_api")


# **This machine only.** These routes reach BuzzAnimate, which can open, save
# and export files anywhere on disk, so a web page must not be able to call
# them — and this app's CORS policy is no protection here (BuzzEdit's is
# `allow_origins=["*"]`). A request from a backend (no `Origin`) or from a page
# served on this machine (`http://127.0.0.1:*`, `http://localhost:*`) is
# served; anything else, `null` included, is refused. `null` is what a
# sandboxed iframe on any website sends — and also what a `file://` page
# sends, so a front-end button for these routes must call them from the
# desktop shell's main process (no `Origin`), not from a `file://` page.
_LOCAL_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost)(:\d+)?$", re.IGNORECASE)


def _this_machine_only(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin.strip() and not _LOCAL_ORIGIN.match(origin.strip()):
        raise HTTPException(
            status_code=403,
            detail=f"refused: requests from {origin} may not drive BuzzAnimate; only this machine may",
        )


router = APIRouter(dependencies=[Depends(_this_machine_only)])

_animate_status: Dict[str, Dict[str, Any]] = {}
_animate_lock = threading.Lock()
_BUSY_STATES = ("starting", "running")


def _set_status(project_id: str, **fields: Any) -> None:
    with _animate_lock:
        current = dict(_animate_status.get(project_id) or {})
        current.update(fields)
        _animate_status[project_id] = current


def _get_status(project_id: str) -> Dict[str, Any]:
    with _animate_lock:
        return dict(_animate_status.get(project_id) or {"state": "idle"})


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, animate.BuzzAnimateUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, animate.BuzzAnimateError):
        return HTTPException(status_code=exc.status, detail=f"BuzzAnimate: {exc.message}")
    return HTTPException(status_code=502, detail=f"BuzzAnimate: {exc}")


def _ensure(start: bool, timeout: float) -> None:
    try:
        animate.ensure(start, timeout)
    except Exception as exc:
        raise _http_error(exc)


class BuzzAnimateCallSchema(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    start: bool = False
    start_timeout: float = Field(animate.START_TIMEOUT_SECONDS, gt=0)


class AnimateSchema(BaseModel):
    casting_path: Optional[str] = None
    scenes: Optional[List[int]] = None
    render: bool = False
    to_buzzedit: bool = False
    start: bool = False
    start_timeout: float = Field(animate.START_TIMEOUT_SECONDS, gt=0)


@router.get("/api/buzzanimate/status")
def buzzanimate_status(start: bool = False, start_timeout: float = animate.START_TIMEOUT_SECONDS):
    if start:
        _ensure(True, start_timeout)
    return animate.status()


@router.post("/api/buzzanimate/call")
def buzzanimate_call(payload: BuzzAnimateCallSchema):
    _ensure(payload.start, payload.start_timeout)
    try:
        return animate.call(payload.tool, payload.args)
    except Exception as exc:
        raise _http_error(exc)


def _script_path(project: Project) -> str:
    rel_path = project.assets.get("script")
    full = os.path.join(project.get_project_dir(), rel_path) if rel_path else None
    if not full or not os.path.isfile(full):
        raise HTTPException(status_code=400, detail="This project has no script yet; write one before animating it.")
    return full


@router.post("/api/projects/{project_id}/animate")
def animate_project(project_id: str, payload: AnimateSchema):
    try:
        project = Project.load(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    script = _script_path(project)
    if _get_status(project_id).get("state") in _BUSY_STATES:
        raise HTTPException(status_code=409, detail="This project is already being animated.")
    if payload.casting_path and not os.path.isfile(payload.casting_path):
        raise HTTPException(status_code=404, detail=f"No casting file at {payload.casting_path}")
    if not payload.start:
        _ensure(False, payload.start_timeout)

    out_dir = os.path.join(project.get_project_dir(), "animation")
    with _animate_lock:
        _animate_status[project_id] = {
            "state": "starting", "progress": 0.0, "error": None, "out_dir": out_dir,
            "message": "Starting BuzzAnimate..." if payload.start else "Sending the script to BuzzAnimate...",
        }
    threading.Thread(target=_run_animate, args=(project_id, script, out_dir, payload),
                     name=f"animate-{project_id}", daemon=True).start()
    return {"status": "starting", "project_id": project_id, "out_dir": out_dir}


@router.get("/api/projects/{project_id}/animate/status")
def animate_status(project_id: str):
    status = _get_status(project_id)
    if status.get("state") == "idle":
        try:
            stored = Project.load(project_id).metadata.get("animation_output")
        except (ValueError, FileNotFoundError):
            return status
        if stored:
            return {"state": "ready", "message": "Animation ready.", "progress": 1.0,
                    "animation_output": stored, "restored": True}
    return status


def _progress(project_id: str, stage: str, progress: float, message: str, **extra: Any) -> None:
    _set_status(project_id, state="running", stage=stage, progress=round(progress, 4), message=message)
    event_bus.publish("animation_progress", {"project_id": project_id, "stage": stage,
                                             "progress": round(progress, 4), "message": message, **extra})


def _send_to_buzzedit(videos: List[str]) -> Dict[str, Any]:
    """The MP4s into BuzzEdit: the first makes a project, the rest join its media."""
    from integrations.buzzedit_client import BuzzEditClient

    client = BuzzEditClient()
    created = client.import_recording(videos[0])
    buzzedit_id = created.get("id")
    if len(videos) > 1:
        resp = client._post(f"/api/projects/{buzzedit_id}/media/import",
                            {"paths": videos[1:], "copy": True}, timeout=(5, 600))
        if resp.status_code >= 400:
            raise RuntimeError(f"BuzzEdit could not add the other scenes: {resp.text[:300]}")
    return {"buzzedit_project_id": buzzedit_id, "videos": len(videos)}


def _run_animate(project_id: str, script: str, out_dir: str, payload: AnimateSchema) -> None:
    render = payload.render or payload.to_buzzedit
    try:
        if payload.start:
            animate.ensure(True, payload.start_timeout)
        os.makedirs(out_dir, exist_ok=True)
        episode_id = animate.episode(out_dir, script_path=script, casting_path=payload.casting_path,
                                     scenes=payload.scenes, render=render)
        _progress(project_id, "building", 0.05, "BuzzAnimate is building the episode...", job_id=episode_id)

        built = animate.wait_job(episode_id)
        result = built.get("result") or {}
        files = list(result.get("files") or [])
        warnings = list(result.get("warnings") or [])
        render_jobs = list(result.get("render_jobs") or [])
        _progress(project_id, "built", 0.3 if render_jobs else 0.9,
                  f"Episode built ({len(files)} files).", files=files)

        videos: List[str] = []
        for n, job_id in enumerate(render_jobs, start=1):
            _progress(project_id, "rendering", 0.3 + 0.6 * (n - 1) / len(render_jobs),
                      f"Rendering scene {n} of {len(render_jobs)}...", job_id=job_id)
            done = animate.wait_job(job_id)
            if done.get("output"):
                videos.append(done["output"])
        if render and not render_jobs:
            warnings.append("Rendering was asked for, but BuzzAnimate queued no previews.")

        output: Dict[str, Any] = {"out_dir": out_dir, "script": script, "files": files, "videos": videos,
                                  "warnings": warnings, "episode_job": episode_id}
        if payload.to_buzzedit:
            if videos:
                _progress(project_id, "buzzedit", 0.92, "Sending the scenes to BuzzEdit...")
                try:
                    output["buzzedit"] = _send_to_buzzedit(videos)
                except Exception as exc:  # the animation itself is done; say what did not go
                    logger.warning("animate(%s): BuzzEdit hand-off failed: %s", project_id, exc)
                    warnings.append(f"Sending to BuzzEdit failed: {exc}")
            else:
                warnings.append("Nothing was rendered, so nothing was sent to BuzzEdit.")

        project = Project.load(project_id)
        project.metadata["animation_output"] = output
        project.save()
        _set_status(project_id, state="ready", stage="ready", progress=1.0, message="Animation ready.",
                    animation_output=output, **({"warning": "; ".join(warnings)} if warnings else {}))
        event_bus.publish("animation_ready", {"project_id": project_id, "animation_output": output})
    except Exception as exc:
        logger.warning("animate(%s) failed: %s", project_id, exc)
        _set_status(project_id, state="failed", message=f"Animation failed: {exc}", error=str(exc))
        event_bus.publish("animation_failed", {"project_id": project_id, "error": str(exc)})
