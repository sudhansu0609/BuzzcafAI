"""
Auto Story (AUTO_STORY_PLAN.md §3.3): videos made end to end in the creator's voice.

    GET  /api/auto_story/settings
    POST /api/auto_story/settings              {enabled?, publish?, per_channel?, formats?, face_intro_clips?, voice_style?}
    GET  /api/auto_story/formats               {channel: [{key, label}]} (a mood reel also carries
                                                `lengths`, `styles`, `themes`)
    GET  /api/auto_story/voices                {voices: ["sudhansu", ...]}
    GET  /api/auto_story/moods                 {moods: [{id, label, description, style}]} (VOICE_DELIVERY_PLAN.md S1)
    POST /api/auto_story/voice_preview         {channel, voice?, text?, style?} -> {job_id}
    GET  /api/auto_story/voice_preview/{id}    the preview job's state
    GET  /api/auto_story/voice_preview/{id}/audio  the finished preview's wav
    GET  /api/auto_story/records               {records: [...]}
    POST /api/auto_story/make                  {channel, format, length?, voice?, publish?, style?} -> job
    GET  /api/auto_story/jobs/{id}
    GET  /api/auto_story/{project_id}          the project's record
    POST /api/auto_story/{project_id}/run      {voice?, publish?, orientation?} -> job
    POST /api/auto_story/{project_id}/open_package
    POST /api/auto_story/{project_id}/post_instagram  {force?} -> posted.instagram (REELS_DESK_PLAN.md R7)
    POST /api/auto_story/{project_id}/approve        -> the record, review.state "approved" (ask before
                                                         publishing, STUDIO_DIRECTOR_PLAN.md)
    POST /api/auto_story/{project_id}/reject         {reason?} -> the record, review.state "rejected"
                                                         (logged to knowledge/decisions/log.jsonl)
    POST /api/auto_story/{project_id}/regenerate     -> job (re-runs make() with the same channel/format/
                                                         length/theme)
    GET  /api/auto_story/{project_id}/preview/video  the record's final file (for a "Needs you" preview)
    GET  /api/auto_story/{project_id}/preview/cover  the record's cover frame
"""

import os
import sys
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import auto_story

router = APIRouter(tags=["Auto story"])


class SettingsSchema(BaseModel):
    enabled: Optional[bool] = None
    publish: Optional[bool] = None
    per_channel: Optional[Dict[str, int]] = None
    formats: Optional[Dict[str, List[str]]] = None
    face_intro_clips: Optional[Dict[str, str]] = None
    voice_style: Optional[Dict[str, Dict[str, Any]]] = None


class VoiceStyleSchema(BaseModel):
    mood: Optional[str] = None
    pace: Optional[float] = None
    word_gap_ms: Optional[float] = None
    phrase_pause_s: Optional[float] = None
    sentence_pause_s: Optional[float] = None
    exaggeration: Optional[float] = None
    temperature: Optional[float] = None
    cfg_weight: Optional[float] = None


class VoicePreviewSchema(BaseModel):
    channel: str
    voice: Optional[str] = None
    text: Optional[str] = None
    style: Optional[VoiceStyleSchema] = None


class MakeSchema(BaseModel):
    channel: str
    format: str
    length: Optional[Union[float, str]] = None
    voice: Optional[str] = None
    publish: Optional[bool] = None
    style: Optional[str] = None
    theme: Optional[str] = None


class RunSchema(BaseModel):
    voice: Optional[str] = None
    publish: Optional[bool] = None
    orientation: Optional[str] = None


def _refuse_if_busy(when_free: bool, exclude: Optional[str] = None) -> None:
    """One video at a time (2026-10-26): a start while another video is being
    made is refused with the `video_running` body the page turns into its
    pop-up -- unless `when_free`, when the job waits its turn in line."""
    if when_free:
        return
    from app.services import video_slot
    info = video_slot.active(exclude)
    if info:
        raise HTTPException(status_code=409, detail=video_slot.busy_detail(info))


