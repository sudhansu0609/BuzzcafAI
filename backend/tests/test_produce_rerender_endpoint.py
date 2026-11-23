"""`POST /api/projects/{id}/produce_video/rerender`: render the saved edit again on
BuzzEdit (after an eye-contact fix) through the queue's render stage."""
import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import produce_queue
from core.models.project import Project

PID = "rerender_endpoint_proj"


class _Immediate:
    def __init__(self, target=None, name=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(produce_queue, "QUEUE_PATH", str(tmp_path / "queue.json"))
    monkeypatch.setattr(produce_queue.threading, "Thread", _Immediate)
    monkeypatch.setattr(produce_queue, "AUTO_RETRY_DELAY_S", 0.0)
    produce_queue.reset_for_tests()
    yield
    produce_queue.reset_for_tests()


@pytest.fixture
def project():
    p = Project(id=PID, name="Rerender", brand="Raat3Baje", workflow_name="after_dark_narration")
    p.metadata["buzzedit_project_id"] = "be_1"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)
    with produce_api._produce_lock:
        produce_api._produce_status.pop(PID, None)


class FakeBuzzEdit:
    def __init__(self, status="presented"):
        self.status, self.enqueued = status, []

    def get_project(self, pid):
        return {"status": self.status}   # the summary carries no timeline

    def enqueue_rerender(self, pid):
        self.enqueued.append(pid)
        return {"job": {"id": "job_rr_1", "status": "pending"}}


def test_rerender_queues_the_render_stage_with_the_new_job(project, monkeypatch):
    be = FakeBuzzEdit()
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: be)
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **kw: {})
    ran = []
    monkeypatch.setattr(produce_api, "run_queue_item", lambda item: ran.append(item["resume_from"]) or "done")
    c = TestClient(app)
    r = c.post(f"/api/projects/{PID}/produce_video/rerender")
    assert r.status_code == 200, r.text
    assert r.json()["buzzedit_job_id"] == "job_rr_1" and be.enqueued == ["be_1"]
    assert Project.load(PID).metadata["buzzedit_job_id"] == "job_rr_1"
    assert ran == ["render"]


def test_rerender_refuses_without_a_finished_edit(project, monkeypatch):
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: FakeBuzzEdit(status="draft"))
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **kw: {})
    c = TestClient(app)
    assert c.post(f"/api/projects/{PID}/produce_video/rerender").status_code == 409
    p = Project.load(PID)
    p.metadata.pop("buzzedit_project_id")
    p.save()
    assert c.post(f"/api/projects/{PID}/produce_video/rerender").status_code == 409
