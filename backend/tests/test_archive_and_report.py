"""Archiving stale projects and the morning report (2026-10-22)."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services import nightly_report, project_archive
from core.models import project as project_model
from core.models.project import Project


@pytest.fixture
def projects(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(project_model, "PROJECTS_DIR", str(root), raising=False)
    monkeypatch.setattr(project_archive, "PROJECTS_DIR", str(root))
    monkeypatch.setattr(project_model, "_project_dir_for", lambda pid: str(root / pid), raising=False)
    import core.paths
    monkeypatch.setattr(core.paths, "PROJECTS_DIR", str(root))

    def make(pid, brand="Raat3Baje", status="active", days_old=0, meta=None):
        p = Project(id=pid, name=pid.replace("_", " "), brand=brand, workflow_name="wf", status=status, metadata=meta or {})
        p.save()
        stamp = datetime.now() - timedelta(days=days_old)
        data = json.loads((root / pid / "project.json").read_text(encoding="utf-8"))
        data["updated_at"] = data["created_at"] = stamp.isoformat()
        (root / pid / "project.json").write_text(json.dumps(data), encoding="utf-8")
        import os
        os.utime(root / pid / "project.json", (stamp.timestamp(), stamp.timestamp()))
        return p

    monkeypatch.setattr(project_archive, "_queued_ids", lambda: {"queued_old"})
    monkeypatch.setattr(project_archive, "rules", lambda: dict(project_archive.DEFAULT_RULES))
    return make


def test_only_stale_untouched_unqueued_projects_are_candidates(projects):
    projects("fresh", days_old=2)
    projects("old_active", days_old=20)
    projects("recent_done", status="completed", days_old=10)
    projects("queued_old", days_old=30)
    projects("old_kept", days_old=30, meta={"keep": True})
    projects("old_parent", days_old=30)
    projects("fresh_child", days_old=1, meta={"session_parent": {"id": "old_parent"}})
    ids = [c["id"] for c in project_archive.candidates(14)]
    assert ids == ["old_active"], ids


def test_rules_ready_scripts_late_failed_early_older_copies(projects):
    from core.models.project import StepExecution
    projects("old_done", status="completed", days_old=30)       # script ready, 30 days: archived (21)
    projects("young_done", status="completed", days_old=10)     # kept: the creator still has to record it
    failed = projects("failed_one", days_old=3)
    failed.steps_history.append(StepExecution(step_name="Shorts Scripts", agent_name="ShortsWriter", status="failed",
                                              started_at=datetime.now().isoformat()))
    failed.save()
    projects("Judges_House", status="completed", days_old=2)
    projects("Judges_House_2", days_old=2)                       # the same title again, behind: archived
    import os, json as _json
    for pid, days in (("failed_one", 3), ("Judges_House_2", 2)):  # save() touched them; age them again
        path = Path(project_archive.PROJECTS_DIR) / pid / "project.json"
        data = _json.loads(path.read_text(encoding="utf-8"))
        stamp = datetime.now() - timedelta(days=days)
        data["updated_at"] = data["created_at"] = stamp.isoformat()
        for h in data.get("steps_history") or []:
            h["started_at"] = h["completed_at"] = stamp.isoformat()
        path.write_text(_json.dumps(data), encoding="utf-8")
        os.utime(path, (stamp.timestamp(), stamp.timestamp()))
    got = {c["id"]: c["reason"] for c in project_archive.candidates()}
    assert set(got) == {"old_done", "failed_one", "Judges_House_2"}, got
    assert "script ready" in got["old_done"] and "failed" in got["failed_one"] and "older copy" in got["Judges_House_2"]


def test_bulk_and_keep(projects):
    projects("a", days_old=1)
    projects("b", days_old=1)
    out = project_archive.bulk(["a", "b", "missing"])
    assert out["done"] == ["a", "b"] and out["failed"][0]["id"] == "missing"
    assert Project.load("a").status == "archived"
    project_archive.set_keep("a", True)
    assert Project.load("a").metadata["keep"] is True


def test_sweep_archives_and_a_project_comes_back(projects):
    projects("old_active", days_old=20)
    out = project_archive.sweep(14, dry_run=True)
    assert [c["id"] for c in out["candidates"]] == ["old_active"] and out["archived"] == []
    assert Project.load("old_active").status == "active"
    out = project_archive.sweep(14)
    assert [a["id"] for a in out["archived"]] == ["old_active"]
    p = Project.load("old_active")
    assert p.status == "archived" and p.metadata["archived_from"] == "active" and "auto" in p.metadata["archived_by"]
    assert project_archive.candidates(14) == [], "archived projects are not candidates again"
    back = project_archive.set_archived("old_active", False)
    assert back["status"] == "active" and "archived_at" not in back["metadata"]


def test_the_report_reads_last_night_s_records(tmp_path, monkeypatch):
    nightly = tmp_path / "nightly"
    nightly.mkdir()
    monkeypatch.setattr(nightly_report, "NIGHTLY_DIR", nightly)
    monkeypatch.setattr(nightly_report, "REPORTS_DIR", nightly / "reports")
    empty = nightly_report.build()
    assert "No nightly run" in empty["headline"]
    (nightly / "last_run.json").write_text(json.dumps({
        "started_at": "2026-10-22T03:00:10", "finished_at": "2026-10-22T04:10:10", "scope": "all", "network": True,
        "tasks": [
            {"task": "shorts_daily", "seconds": 500, "built": [{"channel": "Raat3Baje", "title": "Guliga", "score": 85, "project_id": "p1"}],
             "skipped": [{"channel": "Life3Baje", "reason": "no candidate scored above 70"}]},
            {"task": "longform", "error": "LM Studio refused: context"},
            {"task": "audience", "seconds": 300, "done": [{"brand": "Raat3Baje", "videos": 8, "comments": 174, "findings": 12}],
             "saved": [{"brand": "Raat3Baje", "topic": "Gaurav Tiwari's death", "mentions": 4, "id": "t1"}], "failed": []},
            {"task": "archive", "archived": [{"brand": "Beyond3Baje", "name": "Old thing", "days": 21}]},
        ],
        "hibernate": {"hibernate": False, "reasons": ["someone is using the PC"]},
    }), encoding="utf-8")
    (nightly / "longform_status.json").write_text(json.dumps({"tasks": [
        {"channel": "Beyond3Baje", "stage": "waiting", "topic": "Dyatlov", "detail": "waiting at Visual Plan"}]}), encoding="utf-8")
    rep = nightly_report.write()
    assert rep["date"] == "2026-10-22"
    assert rep["headline"].startswith("1 video written, 1 viewer request saved, 1 problem")
    md = rep["markdown"]
    assert "## Problems" in md and "LM Studio refused" in md
    assert "**Guliga**" in md and "no candidate scored" in md
    assert "Gaurav Tiwari" in md and "Old thing" in md and "Dyatlov" in md and "Stayed awake" in md
    assert (nightly / "reports" / "2026-10-22.md").exists()
    assert nightly_report.latest()["from_file"] == "2026-10-22.json"
    assert nightly_report.list_reports()[0]["problems"] == 1


def test_the_routes_answer():
    from app.main import app
    client = TestClient(app)
    assert "headline" in client.get("/api/nightly/report").json()
    assert "reports" in client.get("/api/nightly/reports").json()
    body = client.get("/api/projects/archive/candidates?days=3650").json()
    assert body["days"] == 3650 and isinstance(body["candidates"], list)
    assert client.post("/api/projects/no-such-project/archive", json={"archived": True}).status_code == 404
