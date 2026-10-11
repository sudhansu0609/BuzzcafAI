"""Publishing to YouTube (integrations/youtube_publish.py).

GET    /api/youtube/status                      client added? connected channels, brand links, sign-in state
POST   /api/youtube/client {json}               save the creator's Google OAuth client (Desktop app)
POST   /api/youtube/connect                     open Google sign-in for one more channel
POST   /api/youtube/channels/{id}/brand {brand} link a channel to a Studio brand
DELETE /api/youtube/channels/{id}               forget a channel and its sign-in
GET    /api/projects/{pid}/youtube              the draft (SEO titles, description, tags), the upload's progress, its result
POST   /api/projects/{pid}/youtube/publish      upload the rendered video in the background
GET    /api/projects/{pid}/youtube/studio       upload helper: the brand channel's YouTube Studio upload link
POST   /api/projects/{pid}/youtube/studio       open that link in the browser and show the video in Explorer
POST   /api/projects/{pid}/youtube/reveal       show the video or thumbnail in Explorer
POST   /api/projects/{pid}/youtube/manual {url} record a video uploaded by hand
"""
import logging
import os
import re
import subprocess
import threading
import webbrowser
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from core.models.project import Project
from integrations import youtube_publish as yt

logger = logging.getLogger("buzzcaf_ai.youtube")

router = APIRouter(tags=["youtube"])

#: project id -> {state: uploading|done|failed, progress, message, error}
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()


def _err(exc: Exception, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/api/youtube/status")
def youtube_status():
    return yt.status()


@router.post("/api/youtube/client")
def youtube_client(payload: Dict[str, Any] = Body(...)):
    text = payload.get("json") or ""
    try:
        return yt.save_client_secret(text if isinstance(text, str) else str(text))
    except yt.YouTubeError as exc:
        raise _err(exc)


@router.post("/api/youtube/connect")
def youtube_connect():
    try:
        return yt.start_login()
    except yt.YouTubeError as exc:
        raise _err(exc)


@router.post("/api/youtube/channels/{channel_id}/brand")
def youtube_channel_brand(channel_id: str, payload: Dict[str, Any] = Body(...)):
    try:
        return yt.set_channel_brand(channel_id, str(payload.get("brand") or ""))
    except yt.YouTubeError as exc:
        raise _err(exc)


@router.delete("/api/youtube/channels/{channel_id}")
def youtube_channel_delete(channel_id: str):
    return yt.disconnect(channel_id)


def _load(project_id: str) -> Project:
    try:
        return Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")


def _seo(project: Project) -> Optional[Dict[str, Any]]:
    rel = (project.assets or {}).get("seo_package") or "publish/publish.json"
    path = os.path.join(project.get_project_dir(), rel)
    try:
        with open(path, encoding="utf-8") as fh:
            return yt.parse_seo_package(fh.read())
    except OSError:
        return None


def _thumbnail(project: Project) -> str:
    report = project.metadata.get("buzzedit_report")
    thumb = report.get("thumbnail") if isinstance(report, dict) else ""
    return thumb if thumb and os.path.isfile(thumb) else ""


def draft(project: Project) -> Dict[str, Any]:
    seo = _seo(project)
    video = project.metadata.get("output_path") or ""
    return {
        "seo_found": bool(seo),
        "titles": (seo or {}).get("titles") or [project.name],
        "description": yt.description_with_hashtags((seo or {}).get("description", ""), (seo or {}).get("hashtags", [])),
        "tags": (seo or {}).get("tags") or [],
        "video_path": video,
        "video_exists": bool(video) and os.path.isfile(video),
        "thumbnail_path": _thumbnail(project),
        "channel_id": yt.channel_for_brand(project.brand) or "",
        "category_id": yt.DEFAULT_CATEGORY.get(project.brand, "24"),
    }


@router.get("/api/projects/{project_id}/youtube")
def project_youtube(project_id: str):
    project = _load(project_id)
    with _jobs_lock:
        job = dict(_jobs.get(project_id) or {})
    return {"draft": draft(project), "job": job or None, "result": project.metadata.get("youtube")}


class PublishRequest(BaseModel):
    channel_id: str
    title: str
    description: str = ""
    tags: List[str] = []
    privacy: str = "unlisted"
    publish_at: Optional[str] = None      # ISO 8601 with timezone; schedules a private video
    category_id: str = "24"
    made_for_kids: bool = False
    synthetic_media: bool = True
    thumbnail: bool = True


def _save_meta(project_id: str, key: str, value: Any) -> None:
    project = Project.load(project_id)
    if value is None:
        project.metadata.pop(key, None)
    else:
        project.metadata[key] = value
    project.save()


@router.post("/api/projects/{project_id}/youtube/publish")
def project_youtube_publish(project_id: str, req: PublishRequest):
    project = _load(project_id)
    d = draft(project)
    if not d["video_exists"]:
        raise HTTPException(status_code=409, detail="There is no rendered video for this project yet.")
    with _jobs_lock:
        if (_jobs.get(project_id) or {}).get("state") == "uploading":
            raise HTTPException(status_code=409, detail="This video is already uploading.")
        _jobs[project_id] = {"state": "uploading", "progress": 0.0, "message": "Starting the upload...", "error": None}
    # A saved session from an interrupted upload of the same file resumes it.
    session = project.metadata.get("youtube_upload_session") or {}
    session_url = session.get("url") if session.get("video_path") == d["video_path"] \
        and session.get("channel_id") == req.channel_id else None

    def progress(frac: float, message: str) -> None:
        with _jobs_lock:
            _jobs[project_id].update(progress=round(frac, 4), message=message)

    def run() -> None:
        try:
            result = yt.upload(
                d["video_path"], channel_id=req.channel_id, title=req.title, description=req.description,
                tags=req.tags, privacy=req.privacy, publish_at=req.publish_at or None,
                category_id=req.category_id, made_for_kids=req.made_for_kids,
                synthetic_media=req.synthetic_media,
                thumbnail_path=d["thumbnail_path"] if req.thumbnail else None, session_url=session_url,
                on_session=lambda url: _save_meta(project_id, "youtube_upload_session",
                                                  {"url": url, "video_path": d["video_path"],
                                                   "channel_id": req.channel_id}),
                on_progress=progress)
            channel = next((c for c in yt.status()["channels"] if c["id"] == req.channel_id), {})
            from datetime import datetime
            result.update(channel_id=req.channel_id, channel_title=channel.get("title", ""),
                          title=yt.clean_title(req.title), publish_at=req.publish_at or None,
                          uploaded_at=datetime.now().isoformat(timespec="seconds"))
            _save_meta(project_id, "youtube", result)
            _save_meta(project_id, "youtube_upload_session", None)
            with _jobs_lock:
                _jobs[project_id].update(state="done", progress=1.0, message="Uploaded.")
            logger.info("YouTube: %s uploaded as %s (%s).", project_id, result["video_id"], result["privacy"])
        except Exception as exc:  # noqa: BLE001 - shown on the panel
            logger.warning("YouTube upload of %s failed: %s", project_id, exc)
            with _jobs_lock:
                _jobs[project_id].update(state="failed", error=str(exc), message="Upload failed.")

    threading.Thread(target=run, name=f"youtube-upload-{project_id[:24]}", daemon=True).start()
    return {"status": "uploading"}


# ───────────────── Upload helper: publish through YouTube Studio by hand ─────────────────
#
# Until the Google project passes YouTube's API audit, API uploads are locked
# to Private. The helper opens YouTube Studio's upload screen for the brand's
# own channel in the creator's browser (where he is already signed in), shows
# the video in Explorer to drag in, and the panel has copy buttons for the
# SEO manager's title, description and tags. Nothing is automated on YouTube.


def _brand_channel_id(brand: str) -> str:
    """The UC... id of the brand's channel: the connected one, else config `youtube_upload_channels`,
    else resolved once from the matching handle in `owner_channel_ids`."""
    from integrations.llm import load_config, save_config

    connected = yt.channel_for_brand(brand)    # a channel signed in on the Bulk Editor tab
    if connected:
        return connected
    cfg = load_config()
    known = dict(cfg.get("youtube_upload_channels") or {})
    if known.get(brand):
        return known[brand]
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())  # noqa: E731
    for ref in cfg.get("owner_channel_ids") or []:
        ref = str(ref).strip()
        if ref.startswith("UC") and len(ref) == 24:
            continue  # an id alone does not say which brand it is
        if norm(ref) != norm(brand):
            continue
        handle = ref if ref.startswith("@") else f"@{ref}"
        try:
            page = requests.get(f"https://www.youtube.com/{handle}", timeout=15, cookies={"CONSENT": "YES+1"},
                                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}).text
        except requests.RequestException as exc:
            logger.info("YouTube: could not look up %s (%s).", handle, exc)
            return ""
        m = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', page)
        if m:
            known[brand] = m.group(1)
            cfg["youtube_upload_channels"] = known
            save_config(cfg)
            return m.group(1)
    return ""