@router.get("/api/auto_story/settings")
def get_settings():
    return auto_story.settings()


@router.post("/api/auto_story/settings")
def post_settings(payload: SettingsSchema):
    patch: Dict[str, Any] = {k: v for k, v in payload.model_dump().items() if v is not None}
    return auto_story.set_settings(patch)


@router.get("/api/auto_story/formats")
def formats():
    from app.services import mood_reel, shorts_desk
    out = {}
    for channel, fmts in shorts_desk.FORMATS.items():
        extra = ([{"key": mood_reel.KEY, "label": mood_reel.LABEL, "lengths": list(mood_reel.LENGTHS),
                   "styles": list(mood_reel.STYLES),
                   "themes": [{"key": k, "label": v["label"]} for k, v in mood_reel.THEMES.items()]}]
                 if channel in mood_reel.CHANNELS else [])
        out[channel] = [{"key": k, "label": v["label"]} for k, v in fmts.items()] + extra + \
            [{"key": auto_story.LONG_STORY, "label": auto_story.LONG_STORY_LABEL}]
    return out


@router.get("/api/auto_story/voices")
def voices():
    return {"voices": auto_story.voices()}


@router.get("/api/auto_story/records")
def records():
    return {"records": auto_story.list_records()}


@router.post("/api/auto_story/make")
def make(payload: MakeSchema, when_free: bool = False):
    from app.services import shorts_desk
    if payload.channel not in shorts_desk.FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {payload.channel}")
    if payload.format not in auto_story.channel_formats(payload.channel):
        raise HTTPException(status_code=400, detail=f"{payload.format!r} is not a {payload.channel} format.")
    if payload.format == auto_story.LONG_STORY and payload.length not in (None, ""):
        try:
            float(payload.length)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="A long story's length is a number of minutes.")
    _refuse_if_busy(when_free)
    return auto_story.start_job("make", auto_story.make, payload.channel, payload.format, payload.length,
                                voice=payload.voice or auto_story.default_voice_for(payload.channel),
                                publish=bool(payload.publish), style=payload.style or None,
                                theme=payload.theme or None)


@router.get("/api/auto_story/jobs/{job_id}")
def get_job(job_id: str):
    found = auto_story.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="No such job")
    return found


@router.get("/api/auto_story/moods")
def moods():
    return {"moods": auto_story.moods()}


@router.post("/api/auto_story/voice_preview")
def voice_preview_start(payload: VoicePreviewSchema):
    from app.services import shorts_desk
    from integrations import idle_offload
    if payload.channel not in shorts_desk.FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {payload.channel}")
    style = payload.style.model_dump(exclude_none=True) if payload.style else None
    try:
        # A preview is a BuzzEdit narration job, same as any other -- counted
        # as Studio activity (STUDIO_DIRECTOR_PLAN.md enhancement 5) so the
        # idle watcher does not treat a creator waiting on one as idle.
        with idle_offload.busy():
            return auto_story.voice_preview_start(payload.channel, voice=payload.voice, text=payload.text, style=style)
    except Exception as exc:  # noqa: BLE001 - BuzzEdit down or refused
        raise HTTPException(status_code=502, detail=str(exc)[:300])


@router.get("/api/auto_story/voice_preview/{job_id}")
def voice_preview_status(job_id: str):
    from integrations import idle_offload
    try:
        # The page polls this every couple of seconds while a preview
        # renders: each poll refreshes `idle_offload`'s own activity clock.
        with idle_offload.busy():
            return auto_story.voice_preview_status(job_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)[:300])


@router.get("/api/auto_story/voice_preview/{job_id}/audio")
def voice_preview_audio(job_id: str):
    from fastapi.responses import FileResponse
    try:
        path = auto_story.voice_preview_audio_path(job_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)[:300])
    return FileResponse(path, media_type="audio/wav")


