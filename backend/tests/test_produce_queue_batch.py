"""`POST /api/produce/queue/batch` -- several videos of one channel queued in
one go: existing projects, new recordings (each a new project), or both."""
import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import produce_queue
from core.models.project import Project


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(produce_queue, "QUEUE_PATH", str(tmp_path / "produce_queue.json"))
    monkeypatch.setattr(produce_queue, "kick", lambda: None)  # queue only; never run the pipeline
    produce_queue.reset_for_tests()
    yield
    produce_queue.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def made():
    ids = []
    yield ids
    for pid in ids:
        try:
            shutil.rmtree(Project.load(pid).get_project_dir(), ignore_errors=True)
        except Exception:
            pass
        with produce_api._produce_lock:
            produce_api._produce_status.pop(pid, None)


def _recording(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"\0")
    return str(path)


def test_new_recordings_become_projects_queued_in_order(client, tmp_path, made):
    recs = [_recording(tmp_path, "morning_routine-take1.mp4"), _recording(tmp_path, "why I quit.mov")]
    res = client.post("/api/produce/queue/batch", json={
        "brand": "Life3Baje", "workflow_name": "life3baje_video",
        "items": [{"recording_path": recs[0]}, {"recording_path": recs[1], "title": "Why I Quit My Job"}],
    }).json()
    made.extend(r["project_id"] for r in res["results"] if r.get("project_id"))
    assert res["queued"] == 2
    assert [r["title"] for r in res["results"]] == ["morning routine take1", "Why I Quit My Job"]
    queued = [i for i in res["items"] if i["status"] == "queued"]
    assert [i["recording_path"] for i in queued] == recs
    assert Project.load(res["results"][0]["project_id"]).metadata["recording_path"] == recs[0]


def test_same_named_recordings_get_numbered(client, tmp_path, made):
    rec_a = _recording(tmp_path, "a.mp4")
    rec_b = _recording(tmp_path, "b.mp4")
    res = client.post("/api/produce/queue/batch", json={
        "brand": "Life3Baje", "workflow_name": "life3baje_video",
        "items": [{"recording_path": rec_a, "title": "Vlog"}, {"recording_path": rec_b, "title": "Vlog"}],
    }).json()
    made.extend(r["project_id"] for r in res["results"] if r.get("project_id"))
    assert [r["title"] for r in res["results"]] == ["Vlog", "Vlog Part 2"]


def test_existing_projects_use_their_remembered_recording(client, tmp_path, made):
    rec = _recording(tmp_path, "take.mp4")
    p = Project(id="batch_existing", name="Existing", brand="Life3Baje", workflow_name="life3baje_video")
    p.metadata["recording_path"] = rec
    p.save()
    made.append(p.id)
    res = client.post("/api/produce/queue/batch", json={"brand": "Life3Baje", "items": [{"project_id": p.id}]}).json()
    assert res["results"][0]["status"] == "queued"
    assert res["items"][0]["recording_path"] == rec


def test_bad_items_are_reported_and_the_rest_still_queue(client, tmp_path, made):
    rec = _recording(tmp_path, "good.mp4")
    other = Project(id="batch_other_channel", name="Other", brand="Raat3Baje", workflow_name="after_dark_narration")
    other.save()
    made.append(other.id)
    res = client.post("/api/produce/queue/batch", json={
        "brand": "Life3Baje", "workflow_name": "life3baje_video",
        "items": [{"recording_path": str(tmp_path / "missing.mp4")}, {"project_id": other.id},
                  {"recording_path": rec}],
    }).json()
    made.extend(r["project_id"] for r in res["results"] if r.get("project_id"))
    assert [r["status"] for r in res["results"]] == ["error", "error", "queued"]
    assert "not found" in res["results"][0]["error"]
    assert "Raat3Baje" in res["results"][1]["error"]
    assert res["queued"] == 1
