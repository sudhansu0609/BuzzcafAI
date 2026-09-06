"""
Video intelligence routes (roadmap v6, S1).

    POST /api/video-intel/analyze   {url, channel?, force?} -> the analysis (video or channel)
    GET  /api/video-intel/recent    past analyses, newest first
    GET  /api/video-intel/{id}      one stored analysis

Analysis is synchronous (captions + baseline + one model call); FastAPI runs
the sync handler in its threadpool so the rest of the app stays responsive.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import video_intel
from app.services.events import bus

logger = logging.getLogger("buzzcaf_ai.video_intel_api")

router = APIRouter(prefix="/api/video-intel", tags=["Video intelligence"])


class AnalyzeSchema(BaseModel):
    url: str
    channel: Optional[str] = None
    force: bool = False


@router.post("/analyze")
def analyze(payload: AnalyzeSchema):
    try:
        video_intel.parse_target(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        result = video_intel.analyze(payload.url, payload.channel, payload.force)
    except video_intel.VideoFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - surface, never hang the UI
        logger.exception("analysis failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(exc)[:200]}")
    bus.publish("analysis_done", {
        "id": result.get("id"),
        "kind": result.get("kind"),
        "title": (result.get("video") or {}).get("title"),
        "simulated": result.get("simulated"),
    })
    return result


@router.get("/recent")
def recent():
    return {"items": video_intel.recent_analyses()}


@router.get("/{item_id}")
def one(item_id: str):
    data = video_intel.load_analysis(item_id)
    if not data:
        raise HTTPException(status_code=404, detail="No analysis with that id.")
    return data
