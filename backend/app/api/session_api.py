"""Recording sessions, face layout and episode formats (app/services/session_format.py).

GET  /api/projects/{id}/session        the project's session: Shorts first or not, how many, the
                                       written Shorts, the split of its recording, its face layout
                                       and its episode format (with the channel's formats)
PUT  /api/projects/{id}/session        {session_format?, shorts_count?, split_at_s?, episode_format?}
                                       -- null clears an override (back to the channel's default)
GET  /api/channel_formats              every session channel's defaults, its episode formats and
                                       the format its next nightly episode gets
PUT  /api/channel_formats/{channel}    {shorts_first?, shorts_count?, face_layout?, face_intro_seconds?,
                                       next_format?}
"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import longform_nightly, session_format
from core.models.project import Project

router = APIRouter(tags=["session"])


class ProjectSessionSchema(BaseModel):
    session_format: Optional[str] = None
    shorts_count: Optional[int] = None
    split_at_s: Optional[float] = None
    episode_format: Optional[str] = None


class ChannelFormatSchema(BaseModel):
    shorts_first: Optional[bool] = None
    shorts_count: Optional[int] = None
    face_layout: Optional[str] = None
    face_intro_seconds: Optional[float] = None
    next_format: Optional[str] = None
    lock_format: Optional[str] = None


def _project(project_id: str) -> Project:
    try:
        return Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")


def _view(project: Project) -> Dict[str, Any]:
    from app.services.writing_style import canonical_channel
    channel = canonical_channel(project.brand)
    view = session_format.project_view(project)
    view["episode_format"] = project.metadata.get("episode_format") or None
    view["episode_formats"] = [{"key": f["key"], "label": f["label"]} for f in longform_nightly.formats_for(channel)]
    view["recording_script"] = project.assets.get("recording_script")
    return view


@router.get("/api/projects/{project_id}/session")
def get_project_session(project_id: str):
    return _view(_project(project_id))


@router.put("/api/projects/{project_id}/session")
def put_project_session(project_id: str, payload: ProjectSessionSchema):
    project = _project(project_id)
    provided = payload.model_dump(exclude_unset=True)
    meta = project.metadata
    if "session_format" in provided:
        value = provided["session_format"]
        if value is None:
            meta.pop("session_format", None)
        elif value in session_format.SESSION_FORMATS:
            meta["session_format"] = value
        else:
            raise HTTPException(status_code=400, detail=f"session_format must be one of "
                                                         f"{', '.join(session_format.SESSION_FORMATS)} (or null).")
    if "shorts_count" in provided:
        value = provided["shorts_count"]
        if value is None:
            meta.pop("session_shorts_count", None)
        elif value in session_format.SHORTS_COUNTS:
            meta["session_shorts_count"] = int(value)
        else:
            raise HTTPException(status_code=400, detail="shorts_count must be 3 or 4 (or null).")
    if "split_at_s" in provided:
        value = provided["split_at_s"]
        if value is None:
            meta.pop("session_split_s", None)
        elif 0 <= float(value) <= 6 * 3600:
            meta["session_split_s"] = round(float(value), 2)
        else:
            raise HTTPException(status_code=400, detail="split_at_s must be seconds into the recording.")
    if "episode_format" in provided:
        value = provided["episode_format"]
        from app.services.writing_style import canonical_channel
        keys = [f["key"] for f in longform_nightly.formats_for(canonical_channel(project.brand))]
        if value is None or value == "":
            meta.pop("episode_format", None)
        elif value in keys:
            meta["episode_format"] = value
        else:
            raise HTTPException(status_code=400, detail=f"episode_format must be one of {', '.join(keys) or '(none for this channel)'}.")
    if session_format.is_shorts_first(project):
        session_format.refresh_recording_script(project)
    else:
        # Recorded as the long video only: the teleprompter no longer offers the session.
        project.assets.pop("recording_script", None)
    project.save()
    return _view(project)


def _channels_state() -> Dict[str, Any]:
    out: Dict[str, Any] = {"channels": session_format.all_channel_defaults(), "episode_formats": {}, "next_format": {},
                           "pinned_format": {}, "locked_format": {}}
    # Every channel with formats, not only the session ones: the Projects page labels
    # a TheTallStoryteller project "Detective" / "Comedy" / "Crime" from this too.
    for channel in dict.fromkeys([*session_format.SESSION_CHANNELS, *longform_nightly.FORMAT_ROTATION]):
        formats = longform_nightly.formats_for(channel)
        if not formats:
            continue
        out["episode_formats"][channel] = [{"key": f["key"], "label": f["label"]} for f in formats]
        nxt = longform_nightly.next_format(channel)
        out["next_format"][channel] = nxt[0] if nxt else None
        out["pinned_format"][channel] = longform_nightly._pinned_format(channel)
        out["locked_format"][channel] = longform_nightly._locked_format(channel)
    return out


@router.get("/api/channel_formats")
def get_channel_formats():
    return _channels_state()


@router.put("/api/channel_formats/{channel}")
def put_channel_format(channel: str, payload: ChannelFormatSchema):
    from app.services.writing_style import canonical_channel
    name = canonical_channel(channel)
    if name not in session_format.SESSION_CHANNELS:
        raise HTTPException(status_code=400, detail=f"Unknown channel: {channel}. "
                                                     f"One of {', '.join(session_format.SESSION_CHANNELS)}.")
    provided = payload.model_dump(exclude_unset=True)
    if provided.get("face_layout") is not None and provided["face_layout"] not in session_format.FACE_LAYOUTS:
        raise HTTPException(status_code=400, detail=f"face_layout must be one of {', '.join(session_format.FACE_LAYOUTS)}.")
    if provided.get("shorts_count") is not None and provided["shorts_count"] not in session_format.SHORTS_COUNTS:
        raise HTTPException(status_code=400, detail="shorts_count must be 3 or 4.")
    if "next_format" in provided:
        key = provided.pop("next_format")
        keys = [f["key"] for f in longform_nightly.formats_for(name)]
        if key and key not in keys:
            raise HTTPException(status_code=400, detail=f"next_format must be one of {', '.join(keys) or '(none)'}.")
        longform_nightly.set_pinned_format(name, key or None)
    if "lock_format" in provided:
        key = provided.pop("lock_format")
        keys = [f["key"] for f in longform_nightly.formats_for(name)]
        if key and key not in keys:
            raise HTTPException(status_code=400, detail=f"lock_format must be one of {', '.join(keys) or '(none)'}.")
        longform_nightly.set_locked_format(name, key or None)
    if provided:
        session_format.set_channel_defaults(name, provided)
    return _channels_state()
