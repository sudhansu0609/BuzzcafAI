"""
Story adaptation (AUTO_STORY_PLAN.md, brief L2): a Story Library entry made
into a Raat3Baje script in the creator's voice (app/services/story_adapt.py).

    POST /api/stories/adapt                {entry_id, parts?, minutes_per_part?, inspired?, run?,
                                            story_index?, story_title?} -> job
    GET  /api/stories/adapt/pieces/{entry_id}  {entry_id, title, pieces: [{index, title, words}], default}
    GET  /api/stories/adapt/jobs/{id}
    GET  /api/stories/adapt/{project_id}   {project_id, state, human_score, parts, rights, steps, ...}
"""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import story_adapt

router = APIRouter(tags=["Story adaptation"])


class AdaptSchema(BaseModel):
    entry_id: str
    parts: Optional[int] = None
    minutes_per_part: Optional[float] = None
    inspired: Optional[bool] = None
    run: Optional[bool] = None
    story_index: Optional[int] = None
    story_title: Optional[str] = None
    channel: Optional[str] = None


@router.post("/api/stories/adapt")
def adapt(payload: AdaptSchema):
    try:
        project_id = story_adapt.adapt(
            payload.entry_id, parts=payload.parts or 1, minutes_per_part=payload.minutes_per_part or 20,
            inspired=bool(payload.inspired), run=False, story_index=payload.story_index,
            story_title=payload.story_title, channel=payload.channel or story_adapt.DEFAULT_CHANNEL)
    except story_adapt.AdaptError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if payload.run is False:
        return {"job_id": None, "kind": "adapt", "project_id": project_id, "state": "created",
                "message": "Created; not started", "result": None, "error": None}
    return story_adapt.start_job(project_id)


@router.post("/api/stories/adapt/{project_id}/resume")
def adapt_resume(project_id: str):
    """Carry an adaptation on from the step it stopped at (a failed Shorts Scripts step
    used to leave a finished script stuck with no way to re-run it)."""
    try:
        from core.models.project import Project
        Project.load(project_id)
    except Exception:
        raise HTTPException(status_code=404, detail=f"No project {project_id}")
    return story_adapt.start_job(project_id)


@router.get("/api/stories/adapt/pieces/{entry_id}")
def adapt_pieces(entry_id: str):
    try:
        return story_adapt.pieces(entry_id)
    except story_adapt.AdaptError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/api/stories/adapt/jobs/{job_id}")
def adapt_job(job_id: str):
    found = story_adapt.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="No such job")
    return found


@router.get("/api/stories/adapt/{project_id}")
def adapt_status(project_id: str):
    try:
        return story_adapt.status(project_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=f"Project not found: {exc}")
