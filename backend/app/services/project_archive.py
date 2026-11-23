"""
Archiving projects (2026-10-22). 52 of 57 projects were "in progress" and
most were abandoned, so the Projects page was unusable. A project can be
archived by hand (`POST /api/projects/{id}/archive`) and the nightly sweep
archives, by itself, any active project nobody touched for `days` days that
is not in the production queue and not a session child of a live parent.
Archived projects keep their files and come back with one click.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.models.project import Project
from core.paths import PROJECTS_DIR

logger = logging.getLogger("buzzcaf_ai.project_archive")

DEFAULT_DAYS = 14
LIVE_QUEUE = ("queued", "running", "awaiting_review", "paused", "awaiting_plan_review", "awaiting_cut_review",
              "awaiting_effects_review")


def set_archived(project_id: str, archived: bool, reason: str = "user") -> Dict[str, Any]:
    project = Project.load(project_id)
    if archived:
        if project.status != "archived":
            project.metadata["archived_from"] = project.status
            project.metadata["archived_at"] = datetime.now().isoformat(timespec="seconds")
            project.metadata["archived_by"] = reason
            project.status = "archived"
    else:
        project.status = project.metadata.pop("archived_from", None) or "active"
        project.metadata.pop("archived_at", None)
        project.metadata.pop("archived_by", None)
    project.save()
    return project.to_dict()


def _queued_ids() -> set:
    try:
        from app.services import produce_queue
        return {i.get("project_id") for i in produce_queue.snapshot().get("items", []) if i.get("status") in LIVE_QUEUE}
    except Exception:  # noqa: BLE001
        return set()


def _last_touch(project: Project) -> datetime:
    """The newest of updated_at, the last step's end, and the project.json mtime."""
    stamps: List[datetime] = []
    for value in (project.updated_at, project.created_at):
        try:
            stamps.append(datetime.fromisoformat(str(value)))
        except (TypeError, ValueError):
            pass
    for step in project.steps_history[-3:]:
        for attr in ("completed_at", "started_at"):
            try:
                stamps.append(datetime.fromisoformat(str(getattr(step, attr, "") or "")))
            except (TypeError, ValueError):
                pass
    try:
        stamps.append(datetime.fromtimestamp(os.path.getmtime(os.path.join(project.get_project_dir(), "project.json"))))
    except OSError:
        pass
    return max(stamps) if stamps else datetime.now()


# The rules (2026-10-26: 80 projects on the list, 54 of them from four days of
# nightly runs, and the 14-day sweep never ran -- the nightly tasks each run
# one part, and the sweep only ran when everything did). Days per rule, in
# config `archive_rules`; 0 turns a rule off. A script ready to record
# ("completed") is kept the longest: it is the work waiting for the creator.
DEFAULT_RULES = {
    "enabled": True,          # the nightly sweep applies them by itself
    "stale_days": 7,          # in progress, nobody touched it
    "failed_days": 2,         # its last step failed and nobody retried it
    "duplicate_days": 1,      # an older copy of the same title on the same channel
    "completed_days": 21,     # script ready, never recorded
}


def rules() -> Dict[str, Any]:
    try:
        from integrations.llm import load_config
        saved = load_config().get("archive_rules") or {}
        legacy = load_config().get("archive_after_days")
    except Exception:  # noqa: BLE001
        saved, legacy = {}, None
    out = dict(DEFAULT_RULES)
    if legacy and "stale_days" not in saved:
        out["stale_days"] = int(legacy)
    for k, v in saved.items():
        if k in DEFAULT_RULES:
            out[k] = bool(v) if k == "enabled" else max(0, int(v))
    return out


def save_rules(changes: Dict[str, Any]) -> Dict[str, Any]:
    from integrations.llm import load_config, save_config
    cfg = load_config()
    current = rules()
    for k, v in changes.items():
        if k in DEFAULT_RULES and v is not None:
            current[k] = bool(v) if k == "enabled" else max(0, min(365, int(v)))
    cfg["archive_rules"] = current
    save_config(cfg)
    return current