def _project_or_404(project_id: str):
    from core.models.project import Project
    try:
        return Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")


@router.get("/api/auto_story/{project_id}")
def get_record(project_id: str):
    _project_or_404(project_id)
    rec = auto_story.record(project_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="This project has no auto-story record")
    return rec


@router.post("/api/auto_story/{project_id}/run")
def run(project_id: str, payload: Optional[RunSchema] = None, when_free: bool = False):
    from app.services import produce_queue
    payload = payload or RunSchema()
    project = _project_or_404(project_id)
    if payload.orientation not in (None, "vertical", "landscape"):
        raise HTTPException(status_code=400, detail="orientation must be 'vertical' or 'landscape'")
    if produce_queue.active_item_for(project_id):
        raise HTTPException(status_code=409, detail="This project is already in the production queue.")
    _refuse_if_busy(when_free, exclude=project_id)
    return auto_story.start_job("run", auto_story.run, project_id,
                                voice=payload.voice or auto_story.default_voice_for(project.brand),
                                publish=bool(payload.publish), orientation=payload.orientation)


@router.post("/api/auto_story/{project_id}/open_package")
def open_package(project_id: str):
    _project_or_404(project_id)
    path = auto_story.package_dir(project_id)
    if not path:
        raise HTTPException(status_code=404, detail="This project has no Instagram package yet")
    if sys.platform != "win32":
        raise HTTPException(status_code=501, detail="Opening a folder is only available on Windows.")
    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not open the folder: {exc}")
    return {"status": "success", "path": path}


class PostInstagramSchema(BaseModel):
    force: Optional[bool] = None


@router.post("/api/auto_story/{project_id}/post_instagram")
def post_instagram(project_id: str, payload: Optional[PostInstagramSchema] = None):
    _project_or_404(project_id)
    payload = payload or PostInstagramSchema()
    try:
        return auto_story.post_instagram(project_id, force=bool(payload.force))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# --- the approval gate (STUDIO_DIRECTOR_PLAN.md: ask before publishing; Fable review #10) ---

class RejectSchema(BaseModel):
    reason: Optional[str] = None


@router.post("/api/auto_story/{project_id}/approve")
def approve(project_id: str):
    _project_or_404(project_id)
    try:
        return auto_story.approve(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/auto_story/{project_id}/reject")
def reject(project_id: str, payload: Optional[RejectSchema] = None):
    _project_or_404(project_id)
    payload = payload or RejectSchema()
    try:
        return auto_story.reject(project_id, reason=payload.reason or "")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/auto_story/{project_id}/regenerate")
def regenerate(project_id: str, when_free: bool = False):
    _project_or_404(project_id)
    _refuse_if_busy(when_free)
    try:
        return auto_story.start_job("regenerate", auto_story.regenerate, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/auto_story/{project_id}/preview/{kind}")
def preview_file(project_id: str, kind: str):
    """A finished record's video or cover, for the "Needs you" list and the
    Story Desk's own Approve / Reject -- resolved from the record itself, no
    arbitrary path from the caller."""
    from fastapi.responses import FileResponse
    _project_or_404(project_id)
    if kind not in ("video", "cover"):
        raise HTTPException(status_code=404, detail="Unknown preview kind")
    rec = auto_story.record(project_id) or {}
    path = rec.get("final") if kind == "video" else rec.get("cover")
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not available yet")
    return FileResponse(path, media_type="video/mp4" if kind == "video" else "image/jpeg")


class ArchiveRecordSchema(BaseModel):
    archived: bool = True


@router.delete("/api/auto_story/{project_id}")
def delete_record(project_id: str):
    try:
        return auto_story.delete_record(project_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Auto story project not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/api/auto_story/{project_id}/archive")
def archive_record(project_id: str, payload: Optional[ArchiveRecordSchema] = None):
    payload = payload or ArchiveRecordSchema()
    try:
        return auto_story.archive_record(project_id, archived=payload.archived)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Auto story project not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

