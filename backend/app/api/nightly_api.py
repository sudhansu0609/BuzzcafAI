"""
The morning report and the project archive (2026-10-22).

    GET  /api/nightly/report            the newest report (built now if none is written)
    GET  /api/nightly/report/{date}
    GET  /api/nightly/reports           the list
    POST /api/nightly/report/rebuild    write it again from the records on disk
    GET  /api/projects/archive/candidates[?days=14]   what the rules would archive, with the reason
    GET  /api/projects/archive/rules / POST {enabled, stale_days, failed_days, duplicate_days, completed_days}
    POST /api/projects/archive/sweep    {days?, dry_run?}
    POST /api/projects/archive/bulk     {ids: [...], archived: true|false}
    POST /api/projects/{id}/archive     {archived: true|false}
    POST /api/projects/{id}/keep        {keep: true|false}  never archived by a rule
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services import nightly_report, project_archive

router = APIRouter(tags=["Nightly report and archive"])


@router.get("/api/nightly/report")
def report():
    return nightly_report.latest()


@router.get("/api/nightly/reports")
def reports():
    return {"reports": nightly_report.list_reports()}


@router.get("/api/nightly/report/{date}")
def report_for(date: str):
    found = nightly_report.get(date)
    if not found:
        raise HTTPException(status_code=404, detail="No report for that date")
    return found


@router.post("/api/nightly/report/rebuild")
def rebuild():
    return nightly_report.write()


class SweepSchema(BaseModel):
    days: Optional[int] = None
    dry_run: Optional[bool] = False


class ArchiveSchema(BaseModel):
    archived: bool = True


class BulkArchiveSchema(BaseModel):
    ids: List[str]
    archived: bool = True


class KeepSchema(BaseModel):
    keep: bool = True


class RulesSchema(BaseModel):
    enabled: Optional[bool] = None
    stale_days: Optional[int] = None
    failed_days: Optional[int] = None
    duplicate_days: Optional[int] = None
    completed_days: Optional[int] = None


@router.get("/api/projects/archive/candidates")
def archive_candidates(days: Optional[int] = None):
    """What the rules (or, with `days`, the old untouched-for-N-days rule) would archive now."""
    return {"days": days, "rules": project_archive.rules(),
            "candidates": project_archive.candidates(max(1, min(365, days)) if days else None)}


@router.get("/api/projects/archive/rules")
def archive_rules():
    return project_archive.rules()


@router.post("/api/projects/archive/rules")
def save_archive_rules(payload: RulesSchema):
    return project_archive.save_rules(payload.model_dump(exclude_none=True))


@router.post("/api/projects/archive/bulk")
def archive_bulk(payload: BulkArchiveSchema):
    return project_archive.bulk(payload.ids, payload.archived)


@router.post("/api/projects/{project_id}/keep")
def keep_project(project_id: str, payload: KeepSchema):
    try:
        return project_archive.set_keep(project_id, payload.keep)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")


@router.post("/api/projects/archive/sweep")
def archive_sweep(payload: SweepSchema):
    return project_archive.sweep(payload.days, dry_run=bool(payload.dry_run))


@router.post("/api/projects/{project_id}/archive")
def archive_project(project_id: str, payload: ArchiveSchema):
    try:
        return project_archive.set_archived(project_id, payload.archived)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found.")