def _reveal(path: str) -> bool:
    if not path or not os.path.isfile(path):
        return False
    try:
        subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(path)}"])
        return True
    except OSError as exc:
        logger.info("Could not open Explorer for %s (%s).", path, exc)
        return False


@router.get("/api/projects/{project_id}/youtube/studio")
def project_youtube_studio_info(project_id: str):
    project = _load(project_id)
    cid = _brand_channel_id(project.brand)
    return {"brand": project.brand, "channel_id": cid,
            "upload_url": f"https://studio.youtube.com/channel/{cid}/videos/upload?d=ud" if cid
            else "https://www.youtube.com/upload"}


@router.post("/api/projects/{project_id}/youtube/studio")
def project_youtube_studio_open(project_id: str):
    """Open YouTube Studio's upload screen and show the video in Explorer."""
    project = _load(project_id)
    d = draft(project)
    if not d["video_exists"]:
        raise HTTPException(status_code=409, detail="There is no rendered video for this project yet.")
    info = project_youtube_studio_info(project_id)
    webbrowser.open(info["upload_url"])
    _reveal(d["video_path"])
    return info


@router.post("/api/projects/{project_id}/youtube/reveal")
def project_youtube_reveal(project_id: str, payload: Dict[str, Any] = Body(...)):
    d = draft(_load(project_id))
    path = d["thumbnail_path"] if payload.get("what") == "thumbnail" else d["video_path"]
    if not _reveal(path):
        raise HTTPException(status_code=404, detail="That file is not on disk.")
    return {"status": "shown", "path": path}


@router.post("/api/projects/{project_id}/youtube/manual")
def project_youtube_manual(project_id: str, payload: Dict[str, Any] = Body(...)):
    """Record a video the creator uploaded himself, from its YouTube link."""
    _load(project_id)
    url = str(payload.get("url") or "").strip()
    m = re.search(r"(?:youtu\.be/|v=|/video/|/shorts/)([\w-]{11})", url)
    if not m:
        raise HTTPException(status_code=400, detail="That is not a YouTube video link.")
    from datetime import datetime
    result = {"video_id": m.group(1), "url": f"https://youtu.be/{m.group(1)}", "privacy": "",
              "manual": True, "title": str(payload.get("title") or "")[:100],
              "uploaded_at": datetime.now().isoformat(timespec="seconds")}
    _save_meta(project_id, "youtube", result)
    return result
