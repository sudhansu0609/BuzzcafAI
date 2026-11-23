"""The creator's own footage: folder, catalog and notes (docs/OWN_FOOTAGE_PLAN.md)."""
from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services import footage
from app.services.audience_desk import job as get_job, start_job
from core.models.project import Project

router = APIRouter(tags=["footage"])


class FootageBody(BaseModel):
    dir: Optional[str] = None
    mode: Optional[str] = None


class NoteBody(BaseModel):
    text: str = ""


def _project(project_id: str) -> Project:
    try:
        return Project.load(project_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=404, detail="Project not found.")


@router.get("/api/projects/{project_id}/footage")
def get_footage(project_id: str):
    project = _project(project_id)
    return {**footage.settings(project), "clips": footage.load_catalog(project)}


@router.post("/api/projects/{project_id}/footage")
def post_footage(project_id: str, body: FootageBody):
    _project(project_id)
    try:
        return footage.set_footage(project_id, body.dir, body.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/projects/{project_id}/footage/scan")
def scan_footage(project_id: str, refresh: bool = False):
    project = _project(project_id)
    job = start_job("footage", lambda p, refresh, progress: footage.catalog(p, refresh=refresh, progress=progress),
                    project, refresh)
    return {"job_id": job["job_id"]}


@router.get("/api/footage/jobs/{job_id}")
def footage_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return job


@router.post("/api/projects/{project_id}/footage/{clip_id}/note")
def clip_note(project_id: str, clip_id: str, body: NoteBody):
    _project(project_id)
    try:
        return footage.set_note(project_id, clip_id, body.text)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown clip.")


@router.get("/api/projects/{project_id}/footage/{clip_id}/frame")
def clip_frame(project_id: str, clip_id: str):
    project = _project(project_id)
    for clip in footage.load_catalog(project):
        if clip.get("id") == clip_id and clip.get("frame"):
            path = os.path.join(footage.frames_dir(project), clip["frame"])
            if os.path.isfile(path):
                return FileResponse(path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="No frame for that clip.")
