"""The creator's own writing style, per channel (app/services/writing_style.py).

    GET    /api/style                          every channel: samples, profile built?
    GET    /api/style/{channel}                samples, profile, notes, measured numbers
    POST   /api/style/{channel}/samples        {title, text} -- a piece of his own writing
    POST   /api/style/{channel}/upload         multipart .txt/.md files of his writing
    DELETE /api/style/{channel}/samples/{id}   (id is "samples/<file>" or "recordings/<file>")
    POST   /api/style/{channel}/harvest        learn from every produced video's recording
    POST   /api/style/{channel}/build          StyleAnalyst writes the profile (~1 min)
    PUT    /api/style/{channel}/profile        {text} -- hand edits to the profile
    PUT    /api/style/{channel}/notes          {text} -- his own rules, never overwritten
    POST   /api/style/{channel}/check          {text} -- how close a draft is, and what to fix
    PUT    /api/style/{channel}/mode           {mode: "mine"|"agent"} -- the channel's default
    PUT    /api/style/projects/{id}/mode       {mode: "mine"|"agent"|null} -- one project's choice
    POST   /api/style/{channel}/styles         {name, copy_current} -- save a new style and select it
    PUT    /api/style/{channel}/styles/active  {id} -- write in this saved style
    PUT    /api/style/{channel}/styles/{id}    {name} -- rename it
    DELETE /api/style/{channel}/styles/{id}    remove a saved style (never the default)

Everything else acts on the channel's selected style.
"""

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services import writing_style

router = APIRouter(prefix="/api/style", tags=["writing-style"])


class SampleIn(BaseModel):
    title: str = ""
    text: str


class TextIn(BaseModel):
    text: str = ""


def _channel(channel: str) -> str:
    name = writing_style.canonical_channel(channel)
    if name not in writing_style.CHANNELS:
        raise HTTPException(status_code=404, detail=f"Unknown channel: {channel}")
    return name


@router.get("")
def channels():
    out = []
    for channel in writing_style.CHANNELS:
        samples = writing_style.list_samples(channel)
        view = writing_style.overview(channel) if samples else {"built_at": None, "stale": True}
        styles = writing_style.list_styles(channel)
        out.append({"channel": channel, "mode": writing_style.channel_mode(channel),
                    "story_standard": writing_style.standard_on(channel),
                    "style_name": next((s["name"] for s in styles if s["active"]), "Default"),
                    "styles": len(styles),
                    "written": sum(1 for s in samples if s["kind"] == "written"),
                    "spoken": sum(1 for s in samples if s["kind"] == "spoken"),
                    "built_at": view.get("built_at"), "stale": view.get("stale")})
    return {"channels": out}


@router.get("/{channel}")
def get_channel(channel: str):
    return writing_style.overview(_channel(channel))


@router.post("/{channel}/samples")
def add_sample(channel: str, body: SampleIn):
    name = _channel(channel)
    try:
        writing_style.add_sample(name, body.title, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return writing_style.overview(name)


@router.post("/{channel}/upload")
async def upload_samples(channel: str, files: List[UploadFile] = File(...)):
    name = _channel(channel)
    skipped = []
    for upload in files:
        if not (upload.filename or "").lower().endswith((".txt", ".md")):
            skipped.append(f"{upload.filename}: only .txt or .md")
            continue
        raw = await upload.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("utf-16", errors="ignore")
        try:
            writing_style.add_sample(name, (upload.filename or "").rsplit(".", 1)[0], text)
        except ValueError as exc:
            skipped.append(f"{upload.filename}: {exc}")
    return {**writing_style.overview(name), "skipped": skipped}


@router.delete("/{channel}/samples/{folder}/{file_name}")
def delete_sample(channel: str, folder: str, file_name: str):
    name = _channel(channel)
    try:
        if not writing_style.delete_sample(name, f"{folder}/{file_name}"):
            raise HTTPException(status_code=404, detail="No such sample.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return writing_style.overview(name)


@router.post("/{channel}/harvest")
def harvest(channel: str):
    name = _channel(channel)
    result = writing_style.harvest_projects(name)
    return {**writing_style.overview(name), "harvest": result}


@router.post("/{channel}/build")
def build(channel: str):
    name = _channel(channel)
    try:
        return writing_style.build_profile(name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.put("/{channel}/profile")
def save_profile(channel: str, body: TextIn):
    return writing_style.save_text(_channel(channel), "profile", body.text)


@router.put("/{channel}/notes")
def save_notes(channel: str, body: TextIn):
    return writing_style.save_text(_channel(channel), "notes", body.text)


class ModeIn(BaseModel):
    mode: Optional[str] = None


@router.put("/projects/{project_id}/mode")
def set_project_mode(project_id: str, body: ModeIn):
    """One project's choice: "mine", "agent", or null for the channel's default."""
    from core.models.project import Project

    if body.mode not in (None, *writing_style.MODES):
        raise HTTPException(status_code=400, detail=f"mode must be one of {', '.join(writing_style.MODES)} or null.")
    try:
        project = Project.load(project_id)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail="Project not found")
    if body.mode:
        project.metadata["writing_style"] = body.mode
    else:
        project.metadata.pop("writing_style", None)
    project.save()
    return {"project_id": project_id, "mode": body.mode,
            "effective": writing_style.mode_for(project.brand, project),
            "channel_default": writing_style.channel_mode(writing_style.canonical_channel(project.brand))}


@router.put("/{channel}/mode")
def set_channel_mode(channel: str, body: ModeIn):
    name = _channel(channel)
    try:
        writing_style.set_channel_mode(name, body.mode or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return writing_style.overview(name)


class StandardIn(BaseModel):
    on: bool


@router.put("/{channel}/standard")
def set_channel_standard(channel: str, body: StandardIn):
    name = _channel(channel)
    if not writing_style.has_standard(name):
        raise HTTPException(status_code=400, detail=f"{name} has no story standard file.")
    writing_style.set_standard(name, body.on)
    return writing_style.overview(name)


class StyleIn(BaseModel):
    name: str = ""
    copy_current: bool = False


class StylePick(BaseModel):
    id: str


def _styles(action):
    try:
        return action()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{channel}/styles")
def create_style(channel: str, body: StyleIn):
    """Save a new style (empty, or a copy of the one in use) and select it."""
    name = _channel(channel)
    return _styles(lambda: writing_style.create_style(name, body.name, body.copy_current))


@router.put("/{channel}/styles/active")
def select_style(channel: str, body: StylePick):
    name = _channel(channel)
    return _styles(lambda: writing_style.select_style(name, body.id))


@router.put("/{channel}/styles/{style_id}")
def rename_style(channel: str, style_id: str, body: StyleIn):
    name = _channel(channel)
    return _styles(lambda: writing_style.rename_style(name, style_id, body.name))


@router.delete("/{channel}/styles/{style_id}")
def delete_style(channel: str, style_id: str):
    name = _channel(channel)
    return _styles(lambda: writing_style.delete_style(name, style_id))


@router.post("/{channel}/check")
def check(channel: str, body: TextIn):
    name = _channel(channel)
    result = writing_style.check(body.text, name)
    if result is None:
        raise HTTPException(status_code=400, detail="Nothing to compare: add samples first, and check at least 60 words.")
    return result
