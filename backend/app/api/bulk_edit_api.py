"""Bulk Editor tab (integrations/youtube_bulk_edit.py): edit titles and
descriptions across a whole channel, with the channels connected at the top of
the same tab (integrations/youtube_publish.py).

POST /api/bulk-edit/preview {channel_id, rules}       dry run: what would change
POST /api/bulk-edit/apply {preview_id, ids, confirm}  back up, then edit (background)
GET  /api/bulk-edit/job                               progress of the running apply/restore
GET  /api/bulk-edit/backups?channel_id=               backups for that channel, newest first
POST /api/bulk-edit/restore/check {channel_id, backup} how many videos a restore would change
POST /api/bulk-edit/restore {channel_id, backup, confirm}
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from integrations import youtube_bulk_edit as bulk
from integrations import youtube_publish as yt

router = APIRouter(prefix="/api/bulk-edit", tags=["bulk-edit"])


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


class PreviewRequest(BaseModel):
    channel_id: str
    rules: Dict[str, Any] = {}


class ApplyRequest(BaseModel):
    preview_id: str
    ids: List[str]
    confirm: int


@router.post("/preview")
def bulk_preview(req: PreviewRequest):
    try:
        return bulk.preview(req.channel_id, req.rules)
    except (yt.YouTubeError, ValueError) as exc:
        raise _err(exc)


@router.post("/apply")
def bulk_apply(req: ApplyRequest):
    try:
        return bulk.apply(req.preview_id, req.ids, req.confirm)
    except (yt.YouTubeError, ValueError) as exc:
        raise _err(exc)


@router.get("/job")
def bulk_job():
    return bulk.job()


@router.get("/backups")
def bulk_backups(channel_id: str):
    try:
        return {"backups": bulk.list_backups(channel_id)}
    except yt.YouTubeError as exc:
        raise _err(exc)


@router.post("/restore/check")
def bulk_restore_check(payload: Dict[str, Any] = Body(...)):
    try:
        plan = bulk.restore_plan(str(payload.get("channel_id") or ""), str(payload.get("backup") or ""))
    except yt.YouTubeError as exc:
        raise _err(exc)
    return {"count": len(plan["entries"]),
            "titles": [e["video"]["title"] + "  ->  " + e["title"] for e in plan["entries"][:50]]}


@router.post("/restore")
def bulk_restore(payload: Dict[str, Any] = Body(...)):
    try:
        return bulk.restore(str(payload.get("channel_id") or ""), str(payload.get("backup") or ""),
                            int(payload.get("confirm") or -1))
    except (yt.YouTubeError, ValueError) as exc:
        raise _err(exc)
