"""
The Audience Desk (2026-10-22): viewer comments -> what they are asking for
-> Topic Vault rows with the evidence. See app/services/audience_desk.py.

    GET  /api/audience/sources?channel=   the brand's own channels, queries, competitors
    POST /api/audience/sources            {channel, queries?, competitors?, own?}
    POST /api/audience/mine               {channel, max_videos?, per_video?} -> job
    GET  /api/audience/jobs/{id}
    GET  /api/audience/latest?channel=    the last run (videos, comments read, findings)
    GET  /api/audience/history?channel=
    POST /api/audience/save               {channel, finding} -> vault row
    GET/POST /api/audience/settings       nightly mining: enabled, max_videos, per_video, auto_save_top
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import audience_desk

router = APIRouter(prefix="/api/audience", tags=["Audience desk"])


class SourcesSchema(BaseModel):
    channel: str
    queries: Optional[List[str]] = None
    competitors: Optional[List[Any]] = None
    own: Optional[List[str]] = None


class MineSchema(BaseModel):
    channel: str
    max_videos: Optional[int] = None
    per_video: Optional[int] = None


class SaveSchema(BaseModel):
    channel: str
    finding: Dict[str, Any]


class SettingsSchema(BaseModel):
    enabled: Optional[bool] = None
    max_videos: Optional[int] = None
    per_video: Optional[int] = None
    auto_save_top: Optional[int] = None


def _brand(channel: str) -> str:
    brand = (channel or "").strip()
    if not brand:
        raise HTTPException(status_code=400, detail="channel is required")
    return brand


@router.get("/sources")
def get_sources(channel: str):
    return audience_desk.sources(_brand(channel))


@router.post("/sources")
def put_sources(payload: SourcesSchema):
    return audience_desk.set_sources(_brand(payload.channel), payload.dict(exclude_none=True, exclude={"channel"}))


@router.post("/mine")
def mine(payload: MineSchema):
    brand = _brand(payload.channel)
    return audience_desk.start_job("mine", audience_desk.run, brand, payload.max_videos, payload.per_video)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = audience_desk.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown job")
    return found


@router.get("/latest")
def latest(channel: str):
    return audience_desk.latest(_brand(channel)) or {"brand": channel, "findings": [], "videos": [], "comments_read": 0}


@router.get("/history")
def history(channel: str):
    return {"channel": channel, "runs": audience_desk.history(_brand(channel))}


@router.post("/save")
def save(payload: SaveSchema):
    if not str(payload.finding.get("topic") or "").strip():
        raise HTTPException(status_code=400, detail="finding.topic is required")
    row = audience_desk.save_to_vault(_brand(payload.channel), payload.finding, added_by="user")
    return {"status": "success", "topic": row}


@router.get("/settings")
def get_settings():
    return audience_desk.settings()


@router.post("/settings")
def put_settings(payload: SettingsSchema):
    return audience_desk.set_settings(payload.dict(exclude_none=True))
