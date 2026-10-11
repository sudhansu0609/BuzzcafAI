"""Background music: a thin proxy onto BuzzEdit's /api/music (generation with
ACE-Step or Stable Audio Open, from a style preset or the genre/instrument/
mood/tempo builder; the licensed music library; track previews).

The music itself lives in BuzzEdit's library so the edit's A2 lane uses it
directly; the Studio only drives generation and browses. Every generation
hands the GPU to the music model and offloads all models when it is done
(BuzzEdit's runtime/gpu_handover policy).

BuzzEdit not running is not an error here: the first request that finds it
down starts it in the background (`produce_api.ensure_buzzedit_running`, the
same headless launcher the production pipeline uses), `/styles` answers with
the builder's vocabulary meanwhile so the page is usable at once, and
`/generate` waits for BuzzEdit before submitting.
"""
import logging
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from integrations.buzzedit_client import BuzzEditClient, BuzzEditUnavailable

logger = logging.getLogger("buzzcaf_ai.music_api")
router = APIRouter(prefix="/api/music", tags=["music"])

from integrations.music_catalog import FALLBACK_CATALOG  # noqa: E402

_start_lock = threading.Lock()
_start_state: Dict[str, Any] = {"starting": False, "error": ""}


def _start_buzzedit_in_background() -> None:
    """Launch BuzzEdit once; concurrent callers share the one attempt."""
    with _start_lock:
        if _start_state["starting"]:
            return
        _start_state.update(starting=True, error="")

    def run():
        from app.api.produce_api import ensure_buzzedit_running
        try:
            ensure_buzzedit_running(timeout=90.0)
        except Exception as exc:
            logger.warning("Could not start BuzzEdit for music: %s", exc)
            _start_state["error"] = str(exc)[:300]
        finally:
            _start_state["starting"] = False

    threading.Thread(target=run, name="music-buzzedit-start", daemon=True).start()


class GenerateMusicSchema(BaseModel):
    style: Optional[str] = None
    engine: str = "ace_step"
    music_genres: List[str] = []
    instruments: List[str] = []
    moods: List[str] = []
    bpm: Optional[int] = None
    variations: int = 2
    seconds: float = 120.0
    extra_tags: str = ""
    genre: Optional[str] = None


def _relay(resp):
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except Exception:
            detail = resp.text[:300]
        raise HTTPException(status_code=resp.status_code, detail=detail or "BuzzEdit error")
    return resp.json()


def _call(fn):
    import requests
    try:
        return _relay(fn())
    except (BuzzEditUnavailable, requests.RequestException) as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _offline(extra: Dict[str, Any]) -> Dict[str, Any]:
    _start_buzzedit_in_background()
    return {**extra, "buzzedit_online": False, "buzzedit_starting": _start_state["starting"],
            "buzzedit_error": _start_state["error"]}


@router.get("/styles")
def styles():
    client = BuzzEditClient()
    try:
        data = _call(lambda: client._get("/api/music/styles", timeout=(5, 15)))
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return _offline({**FALLBACK_CATALOG, "styles": [], "model_ready": False})
    # A BuzzEdit that predates the builder ignores its fields; say so.
    data["builder_supported"] = "engines" in data
    for key, value in FALLBACK_CATALOG.items():
        data.setdefault(key, value)
    data["buzzedit_online"] = True
    return data


@router.get("/library")
def library():
    client = BuzzEditClient()
    try:
        return _call(lambda: client._get("/api/music/library", timeout=(5, 30)))
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return _offline({"tracks": []})


@router.post("/generate")
def generate(payload: GenerateMusicSchema):
    from app.api.produce_api import ensure_buzzedit_running
    try:
        ensure_buzzedit_running(timeout=90.0)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BuzzEdit could not be started: {exc}")
    client = BuzzEditClient()
    return _call(lambda: client._post("/api/music/generate", payload.model_dump(), timeout=(5, 30)))


@router.post("/preview")
def preview(payload: GenerateMusicSchema):
    """The exact prompt a generation would send (BuzzEdit composes it)."""
    client = BuzzEditClient()
    return _call(lambda: client._post("/api/music/preview", payload.model_dump(), timeout=(5, 15)))


@router.get("/jobs/{job_id}")
def job(job_id: str):
    client = BuzzEditClient()
    return _call(lambda: client._get(f"/api/music/jobs/{job_id}", timeout=(5, 15)))


@router.post("/upload")
def upload(file: UploadFile = File(...), license: str = Form(...), label: str = Form("")):
    """Add your own track to BuzzEdit's library (`uploads/`), loudness-normalised
    so a level picked for it means the same as for any other track. The licence
    is required: the music guard never uses a file without one on record."""
    from app.api.produce_api import ensure_buzzedit_running
    try:
        ensure_buzzedit_running(timeout=90.0)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BuzzEdit could not be started: {exc}")
    client = BuzzEditClient()
    import requests
    files = {"file": (file.filename or "track", file.file, file.content_type or "application/octet-stream")}
    data = {"license": license, "label": label}
    return _call(lambda: requests.post(f"{client._base()}/api/music/upload", files=files, data=data,
                                       timeout=(5, 900)))


@router.delete("/file/{path:path}")
def delete_file(path: str):
    import requests
    client = BuzzEditClient()
    return _call(lambda: requests.delete(f"{client._base()}/api/music/file/{path}", timeout=(5, 30)))


@router.get("/file/{path:path}")
def file(path: str, download: bool = False):
    """Stream a library track for the <audio> preview, or as a download."""
    import requests
    client = BuzzEditClient()
    try:
        upstream = requests.get(f"{client._base()}/api/music/file/{path}", stream=True, timeout=(5, 60))
    except (BuzzEditUnavailable, requests.RequestException) as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if upstream.status_code != 200:
        upstream.close()
        raise HTTPException(status_code=upstream.status_code, detail="Track not found")
    headers = {}
    if download:
        from urllib.parse import quote
        name = path.rsplit("/", 1)[-1]
        headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(name)}"
    return StreamingResponse(upstream.iter_content(64 * 1024), headers=headers,
                             media_type=upstream.headers.get("content-type", "audio/wav"))
