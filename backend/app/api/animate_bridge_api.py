"""Produce animation (BuzzAnimate producer) for Khayal3Baje / Originals projects (ST1)."""
from fastapi import APIRouter, HTTPException

from app.services import animate_bridge, video_slot

router = APIRouter()


@router.post("/api/projects/{project_id}/animation/produce")
def produce(project_id: str, when_free: bool = False):
    if not when_free:
        info = video_slot.active(project_id)
        if info:
            raise HTTPException(status_code=409, detail=video_slot.busy_detail(info))
    try:
        job = animate_bridge.produce(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job_id": job["job_id"], "state": job["state"]}


@router.get("/api/projects/{project_id}/animation")
def animation_status(project_id: str):
    return animate_bridge.status(project_id)
