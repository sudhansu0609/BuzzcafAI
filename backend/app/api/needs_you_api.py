"""GET /api/needs_you -- everything waiting on the creator, with its buttons
(app/services/needs_you.py). The app shell polls it and pops up when
something new is waiting.

GET /api/video_slot -- the one video being made now and the ones waiting in
line behind it (app/services/video_slot.py)."""
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import needs_you

router = APIRouter()


@router.get("/api/needs_you")
def get_needs_you() -> Dict[str, Any]:
    return needs_you.collect()


class SeenRequest(BaseModel):
    keys: List[str] = []


@router.post("/api/needs_you/seen")
def post_seen(req: SeenRequest) -> Dict[str, Any]:
    """Seen it / Dismiss all: the items leave the pop-up until they are settled."""
    return needs_you.mark_seen(req.keys, True)


@router.post("/api/needs_you/unseen")
def post_unseen(req: SeenRequest) -> Dict[str, Any]:
    """Bring dismissed items back into the pop-up."""
    return needs_you.mark_seen(req.keys, False)


@router.get("/api/video_slot")
def get_video_slot() -> Dict[str, Any]:
    from app.services import video_slot
    return {"active": video_slot.active(), "waiting": video_slot.waiting()}
