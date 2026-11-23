"""app/services/needs_you.py: one list of everything waiting on the creator."""
import json
from datetime import datetime, timedelta

import pytest

from app.services import needs_you


def _write(root, pid, **data):
    d = root / pid
    d.mkdir(parents=True)
    data.setdefault("name", pid)
    data.setdefault("brand", "Beyond3Baje")
    (d / "project.json").write_text(json.dumps({"id": pid, **data}), encoding="utf-8")


@pytest.fixture
def projects(tmp_path, monkeypatch):
    import core.paths
    from app.services import auto_story, produce_queue, studio_director
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(core.paths, "PROJECTS_DIR", str(root))
    monkeypatch.setattr(auto_story, "_live", {})
    queued = set()
    monkeypatch.setattr(produce_queue, "active_item_for", lambda pid: {"id": "q"} if pid in queued else None)
    approvals = []
    monkeypatch.setattr(studio_director, "list_approvals", lambda state=None: approvals)
    return root, queued, approvals


def _kinds(result):
    return [(i["kind"], i.get("project_id")) for i in result["items"]]


def test_every_kind_is_listed_most_urgent_first(projects):
    root, _, approvals = projects
    _write(root, "voice", workflow_name="beyond3baje_documentary", current_step="Voice Recording")
    _write(root, "step", current_step="Script Writing",
           steps_history=[{"step_name": "Script Writing", "status": "paused_for_approval"}])
    _write(root, "gate", current_step="Produce", metadata={"produce_gate": {"stage": "plan_review"}})
    _write(root, "publish", metadata={"auto_story": {"state": "packaged", "review": {"state": "needs_review"}}})
    _write(root, "short", workflow_name="shorts_ready", current_step="Ready to record")
    _write(root, "done", status="completed", current_step="Voice Recording")
    approvals.append({"id": "a1", "item": {"action": "fix_set_config", "why": "context too small"}})

    r = needs_you.collect()
    assert _kinds(r) == [("publish", "publish"), ("step_approval", "step"), ("review_gate", "gate"),
                         ("director", None), ("voice", "voice"), ("shorts_record", None)]
    assert r["decisions"] == 5
    gate = r["items"][2]
    assert gate["actions"][0]["path"] == "/api/projects/gate/produce_video/continue"
    assert gate["actions"][0]["body"] == {"stage": "plan_review"}
    assert r["items"][3]["title"] == "Fix set config"
    assert r["items"][-1]["count"] == 1


def test_work_in_progress_is_not_waiting_on_him(projects):
    root, queued, _ = projects
    fresh = datetime.now().isoformat(timespec="seconds")
    stale = (datetime.now() - timedelta(hours=9)).isoformat(timespec="seconds")
    for pid in ("in_queue", "narrating", "died_narrating"):
        _write(root, pid, workflow_name="beyond3baje_documentary", current_step="Voice Recording")
    queued.add("in_queue")
    for pid, at in (("narrating", fresh), ("died_narrating", stale)):
        path = root / pid / "project.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["metadata"] = {"auto_story": {"state": "narration", "updated_at": at}}
        path.write_text(json.dumps(data), encoding="utf-8")

    # Queued or narrating now: not waiting. A narration that stopped hours ago is.
    assert _kinds(needs_you.collect()) == [("voice", "died_narrating")]
