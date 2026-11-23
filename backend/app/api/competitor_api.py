"""
The Competitor Desk: competitors' viral videos, why they worked, our own
version into the Topic Vault. See app/services/competitor_desk.py.

    GET  /api/competitors/{brand}/videos?days=30&min_outlier=0&sort=outlier
    POST /api/competitors/{brand}/scan                -> job
    POST /api/competitors/{brand}/discover            -> job (finds the competitors itself)
    POST /api/competitors/{brand}/exclude {channel}   -> removes one for good
    POST /api/competitors/{brand}/analyze {video_ids} -> job
    GET  /api/competitors/jobs/{id}
    GET  /api/competitors/{brand}/analyses/latest
    POST /api/competitors/{brand}/idea    {idea, evidence} -> vault row
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import audience_desk, competitor_desk

router = APIRouter(prefix="/api/competitors", tags=["Competitor desk"])


class AnalyzeSchema(BaseModel):
    video_ids: List[str]


class ExcludeSchema(BaseModel):
    channel: str


class IdeaSchema(BaseModel):
    idea: Dict[str, Any]
    evidence: List[Dict[str, Any]] = []


class SettingsSchema(BaseModel):
    enabled: Optional[bool] = None
    rediscover_days: Optional[int] = None
    brands: Optional[List[str]] = None


@router.get("/settings")
def get_settings():
    return competitor_desk.settings()


@router.post("/settings")
def post_settings(payload: SettingsSchema):
    patch = payload.dict(exclude_none=True)
    if "rediscover_days" in patch:
        patch["rediscover_days"] = max(1, patch["rediscover_days"])
    return competitor_desk.set_settings(patch)


@router.post("/run_all")
def run_all():
    return audience_desk.start_job("competitor_run_all", competitor_desk.run_all)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = audience_desk.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown job")
    return found


@router.get("/{brand}/videos")
def videos(brand: str, days: int = 30, min_outlier: float = 0, sort: str = "outlier"):
    return competitor_desk.videos(brand, days, min_outlier, sort)


@router.post("/{brand}/scan")
def scan(brand: str):
    return audience_desk.start_job("competitor_scan", competitor_desk.scan, brand, 60)


@router.post("/{brand}/discover")
def discover(brand: str):
    return audience_desk.start_job("competitor_discover", competitor_desk.discover, brand, 10)


@router.post("/{brand}/exclude")
def exclude(brand: str, payload: ExcludeSchema):
    if not payload.channel.strip():
        raise HTTPException(status_code=400, detail="channel is required")
    return competitor_desk.exclude(brand, payload.channel)


@router.post("/{brand}/analyze")
def analyze(brand: str, payload: AnalyzeSchema):
    if not payload.video_ids:
        raise HTTPException(status_code=400, detail="video_ids is required")
    return audience_desk.start_job("competitor_analyze", competitor_desk.analyze, brand, payload.video_ids[:competitor_desk.MAX_ANALYZE])


@router.get("/{brand}/analyses/latest")
def latest(brand: str):
    return competitor_desk.latest_analysis(brand) or {"brand": brand, "videos": [], "patterns": [], "title_formulas": [], "gaps": [], "ideas": []}


@router.post("/{brand}/idea")
def idea(brand: str, payload: IdeaSchema):
    if not str(payload.idea.get("title") or "").strip():
        raise HTTPException(status_code=400, detail="idea.title is required")
    return {"status": "success", "topic": competitor_desk.save_idea(brand, payload.idea, payload.evidence)}
