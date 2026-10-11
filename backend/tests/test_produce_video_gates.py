"""
The produce_video review-gate state machine in `app/api/produce_api.py`:
`review_mode` validation, the `awaiting_cut_review` / `awaiting_plan_review`
pauses, `produce_video/continue` and `/cancel`, and restart-safety (the gate
is read back from `project.metadata`, not from in-memory state).

Visual planning itself (`integrations/visual_windows.py`) is stubbed out here
via `produce_api.plan_visual_windows` -- its own chunking/parsing/retry logic
is covered by `test_visual_windows.py`. No real LLM or BuzzEdit call is ever
made.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from app.services import produce_queue
from core.models.project import Project


@pytest.fixture
def client():
    return TestClient(app)


def _kept_words(words):
    out = []
    t = 0.0
    for w in words:
        out.append({"word": w, "start": t, "end": t + 0.4})
        t += 0.5
    return out


DEFAULT_WORDS = ["Hello", "world", "welcome", "to", "the", "show"]


def _make_project(project_id="gate_test_proj", review_mode=None):
    p = Project(id=project_id, name="Gate Test", brand="Life3Baje", workflow_name="life3baje_video")
    p.metadata["buzzedit_project_id"] = "be_proj_1"
    if review_mode is not None:
        p.metadata["video_settings"] = {"review_mode": review_mode}
    p.save()
    return p


@pytest.fixture(autouse=True)
def isolated_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(produce_queue, "QUEUE_PATH", str(tmp_path / "produce_queue.json"))
    produce_queue.reset_for_tests()
    yield
    produce_queue.reset_for_tests()


@pytest.fixture
def project():
    p = _make_project()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)
    with produce_api._produce_lock:
        produce_api._produce_status.pop(p.id, None)


def _patch_kept_words(monkeypatch, words=None, sequence=None):
    """`sequence` (a list of word-lists) makes each successive call return the
    next entry, so a test can prove a re-fetch actually happened."""
    calls = {"n": 0}

    def fake(self, project_id):
        if sequence is not None:
            i = min(calls["n"], len(sequence) - 1)
            calls["n"] += 1
            return _kept_words(sequence[i])
        return _kept_words(words if words is not None else DEFAULT_WORDS)

    monkeypatch.setattr(produce_api.BuzzEditClient, "get_kept_words", fake)
    return calls


def _patch_render_plumbing(monkeypatch):
    """Everything `_finalize_and_render`/`_await_render` touches on BuzzEdit,
    stubbed to succeed instantly -- these tests are about the gate state
    machine, not the render poll loop (already covered elsewhere)."""
    monkeypatch.setattr(produce_api.BuzzEditClient, "set_script", lambda self, pid, text: {"ok": True})
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "enqueue_presentation",
        lambda self, pid, settings, start_at="": {"job": {"id": "job_1"}},
    )
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "get_jobs",
        lambda self: {"jobs": [{"id": "job_1", "status": "completed", "progress": 1.0}]},
    )
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "get_report",
        lambda self, pid: {"output_path": "/out/video.mp4"},
    )
    monkeypatch.setattr(produce_api, "_free_gpu_for_render", lambda project_id: None)


def _stub_planning(monkeypatch, beats=None, ok=1, failed=None, windows=1):
    beats = beats if beats is not None else [{
        "kind": "broll_image", "anchor": "welcome to the show", "start": 1.0, "end": 2.0,
        "window_index": 0, "prompt": "a lonely street at night", "image_prompt": "a lonely street at night",
    }]
    result = {"beats": beats, "windows": windows, "ok": ok, "failed": failed or []}
    monkeypatch.setattr(produce_api, "plan_visual_windows", lambda *a, **k: result)
    return result


# ------------------------------------------------------------ review_mode


def test_review_mode_defaults_to_plan(project):
    assert produce_api._resolve_review_mode(project) == "plan"


def test_review_mode_saved_value_wins(project):
    project.metadata["video_settings"] = {"review_mode": "cuts_and_plan"}
    assert produce_api._resolve_review_mode(project) == "cuts_and_plan"


def test_review_mode_garbage_falls_back_to_plan(project):
    project.metadata["video_settings"] = {"review_mode": "yolo"}
    assert produce_api._resolve_review_mode(project) == "plan"


def test_put_video_settings_accepts_review_mode(client, project):
    resp = client.put(f"/api/projects/{project.id}/video_settings", json={"review_mode": "none"})
    assert resp.status_code == 200
    assert resp.json()["video_settings"]["review_mode"] == "none"
    assert Project.load(project.id).metadata["video_settings"]["review_mode"] == "none"


def test_put_video_settings_rejects_bad_review_mode(client, project):
    resp = client.put(f"/api/projects/{project.id}/video_settings", json={"review_mode": "sometimes"})
    assert resp.status_code == 400


# ----------------------------------------------------- _plan_and_render


def test_plan_and_render_pauses_for_plan_review_by_default(monkeypatch, project):
    _patch_kept_words(monkeypatch)
    _stub_planning(monkeypatch)
    _patch_render_plumbing(monkeypatch)

    produce_api._plan_and_render(project.id, "record_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "awaiting_plan_review"
    assert status["planning"]["windows"] == 1
    assert status["planning"]["ok"] == 1
    assert status["planning"]["failed"] == []

    reloaded = Project.load(project.id)
    gate = reloaded.metadata["produce_gate"]
    assert gate["stage"] == "plan_review"
    assert reloaded.assets["visual_plan_take"] == "production/visual_plan_take.json"

    import json, os
    plan_path = os.path.join(reloaded.get_project_dir(), "production", "visual_plan_take.json")
    with open(plan_path, "r", encoding="utf-8") as f:
        stored = json.load(f)
    assert len(stored["beats"]) == 1
    assert stored["beats"][0]["deleted"] is False


def test_plan_and_render_renders_straight_through_when_review_mode_none(monkeypatch, project):
    project.metadata["video_settings"] = {"review_mode": "none"}
    project.save()
    _patch_kept_words(monkeypatch)
    _stub_planning(monkeypatch)
    _patch_render_plumbing(monkeypatch)

    calls = {}
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "set_script",
        lambda self, pid, text: calls.setdefault("text", text) or {"ok": True},
    )

    produce_api._plan_and_render(project.id, "record_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "ready"
    assert "[broll:" in calls["text"]
    assert "a lonely street at night" in calls["text"]
    assert Project.load(project.id).metadata.get("produce_gate") is None


def test_plan_and_render_forces_review_when_every_window_fails(monkeypatch, project):
    project.metadata["video_settings"] = {"review_mode": "none"}
    project.save()
    _patch_kept_words(monkeypatch)
    _stub_planning(monkeypatch, beats=[], ok=0, failed=[{"window_index": 0, "reason": "simulated content"}])
    _patch_render_plumbing(monkeypatch)

    produce_api._plan_and_render(project.id, "record_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "awaiting_plan_review"
    assert "Every planning window failed" in status["warning"]
    assert Project.load(project.id).metadata["produce_gate"]["stage"] == "plan_review"


# --------------------------------------------------- plan review: edits


def test_continue_after_plan_review_with_deleted_beat_drops_it(monkeypatch, project):
    _patch_kept_words(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    calls = {}
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "set_script",
        lambda self, pid, text: calls.setdefault("text", text) or {"ok": True},
    )
    plan = [{
        "kind": "broll_image", "anchor": "welcome to the show", "start": 1.0, "end": 2.0,
        "window_index": 0, "prompt": "a lonely street", "image_prompt": "a lonely street", "deleted": True,
    }]

    produce_api._continue_after_plan_review(project.id, "record_first", None, False, plan)

    assert produce_api._get_status(project.id)["state"] == "ready"
    assert "[broll:" not in calls["text"]


def test_continue_after_plan_review_applies_edited_prompt(monkeypatch, project):
    _patch_kept_words(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    calls = {}
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "set_script",
        lambda self, pid, text: calls.setdefault("text", text) or {"ok": True},
    )
    plan = [{
        "kind": "broll_image", "anchor": "welcome to the show", "start": 1.0, "end": 2.0,
        "window_index": 0, "prompt": "a rainy rooftop", "image_prompt": "a lonely street", "deleted": False,
    }]

    produce_api._continue_after_plan_review(project.id, "record_first", None, False, plan)

    assert "a rainy rooftop" in calls["text"]
    assert "a lonely street" not in calls["text"]


def test_continue_after_plan_review_uses_saved_plan_when_none_given(monkeypatch, project):
    _patch_kept_words(monkeypatch)
    _stub_planning(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    # First pause: writes visual_plan_take.json to disk.
    produce_api._plan_and_render(project.id, "record_first", None, False)
    assert produce_api._get_status(project.id)["state"] == "awaiting_plan_review"

    calls = {}
    monkeypatch.setattr(
        produce_api.BuzzEditClient, "set_script",
        lambda self, pid, text: calls.setdefault("text", text) or {"ok": True},
    )
    produce_api._continue_after_plan_review(project.id, "record_first", None, False, None)

    assert produce_api._get_status(project.id)["state"] == "ready"
    assert "a lonely street at night" in calls["text"]


# ----------------------------------------------------- cut review re-fetch


def test_continue_after_cut_review_refetches_kept_words(monkeypatch, project):
    produce_api._save_gate(project, "cut_review", "record_first", None, False)
    calls = _patch_kept_words(monkeypatch, sequence=[["Hello", "world"], DEFAULT_WORDS])
    _stub_planning(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    monkeypatch.setattr(produce_api.BuzzEditClient, "set_script", lambda self, pid, text: {"ok": True})

    produce_api._continue_after_cut_review(project.id, "record_first", None, False)

    # _plan_and_render (called by the continuation) is what actually fetches
    # kept words -- confirms the fetch happened after the gate cleared, not
    # a cached copy from before the (simulated) cut edit. Default review_mode
    # is "plan", so it pauses again -- at "plan_review" now, not "cut_review".
    assert calls["n"] >= 1
    assert Project.load(project.id).metadata["produce_gate"]["stage"] == "plan_review"
    assert produce_api._get_status(project.id)["state"] == "awaiting_plan_review"


# --------------------------------------------------------------- /continue


def _sync_thread(monkeypatch):
    """Runs a spawned thread's target synchronously, so the HTTP call and its
    background work finish before the test asserts anything."""
    class _Immediate:
        def __init__(self, target=None, name=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    monkeypatch.setattr(produce_api.threading, "Thread", _Immediate)
    monkeypatch.setattr(produce_queue.threading, "Thread", _Immediate)


def test_continue_endpoint_needs_a_pending_gate(client, project):
    resp = client.post(f"/api/projects/{project.id}/produce_video/continue", json={"stage": "cut_review"})
    assert resp.status_code == 409


def test_continue_endpoint_rejects_wrong_stage(client, project):
    produce_api._save_gate(project, "plan_review", "record_first", None, False)
    resp = client.post(f"/api/projects/{project.id}/produce_video/continue", json={"stage": "cut_review"})
    assert resp.status_code == 409


def test_continue_endpoint_resumes_plan_review(client, monkeypatch, project):
    _sync_thread(monkeypatch)
    _patch_kept_words(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    produce_api._save_gate(project, "plan_review", "record_first", None, False)
    plan_path_project = Project.load(project.id)
    import json, os
    prod_dir = os.path.join(plan_path_project.get_project_dir(), "production")
    os.makedirs(prod_dir, exist_ok=True)
    with open(os.path.join(prod_dir, "visual_plan_take.json"), "w", encoding="utf-8") as f:
        json.dump({"beats": [{"kind": "broll_image", "anchor": "welcome to the show",
                              "prompt": "x", "image_prompt": "x", "deleted": False}]}, f)

    resp = client.post(f"/api/projects/{project.id}/produce_video/continue", json={"stage": "plan_review"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"
    assert produce_api._get_status(project.id)["state"] == "ready"


# ----------------------------------------------------------------- /cancel


def test_cancel_clears_a_pending_gate(client, project):
    produce_api._save_gate(project, "plan_review", "record_first", None, False)
    resp = client.post(f"/api/projects/{project.id}/produce_video/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cancelled"
    assert body["had_pending_gate"] is True
    assert Project.load(project.id).metadata.get("produce_gate") is None
    assert produce_api._get_status(project.id)["state"] == "cancelled"


def test_cancel_refuses_an_active_render(client, project):
    produce_api._set_status(project.id, state="running")
    resp = client.post(f"/api/projects/{project.id}/produce_video/cancel")
    assert resp.status_code == 409


# ------------------------------------------------ produce_video guard + restart


def test_produce_video_refuses_to_start_over_a_pending_gate(client, project):
    produce_api._save_gate(project, "plan_review", "record_first", None, False)
    resp = client.post(f"/api/projects/{project.id}/produce_video", json={"recording_path": "x.mp4"})
    assert resp.status_code == 409


def test_status_falls_back_to_the_persisted_gate_after_a_restart(client, project):
    """No in-memory status at all (simulating a fresh process) but a gate
    persisted on the project -- the status endpoint must not claim "idle"."""
    with produce_api._produce_lock:
        produce_api._produce_status.pop(project.id, None)
    produce_api._save_gate(project, "cut_review", "record_first", None, False)

    resp = client.get(f"/api/projects/{project.id}/produce_video/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "awaiting_cut_review"
    assert body["resumed_after_restart"] is True


# ------------------------------------------------------------ effects review


def _stub_effects_sample(monkeypatch, calls):
    def fake(project_id, settings_override):
        calls.append(project_id)
        return {"url": "http://buzzedit/sample.mp4", "result": {"text_fx": {"knockout": 1}}}
    monkeypatch.setattr(produce_api, "run_effects_sample", fake)


def test_effects_review_parks_before_the_render_with_a_sample(monkeypatch, project):
    project.metadata["video_settings"] = {"review_mode": "none", "effects_review": True}
    project.save()
    _patch_kept_words(monkeypatch)
    _stub_planning(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    enqueued = []
    monkeypatch.setattr(produce_api.BuzzEditClient, "enqueue_presentation",
                        lambda self, pid, settings, start_at="": enqueued.append(pid) or {"job": {"id": "job_1"}})
    samples = []
    _stub_effects_sample(monkeypatch, samples)

    produce_api._plan_and_render(project.id, "record_first", None, False)

    status = produce_api._get_status(project.id)
    assert status["state"] == "awaiting_effects_review"
    assert status["effects_sample"]["url"] == "http://buzzedit/sample.mp4"
    assert samples == [project.id]
    assert enqueued == [], "nothing renders until the sample is approved"
    assert Project.load(project.id).metadata["produce_gate"]["stage"] == "effects_review"


def test_continuing_the_effects_review_renders_without_a_second_sample(client, monkeypatch, project):
    _sync_thread(monkeypatch)
    project.metadata["video_settings"] = {"effects_review": True}
    project.save()
    _patch_kept_words(monkeypatch)
    _patch_render_plumbing(monkeypatch)
    samples = []
    _stub_effects_sample(monkeypatch, samples)
    produce_api._save_gate(Project.load(project.id), "effects_review", "record_first", None, False)

    resp = client.post(f"/api/projects/{project.id}/produce_video/continue", json={"stage": "effects_review"})

    assert resp.status_code == 200
    assert samples == [], "an approved project goes straight to the render"
    assert produce_api._get_status(project.id)["state"] == "ready"
    assert Project.load(project.id).metadata["effects_approved_for"] == "be_proj_1"


def test_retest_needs_a_pending_effects_review(client, project):
    resp = client.post(f"/api/projects/{project.id}/produce_video/effects_sample")
    assert resp.status_code == 409


def test_status_restores_an_effects_review_after_a_restart(client, project):
    with produce_api._produce_lock:
        produce_api._produce_status.pop(project.id, None)
    p = Project.load(project.id)
    p.metadata["effects_sample"] = {"url": "http://buzzedit/sample.mp4"}
    p.save()
    produce_api._save_gate(Project.load(project.id), "effects_review", "record_first", None, False)
    body = client.get(f"/api/projects/{project.id}/produce_video/status").json()
    assert body["state"] == "awaiting_effects_review"
    assert body["effects_sample"]["url"] == "http://buzzedit/sample.mp4"
