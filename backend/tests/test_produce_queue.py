"""
The video-production queue (`app/services/produce_queue.py`) and its HTTP
surface in `app/api/produce_api.py`: one video at a time across channels,
cooperative pause at checkpoints, resume/retry from the saved checkpoint,
restart from scratch, cancel, a paused queue, and restart recovery.

The pipeline itself is replaced by a fake `produce_api.run_queue_item`, and
the worker thread runs synchronously, so nothing touches BuzzEdit or an LLM.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import produce_queue
from core.models.project import Project


#: The real wait, kept before the fixture below stubs it on the module.
_REAL_AWAIT_RELOAD = produce_queue._await_buzzedit_reload


class _Immediate:
    def __init__(self, target=None, name=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(produce_queue, "QUEUE_PATH", str(tmp_path / "produce_queue.json"))
    monkeypatch.setattr(produce_queue.threading, "Thread", _Immediate)
    monkeypatch.setattr(produce_queue, "AUTO_RETRY_DELAY_S", 0.0)
    monkeypatch.setattr(produce_queue, "_await_buzzedit_reload", lambda: None)
    produce_queue.reset_for_tests()
    yield
    produce_queue.reset_for_tests()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def projects():
    made = []
    for pid, brand in (("queue_proj_a", "Life3Baje"), ("queue_proj_b", "Khayal3Baje")):
        p = Project(id=pid, name=pid, brand=brand, workflow_name="life3baje_video")
        p.save()
        made.append(p)
    yield made
    for p in made:
        shutil.rmtree(p.get_project_dir(), ignore_errors=True)
        with produce_api._produce_lock:
            produce_api._produce_status.pop(p.id, None)


def _fake_pipeline(monkeypatch, checkpoints=("transcribe", "plan", "finalize"), fail_at=None, calls=None):
    """Walks the real checkpoint hooks, so pause/cancel requests are honoured
    exactly where the real pipeline would honour them."""
    calls = calls if calls is not None else []

    def run(item):
        calls.append((item["project_id"], item["resume_from"]))
        order = ["start", *checkpoints]
        begin = order.index(item["resume_from"]) if item["resume_from"] in order else 0
        for point in order[begin + 1:]:
            if point == fail_at:
                raise RuntimeError(f"boom at {point}")
            produce_queue.checkpoint(item["project_id"], point)
            hook = getattr(run, "after_checkpoint", None)
            if hook:
                hook(item, point)
        return "done"

    monkeypatch.setattr(produce_api, "run_queue_item", run)
    return run, calls


def _add(project, **kw):
    return produce_queue.add(project.id, brand=project.brand, title=project.name, recording_path="C:/rec.mp4",
                             settings_override=None, mode="record_first", precut=False, **kw)


def _status(item_id):
    return produce_queue.get(item_id)["status"]


def test_items_from_different_channels_run_in_order(monkeypatch, projects):
    _, calls = _fake_pipeline(monkeypatch)
    produce_queue.set_paused(True)
    a, b = _add(projects[0]), _add(projects[1])
    produce_queue.set_paused(False)
    assert [c[0] for c in calls] == ["queue_proj_a", "queue_proj_b"]
    assert _status(a["id"]) == _status(b["id"]) == "done"


def test_a_project_cannot_be_queued_twice(monkeypatch, projects):
    produce_queue.set_paused(True)
    _add(projects[0])
    with pytest.raises(ValueError):
        _add(projects[0])


def test_paused_queue_holds_new_work(monkeypatch, projects):
    _, calls = _fake_pipeline(monkeypatch)
    produce_queue.set_paused(True)
    item = _add(projects[0])
    assert calls == [] and _status(item["id"]) == "queued"
    produce_queue.set_paused(False)
    assert _status(item["id"]) == "done"


def test_pausing_a_running_item_stops_at_the_next_checkpoint_and_resumes_there(monkeypatch, projects):
    run, calls = _fake_pipeline(monkeypatch)

    def pause_once(item, point):
        if point == "transcribe" and item["resume_from"] == "start":
            produce_queue.pause(item["id"])

    run.after_checkpoint = pause_once
    item = _add(projects[0])
    got = produce_queue.get(item["id"])
    assert got["status"] == "paused"
    assert got["resume_from"] == "plan"  # paused at the checkpoint after transcribe

    run.after_checkpoint = None
    produce_queue.resume(item["id"])
    assert calls[-1] == ("queue_proj_a", "plan")
    assert _status(item["id"]) == "done"


def test_pausing_a_queued_item_skips_it_until_resumed(monkeypatch, projects):
    _, calls = _fake_pipeline(monkeypatch)
    produce_queue.set_paused(True)
    a, b = _add(projects[0]), _add(projects[1])
    produce_queue.pause(a["id"])
    produce_queue.set_paused(False)
    assert [c[0] for c in calls] == ["queue_proj_b"]
    assert _status(a["id"]) == "paused"
    produce_queue.resume(a["id"])
    assert _status(a["id"]) == "done"


def test_a_render_cannot_be_paused(monkeypatch, projects):
    run, _ = _fake_pipeline(monkeypatch, checkpoints=("transcribe", "plan", "finalize", "render"))
    seen = {}

    def try_pause(item, point):
        if point == "render":
            with pytest.raises(ValueError):
                produce_queue.pause(item["id"])
            seen["tried"] = True

    run.after_checkpoint = try_pause
    item = _add(projects[0])
    assert seen["tried"] and _status(item["id"]) == "done"


def test_cancel_a_running_item_at_its_next_checkpoint(monkeypatch, projects):
    run, _ = _fake_pipeline(monkeypatch)
    run.after_checkpoint = lambda item, point: point == "transcribe" and produce_queue.cancel(item["id"])
    item = _add(projects[0])
    assert _status(item["id"]) == "cancelled"


def test_failed_item_retries_from_its_last_checkpoint(monkeypatch, projects):
    """A stage that keeps failing is retried by itself from its checkpoint,
    AUTO_RETRY_ATTEMPTS runs in all; only then does the item stay failed, and
    a manual retry still picks up from the checkpoint."""
    _, calls = _fake_pipeline(monkeypatch, fail_at="finalize")
    item = _add(projects[0])
    got = produce_queue.get(item["id"])
    assert got["status"] == "failed" and "boom" in got["error"]
    assert got["checkpoint"] == "plan"
    assert got["attempts"] == produce_queue.AUTO_RETRY_ATTEMPTS
    # The first run started from scratch; every automatic retry resumed at the plan.
    assert calls[0] == ("queue_proj_a", "start")
    assert calls[1:] == [("queue_proj_a", "plan")] * (produce_queue.AUTO_RETRY_ATTEMPTS - 1)

    _fake_pipeline(monkeypatch, calls=calls)
    produce_queue.retry(item["id"])
    assert calls[-1] == ("queue_proj_a", "plan")
    assert _status(item["id"]) == "done"
    assert produce_queue.get(item["id"])["attempts"] == produce_queue.AUTO_RETRY_ATTEMPTS + 1


def test_a_passing_failure_is_retried_by_itself_and_finishes(monkeypatch, projects):
    """The 2026-10-20 case: BuzzEdit went away once during transcription. The
    item goes back in line on its own, resumes at the transcribe checkpoint
    and finishes without anyone pressing Retry."""
    failures = {"left": 1}

    def run(item):
        calls.append((item["project_id"], item["resume_from"]))
        if item["resume_from"] == "start":
            produce_queue.checkpoint(item["project_id"], "transcribe")
        if failures["left"]:
            failures["left"] -= 1
            raise RuntimeError("BuzzEdit no longer has the transcription job (restarted?)")
        produce_queue.checkpoint(item["project_id"], "plan")
        produce_queue.checkpoint(item["project_id"], "finalize")
        return "done"

    calls = []
    monkeypatch.setattr(produce_api, "run_queue_item", run)
    item = _add(projects[0])
    assert calls == [("queue_proj_a", "start"), ("queue_proj_a", "transcribe")]
    got = produce_queue.get(item["id"])
    assert got["status"] == "done"
    assert got["attempts"] == 2
    assert got["auto_retry"] is True


def test_a_cancelled_run_is_not_retried(monkeypatch, projects):
    def run(item):
        produce_queue.checkpoint(item["project_id"], "transcribe")
        produce_queue._update(item["id"], cancel_requested=True)
        raise RuntimeError("boom")

    monkeypatch.setattr(produce_api, "run_queue_item", run)
    item = _add(projects[0])
    got = produce_queue.get(item["id"])
    assert got["status"] == "failed" and got["attempts"] == 1


def test_restart_runs_from_scratch(monkeypatch, projects):
    _, calls = _fake_pipeline(monkeypatch, fail_at="plan")
    item = _add(projects[0])
    _fake_pipeline(monkeypatch, calls=calls)
    produce_queue.restart(item["id"])
    assert calls[-1] == ("queue_proj_a", "start")
    assert _status(item["id"]) == "done"


def test_a_run_cut_off_by_a_restart_goes_back_in_line_from_its_checkpoint(monkeypatch, projects):
    produce_queue.set_paused(True)
    item = _add(projects[0])
    produce_queue._update(item["id"], status="running", checkpoint="finalize", attempts=1)
    produce_queue.reset_for_tests()  # a fresh process reading the file

    got = produce_queue.get(item["id"])
    assert got["status"] == "queued" and "Interrupted" in got["error"]
    assert got["resume_from"] == "finalize" and got["auto_retry"] is True
    assert produce_queue.snapshot()["paused"] is True


def test_a_run_cut_off_after_its_last_attempt_stays_failed(monkeypatch, projects):
    produce_queue.set_paused(True)
    item = _add(projects[0])
    produce_queue._update(item["id"], status="running", checkpoint="finalize",
                          attempts=produce_queue.AUTO_RETRY_ATTEMPTS)
    produce_queue.reset_for_tests()
    got = produce_queue.get(item["id"])
    assert got["status"] == "failed" and "Interrupted" in got["error"]


def test_an_error_that_needs_the_creator_is_not_retried(monkeypatch, projects):
    from app.services.session_split import SessionSplitError

    def run(item):
        produce_queue.checkpoint(item["project_id"], "transcribe")
        raise SessionSplitError("the greeting was not found; set 'Long video starts at'")

    monkeypatch.setattr(produce_api, "run_queue_item", run)
    item = _add(projects[0])
    got = produce_queue.get(item["id"])
    assert got["status"] == "failed" and got["attempts"] == 1
    assert "greeting" in got["error"]


def test_move_reorders_waiting_items(projects):
    produce_queue.set_paused(True)
    a, b = _add(projects[0]), _add(projects[1])
    produce_queue.move(b["id"], "up")
    assert [i["id"] for i in produce_queue.snapshot()["items"]] == [b["id"], a["id"]]


# ------------------------------------------------------------------- HTTP


def test_produce_video_endpoint_queues_the_run(client, monkeypatch, projects):
    _, calls = _fake_pipeline(monkeypatch)
    resp = client.post(f"/api/projects/{projects[0].id}/produce_video", json={"recording_path": "C:/rec.mp4"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert calls == [("queue_proj_a", "start")]


def test_queue_endpoints_add_pause_resume_and_list(client, monkeypatch, projects):
    _fake_pipeline(monkeypatch)
    assert client.post("/api/produce/queue/paused", json={"paused": True}).json()["paused"] is True
    resp = client.post("/api/produce/queue", json={"project_id": projects[1].id, "recording_path": "C:/b.mp4"})
    assert resp.status_code == 200
    item_id = resp.json()["queue_item_id"]

    status = client.get(f"/api/projects/{projects[1].id}/produce_video/status").json()
    assert status["state"] == "queued" and status["queue_item"]["id"] == item_id

    assert client.post(f"/api/produce/queue/{item_id}/pause").status_code == 200
    body = client.post("/api/produce/queue/paused", json={"paused": False}).json()
    assert next(i for i in body["items"] if i["id"] == item_id)["status"] == "paused"

    body = client.post(f"/api/produce/queue/{item_id}/resume").json()
    assert next(i for i in body["items"] if i["id"] == item_id)["status"] == "done"


def test_queue_action_errors_are_409(client, monkeypatch, projects):
    _fake_pipeline(monkeypatch)
    item = _add(projects[0])  # runs straight to done
    assert client.post(f"/api/produce/queue/{item['id']}/retry").status_code == 409
    assert client.post(f"/api/produce/queue/{item['id']}/bogus").status_code == 404
    assert client.post("/api/produce/queue/nope/pause").status_code == 404


def test_clear_finished_keeps_failed_items(client, monkeypatch, projects):
    _fake_pipeline(monkeypatch)
    _add(projects[0])
    _fake_pipeline(monkeypatch, fail_at="plan")
    failed = _add(projects[1])
    body = client.post("/api/produce/queue/clear_finished").json()
    assert body["removed"] == 1
    assert [i["id"] for i in body["items"]] == [failed["id"]]


def test_each_stage_is_timed(monkeypatch, projects):
    _fake_pipeline(monkeypatch)
    item = _add(projects[0])
    times = produce_queue.get(item["id"])["stage_times"]
    assert [t["stage"] for t in times] == ["start", "transcribe", "plan", "finalize"]
    assert all(t["outcome"] == "done" and t["finished_at"] and t["seconds"] is not None for t in times)


def test_a_paused_and_resumed_run_times_each_attempt(monkeypatch, projects):
    run, _ = _fake_pipeline(monkeypatch)
    run.after_checkpoint = lambda item, point: (point == "transcribe" and item["resume_from"] == "start"
                                                and produce_queue.pause(item["id"]))
    item = _add(projects[0])
    # Paused at the plan checkpoint: transcribe closed as paused, plan never opened.
    times = produce_queue.get(item["id"])["stage_times"]
    assert [(t["stage"], t["outcome"]) for t in times] == [("start", "done"), ("transcribe", "done")] or \
        [(t["stage"], t["outcome"]) for t in times][-1][1] == "paused"
    assert not any(t["stage"] == "plan" for t in times)
    run.after_checkpoint = None
    produce_queue.resume(item["id"])
    times = produce_queue.get(item["id"])["stage_times"]
    assert [t["stage"] for t in times][-2:] == ["plan", "finalize"]
    assert all(t["finished_at"] for t in times)


def test_a_failed_stage_is_closed_as_failed(monkeypatch, projects):
    _fake_pipeline(monkeypatch, fail_at="plan")
    item = _add(projects[0])
    times = produce_queue.get(item["id"])["stage_times"]
    assert times[-1]["stage"] == "transcribe" and times[-1]["outcome"] == "failed"


def test_restart_clears_stage_times(monkeypatch, projects):
    _fake_pipeline(monkeypatch)
    item = _add(projects[0])
    produce_queue.set_paused(True)
    produce_queue.restart(item["id"])
    assert produce_queue.get(item["id"])["stage_times"] == []


def test_the_queue_waits_for_a_buzzedit_restart_that_is_pending(monkeypatch):
    # BuzzEdit restarts itself onto changed code only when idle, and a queue
    # that starts the next item the instant the last ends never lets it. So
    # before an item the queue waits until a new pid answers (or the flag goes).
    from integrations import buzzedit_client

    answers = iter([
        {"pid": 100, "reload_pending": True},
        {"pid": 100, "reload_pending": True},
        None,                                   # restarting
        {"pid": 200, "reload_pending": False},
    ])
    slept = []
    monkeypatch.setattr(buzzedit_client.BuzzEditClient, "health", lambda self: next(answers, None))
    monkeypatch.setattr(produce_queue.time, "sleep", lambda s: slept.append(s))
    _REAL_AWAIT_RELOAD()
    assert len(slept) == 3 and next(answers, "drained") == "drained"

    # Nothing pending: no wait at all.
    monkeypatch.setattr(buzzedit_client.BuzzEditClient, "health", lambda self: {"pid": 200, "reload_pending": False})
    slept.clear()
    _REAL_AWAIT_RELOAD()
    assert slept == []
