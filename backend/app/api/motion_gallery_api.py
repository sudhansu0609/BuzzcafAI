"""The Motion Gallery proxy (docs/MOTION_GRAPHICS_PLAN.md M11): starts
BuzzEdit's render of every registered motion composition and opens the
finished folder's index.html -- the Studio button next to the art style /
effects settings.

POST /api/motion_gallery/start {themes?, width?, height?} -> BuzzEdit's own
                                 {state, folder, count, errors, total}
GET  /api/motion_gallery/status                 -> the same, polled
POST /api/motion_gallery/open                    -> opens the last rendered
                                 gallery's index.html (Windows only)
"""
import os
import sys
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from integrations.buzzedit_client import BuzzEditClient, BuzzEditUnavailable

router = APIRouter(prefix="/api/motion_gallery", tags=["motion_gallery"])


class StartBody(BaseModel):
    themes: Optional[List[str]] = None
    width: Optional[int] = None
    height: Optional[int] = None


@router.post("/start")
def start(body: StartBody) -> Dict[str, Any]:
    try:
        return BuzzEditClient().start_motion_gallery(body.themes, body.width, body.height)
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/status")
def status() -> Dict[str, Any]:
    try:
        return BuzzEditClient().motion_gallery_status()
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/open")
def open_gallery() -> Dict[str, Any]:
    """Opens the last rendered gallery's index.html in the default browser --
    BuzzEdit and the Studio run on the same machine, so the folder path it
    reports is openable here too."""
    try:
        data = BuzzEditClient().motion_gallery_status()
    except BuzzEditUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    folder = data.get("folder")
    if not folder:
        raise HTTPException(status_code=404, detail="No motion gallery has been rendered yet.")
    index_path = os.path.join(folder, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=404, detail="The gallery folder has no index.html.")
    if sys.platform != "win32":
        raise HTTPException(status_code=501, detail="Opening a folder is only available on Windows.")
    try:
        os.startfile(index_path)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open the gallery: {exc}")
    return {"status": "success", "path": index_path}
