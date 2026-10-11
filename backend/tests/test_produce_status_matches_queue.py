"""The project panel's produce status says what its queue item says."""
from app.api import produce_api


def _item(status, **kw):
    return {"id": "q1", "project_id": "p", "status": status, "resume_from": "render", **kw}


def test_a_retried_run_no_longer_shows_the_old_failure():
    status = {"state": "failed", "error": "ffmpeg exit 1", "message": "Failed"}
    produce_api._align_with_queue(status, _item("running", message="Rendering"))
    assert status["state"] == "running" and status["error"] is None


def test_paused_and_queued_use_the_queue_panel_wording():
    paused = {"state": "running"}
    produce_api._align_with_queue(paused, _item("paused"))
    assert paused == {**paused, "state": "paused", "message": "Paused. Resumes at render."}
    queued = {"state": "idle"}
    produce_api._align_with_queue(queued, _item("queued"))
    assert queued["state"] == "queued" and "picks up at render" in queued["message"]


def test_a_failure_survives_a_studio_restart():
    status = {"state": "idle"}
    produce_api._align_with_queue(status, _item("failed", error="BuzzEdit render job failed"))
    assert status["state"] == "failed" and status["error"] == "BuzzEdit render job failed"


def test_a_newer_run_is_not_overwritten_by_an_old_finished_item():
    status = {"state": "running", "message": "Transcribing"}
    produce_api._align_with_queue(status, _item("failed", error="old"))
    assert status["state"] == "running" and status["message"] == "Transcribing"


def test_the_queue_view_carries_the_same_message(monkeypatch):
    item = _item("paused")
    monkeypatch.setattr(produce_api.produce_queue, "snapshot",
                        lambda: {"paused": False, "worker_active": False, "items": [dict(item)]})
    view = produce_api._queue_view()
    status = {"state": "idle"}
    produce_api._align_with_queue(status, item)
    assert view["items"][0]["message"] == status["message"]


def test_a_resumed_stage_waits_for_buzzedit_before_using_it(monkeypatch):
    # A resume right after a Studio restart used to hit BuzzEdit while it was
    # still booting and fail in seconds with "not reachable".
    calls = []
    monkeypatch.setattr(produce_api, "_set_status", lambda *a, **k: None)
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **k: calls.append("ensure") or {})
    monkeypatch.setattr(produce_api, "_reattach_render", lambda *a: calls.append("render"))
    produce_api.run_queue_item(_item("queued"))
    assert calls == ["ensure", "render"]