def _norm_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def candidates(days: Optional[int] = None, rule_set: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Projects the rules would archive now, each with its reason. Nothing in
    the production queue, nothing pinned (`keep`), and no session parent whose
    Shorts are still being worked on. `days` (older callers) sets the stale rule."""
    if not os.path.isdir(PROJECTS_DIR):
        return []
    r = dict(rule_set or rules())
    if days:
        r["stale_days"] = int(days)
    now = datetime.now()
    queued = _queued_ids()
    projects: List[Project] = []
    for pid in os.listdir(PROJECTS_DIR):
        try:
            projects.append(Project.load(pid))
        except Exception:  # noqa: BLE001
            continue
    live_parents = set()
    for p in projects:
        if p.status not in ("archived", "completed"):
            parent = p.metadata.get("session_parent")
            if isinstance(parent, dict):
                parent = parent.get("id") or parent.get("project_id")
            if parent and (now - _last_touch(p)).days < max(1, r["stale_days"] or 7):
                live_parents.add(str(parent))

    # Duplicates: the same title on the same channel; the copy furthest along
    # (completed first, then the newest) stays.
    groups: Dict[tuple, List[Project]] = {}
    for p in projects:
        if p.status != "archived":
            groups.setdefault((p.brand, _norm_title(re.sub(r"\s+\d+$", "", p.name or ""))), []).append(p)
    older_copy = {}
    for (_, title), group in groups.items():
        if title and len(group) > 1:
            keep = max(group, key=lambda p: (p.status == "completed", _last_touch(p)))
            for p in group:
                if p.id != keep.id:
                    older_copy[p.id] = keep.name

    out = []
    for p in projects:
        if p.status == "archived" or p.id in queued or p.id in live_parents:
            continue
        if p.metadata.get("keep") or p.metadata.get("pinned"):
            continue
        idle = (now - _last_touch(p)).days
        last = p.steps_history[-1] if p.steps_history else None
        reason = None
        if r["duplicate_days"] and p.id in older_copy and idle >= r["duplicate_days"]:
            reason = f"older copy of '{older_copy[p.id]}'"
        elif r["failed_days"] and p.status != "completed" and last is not None \
                and getattr(last, "status", "") == "failed" and idle >= r["failed_days"]:
            reason = f"'{last.step_name}' failed {idle} days ago, never retried"
        elif r["completed_days"] and p.status == "completed" and idle >= r["completed_days"]:
            reason = f"script ready, not touched for {idle} days"
        elif r["stale_days"] and p.status != "completed" and idle >= r["stale_days"]:
            reason = f"untouched for {idle} days"
        if reason:
            out.append({"id": p.id, "name": p.name, "brand": p.brand, "current_step": p.current_step,
                        "status": p.status, "last_touch": _last_touch(p).isoformat(timespec="seconds"),
                        "days": idle, "reason": reason})
    out.sort(key=lambda row: row["last_touch"])
    return out


def sweep(days: Optional[int] = None, dry_run: bool = False) -> Dict[str, Any]:
    rows = candidates(days)
    archived = []
    if not dry_run:
        for row in rows:
            try:
                set_archived(row["id"], True, reason=f"auto: {row['reason']}")
                archived.append(row)
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not archive %s: %s", row["id"], exc)
    return {"rules": rules(), "candidates": rows, "archived": archived, "dry_run": dry_run,
            "at": datetime.now().isoformat(timespec="seconds")}


def bulk(ids: List[str], archived: bool = True, reason: str = "user") -> Dict[str, Any]:
    done, failed = [], []
    for pid in ids:
        try:
            set_archived(pid, archived, reason=reason)
            done.append(pid)
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": pid, "error": str(exc)[:200]})
    return {"done": done, "failed": failed}


def set_keep(project_id: str, keep: bool) -> Dict[str, Any]:
    """Pin a project so no rule ever archives it."""
    project = Project.load(project_id)
    if keep:
        project.metadata["keep"] = True
    else:
        project.metadata.pop("keep", None)
    project.save()
    return project.to_dict()
