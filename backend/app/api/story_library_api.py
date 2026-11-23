"""
The Story Library (2026-10-23): horror stories by real writers, fetched in full
with their rights. See app/services/story_library.py.

    POST   /api/stories/search        {query, language?, author?, source?, limit?} -> job
    GET    /api/stories/jobs/{id}
    POST   /api/stories/fetch         {candidate} -> library entry
    GET    /api/stories/library       the index
    GET    /api/stories/library/{id}  meta + the first 3,000 characters
    DELETE /api/stories/library/{id}
    GET    /api/stories/rights?author=
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import story_library

router = APIRouter(prefix="/api/stories", tags=["Story library"])

PREVIEW_CHARS = 3000


class SearchSchema(BaseModel):
    query: str = ""
    language: Optional[str] = "any"
    author: Optional[str] = ""
    source: Optional[str] = "any"
    limit: Optional[int] = 8


class FetchSchema(BaseModel):
    candidate: Dict[str, Any]


@router.post("/search")
def search(payload: SearchSchema):
    if not (payload.query or "").strip() and not (payload.author or "").strip():
        raise HTTPException(status_code=400, detail="query or author is required")
    return story_library.start_job("search", story_library.search, payload.query,
                                   language=payload.language or "any", author=payload.author or "",
                                   source=payload.source or "any", limit=payload.limit or 8)


@router.get("/jobs/{job_id}")
def job(job_id: str):
    found = story_library.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown job")
    return found


@router.post("/fetch")
def fetch(payload: FetchSchema):
    try:
        return story_library.fetch(payload.candidate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/library")
def library():
    return {"entries": story_library.entries()}


@router.get("/library/{story_id}")
def library_entry(story_id: str):
    found = story_library.entry(story_id)
    if not found:
        raise HTTPException(status_code=404, detail="Unknown story")
    text = found.pop("text", "") or ""
    found["text_chars"] = len(text)
    found["text"] = text[:PREVIEW_CHARS]
    return found


@router.delete("/library/{story_id}")
def library_delete(story_id: str):
    if not story_library.delete(story_id):
        raise HTTPException(status_code=404, detail="Unknown story")
    return {"deleted": story_id}


@router.get("/rights")
def rights(author: str = ""):
    if not author.strip():
        raise HTTPException(status_code=400, detail="author is required")
    return story_library.rights_for(author)
