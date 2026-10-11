"""Eye-contact correction driven from the Studio, done by BuzzEdit: the setup is
saved on the project, the correction runs against the imported recording, and
a resumed production does not redo it. No real BuzzEdit call is made."""
import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import eye_contact_api
from app.main import app
from core.models.project import Project

PID = "eye_contact_test_proj"


@pytest.fixture
def project():
    p = Project(id=PID, name="Eye Test", brand="Raat3Baje", workflow_name="after_dark_narration")
    p.metadata["buzzedit_project_id"] = "be_1"
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)


class FakeBuzzEdit:
    def __init__(self):
        self.started = []

    def eye_contact_available(self):
        return {"available": True, "reason": ""}

    def get_project(self, pid):
        return {"source_video": r"C:\be\rec.mp4",
                "media_pool": [{"id": "m_audio", "kind": "audio", "path": r"C:\be\music.wav"},
                               {"id": "m_rec", "kind": "video", "path": r"C:\BE\rec.mp4"}]}

    def start_eye_contact(self, pid, media_id, setup):
        self.started.append((pid, media_id, setup))
        return "job1"

    def eye_contact_status(self, job_id):
        return {"status": "completed", "progress": 1.0, "stage": "Done", "result": {"frames": 10}}


def test_the_setup_is_saved_on_the_project_and_null_falls_back(project):
    c = TestClient(app)
    r = c.put(f"/api/projects/{PID}/eye_contact",
              json={"enabled": True, "prompter_side": "right", "angle_deg": 12.5, "aim_deg": -2})
    assert r.status_code == 200
    assert r.json()["setup"] == {"enabled": True, "prompter_side": "right", "angle_deg": 12.5, "aim_deg": -2.0}
    r = c.put(f"/api/projects/{PID}/eye_contact", json={"angle_deg": None})
    assert "angle_deg" not in r.json()["setup"]
    assert c.put(f"/api/projects/{PID}/eye_contact", json={"angle_deg": 90}).status_code == 422
    assert c.get(f"/api/projects/{PID}/eye_contact").json()["setup"]["prompter_side"] == "right"


def test_correction_targets_the_recording_and_is_not_redone_on_resume(project):
    project.metadata["eye_contact"] = {"enabled": True, "prompter_side": "left", "angle_deg": 10.0}
    project.save()
    be = FakeBuzzEdit()
    stages = []
    result = eye_contact_api.correct_recording(PID, be, "be_1", lambda s, f: stages.append((s, f)))
    # The Studio default aim (-10 deg, toward the viewer's left) goes along unless the project sets one.
    assert be.started == [("be_1", "m_rec", {"aim_deg": -10.0, "prompter_side": "left", "angle_deg": 10.0})]
    assert result["report"] == {"frames": 10} and stages
    # A resumed production with the same setup skips the GPU job...
    eye_contact_api.correct_recording(PID, be, "be_1")
    assert len(be.started) == 1
    # ...a changed setup, or "Fix now", runs it again.
    p = Project.load(PID)
    p.metadata["eye_contact"]["angle_deg"] = 14.0
    p.save()
    eye_contact_api.correct_recording(PID, be, "be_1")
    eye_contact_api.correct_recording(PID, be, "be_1", force=True)
    assert len(be.started) == 3


def test_a_failed_job_raises(project):
    be = FakeBuzzEdit()
    be.eye_contact_status = lambda job_id: {"status": "failed", "error": "no face found"}
    with pytest.raises(RuntimeError, match="no face found"):
        eye_contact_api.correct_recording(PID, be, "be_1", force=True)


def test_a_status_poll_that_times_out_does_not_abandon_the_job(project, monkeypatch):
    # BuzzEdit's loop stalls while the corrected file is finalised; one slow
    # status reply must not give up on a job that completes a moment later.
    monkeypatch.setattr(eye_contact_api, "POLL_S", 0.0)
    be = FakeBuzzEdit()
    replies = iter([{"status": "running", "progress": 0.9}, None, None,
                    {"status": "completed", "progress": 1.0, "result": {"frames": 10}}])

    def status(job_id):
        reply = next(replies)
        if reply is None:
            raise eye_contact_api.BuzzEditUnavailable("Read timed out. (read timeout=15)")
        return reply

    be.eye_contact_status = status
    result = eye_contact_api.correct_recording(PID, be, "be_1", force=True)
    assert result["report"] == {"frames": 10}
    assert Project.load(PID).metadata["eye_contact_applied"]["report"] == {"frames": 10}


def test_buzzedit_silent_past_the_grace_period_fails(project, monkeypatch):
    monkeypatch.setattr(eye_contact_api, "POLL_S", 0.0)
    monkeypatch.setattr(eye_contact_api, "STATUS_GRACE_S", -1.0)
    be = FakeBuzzEdit()

    def status(job_id):
        raise eye_contact_api.BuzzEditUnavailable("connection refused")

    be.eye_contact_status = status
    with pytest.raises(RuntimeError, match="stopped answering"):
        eye_contact_api.correct_recording(PID, be, "be_1", force=True)


def test_run_needs_a_buzzedit_recording(project):
    project.metadata.pop("buzzedit_project_id")
    project.save()
    r = TestClient(app).post(f"/api/projects/{PID}/eye_contact/run")
    assert r.status_code == 400 and "start video production" in r.json()["detail"]


def test_a_stopped_buzzedit_is_started_before_correcting(project, monkeypatch):
    from app.api import produce_api
    from integrations.buzzedit_client import BuzzEditUnavailable
    project.metadata["eye_contact"] = {"enabled": True}
    project.save()
    be = FakeBuzzEdit()
    calls = {"n": 0, "started": 0}
    real = be.eye_contact_available

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise BuzzEditUnavailable("not running")
        return real()

    be.eye_contact_available = flaky
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running",
                        lambda **kw: calls.__setitem__("started", calls["started"] + 1) or {})
    eye_contact_api.correct_recording(PID, be, "be_1", force=True)
    assert calls["started"] == 1 and len(be.started) == 1


def test_keep_alive_starts_buzzedit_only_when_enabled(monkeypatch):
    from app.services import buzzedit_keepalive as ka
    from app.api import produce_api
    from integrations import buzzedit_client
    started = []
    monkeypatch.setattr(buzzedit_client.BuzzEditClient, "health", lambda self: None)
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **kw: started.append(1) or {})
    monkeypatch.setattr(ka, "enabled", lambda: False)
    assert ka.check_once() is False and not started
    monkeypatch.setattr(ka, "enabled", lambda: True)
    assert ka.check_once() is True and started == [1]


def test_the_up_down_aim_is_saved_and_sent_to_buzzedit(project):
    c = TestClient(app)
    r = c.put(f"/api/projects/{PID}/eye_contact", json={"enabled": True, "pitch_deg": 2})
    assert r.status_code == 200 and r.json()["setup"]["pitch_deg"] == 2.0
    assert c.put(f"/api/projects/{PID}/eye_contact", json={"pitch_deg": 30}).status_code == 422
    be = FakeBuzzEdit()
    eye_contact_api.correct_recording(PID, be, "be_1")
    assert be.started[0][2]["pitch_deg"] == 2.0
