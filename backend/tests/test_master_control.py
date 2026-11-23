"""The master pause / resume (docs/STUDIO_DIRECTOR_PLAN.md Part 1):
`app/services/master_control.py` -- durable state, hold points that block
and release on resume, the release sequence, and `code_reload`'s "paused
with held work is busy" rule.
"""
import threading
import time

import pytest

from app.services import master_control, produce_queue
from app.services import code_reload


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """Every test gets its own state file -- never the real
    `backend/config/master_control.json` (conftest does not sandbox
    CONFIG_DIR, only the knowledge/projects/logs dirs)."""
    monkeypatch.setattr(master_control, "STATE_PATH", str(tmp_path / "master_control.json"))
    master_control._state_cache = None
    master_control._held.clear()
    # produce_queue is real (conftest sandboxes KNOWLEDGE_PATH); start clean.
    produce_queue.set_paused(False)
    yield
    # Never leave a paused queue or a blocked thread behind for the next test.
    if master_control.is_paused():
        master_control.resume()
    produce_queue.set_paused(False)
    master_control._state_cache = None
    master_control._held.clear()


def _noop_buzzedit(monkeypatch):
    """BuzzEdit is not running in the test environment; its calls must be
    harmless no-ops rather than real HTTP attempts."""
    monkeypatch.setattr(master_control, "_pause_buzzedit", lambda mode, reason="", by="": {"ok": False})
    monkeypatch.setattr(master_control, "_resume_buzzedit", lambda: {"ok": False})


def test_pause_resume_state_durable_across_reload(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {"before": {}, "after": {}})

    master_control.pause(mode="soft", reason="testing", by="tester")
    assert master_control.is_paused() is True

    # Simulate a process restart: the in-memory cache is gone, only the file remains.
    master_control._state_cache = None
    st = master_control.state()
    assert st["paused"] is True
    assert st["reason"] == "testing"
    assert st["by"] == "tester"
    assert st["mode"] == "soft"
    assert st["since"]

    master_control.resume()
    master_control._state_cache = None
    assert master_control.is_paused() is False


def test_pause_is_idempotent_and_can_escalate_mode(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})

    first = master_control.pause(mode="soft", reason="a", by="dashboard")
    since = first["since"]
    second = master_control.pause(mode="now", reason="b")
    assert second["mode"] == "now"
    assert second["reason"] == "b"
    assert second["since"] == since  # still the original pause, not a new one
    assert second["by"] == "dashboard"  # unset `by` on the second call keeps the first


def test_resume_without_a_pause_is_a_noop():
    st = master_control.resume()
    assert st["paused"] is False


def test_wait_if_paused_blocks_and_returns_on_resume(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})
    monkeypatch.setattr(master_control, "POLL_S", 0.02)

    master_control.pause(mode="soft", reason="hold test")
    finished = threading.Event()
    said = []

    def worker():
        master_control.wait_if_paused("unit-test-spot", say=said.append)
        finished.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    # It must actually be blocked, with the spot recorded as held and the
    # `say` callback fired (both happen a hair after the thread starts).
    deadline = time.time() + 2
    while (not said or "unit-test-spot" not in master_control.held()) and time.time() < deadline:
        time.sleep(0.01)
    assert "unit-test-spot" in master_control.held()
    assert not finished.is_set()
    assert said and "unit-test-spot" in said[0]

    master_control.resume()
    assert finished.wait(timeout=2)
    assert "unit-test-spot" not in master_control.held()


def test_wait_if_paused_is_a_noop_when_not_paused():
    assert master_control.wait_if_paused("anything") is False
    assert master_control.held() == []


def test_release_memory_called_in_order(monkeypatch):
    from integrations import idle_offload

    calls = []
    monkeypatch.setattr(master_control, "_pause_buzzedit",
                         lambda mode, reason="", by="": calls.append(("buzzedit_pause", mode)) or {})
    monkeypatch.setattr(idle_offload, "offload_now", lambda reason: calls.append(("offload_now", reason)) or True)
    monkeypatch.setattr(master_control, "_memory_snapshot", lambda: {"ram_free_mb": 1})

    master_control.pause(mode="now", reason="order test")
    names = [c[0] for c in calls]
    assert names == ["buzzedit_pause", "offload_now"]
    assert calls[0][1] == "now"


def test_pause_sets_and_resume_restores_produce_queue_flag(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})

    assert produce_queue.snapshot()["paused"] is False
    master_control.pause(mode="soft")
    assert produce_queue.snapshot()["paused"] is True
    master_control.resume()
    assert produce_queue.snapshot()["paused"] is False


def test_pause_does_not_clear_a_pre_existing_produce_queue_pause(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})

    produce_queue.set_paused(True)  # the creator paused the queue by hand first
    master_control.pause(mode="soft")
    master_control.resume()
    assert produce_queue.snapshot()["paused"] is True  # the master never un-paused it


def test_code_reload_busy_while_paused_with_held_work(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})

    master_control.pause(mode="soft", reason="busy test")
    master_control._held["some loop"] = "now"
    reason = code_reload.busy_reason()
    assert reason is not None and "master paused" in reason
    master_control._held.clear()


def test_held_work_check_is_silent_with_nothing_held(monkeypatch):
    _noop_buzzedit(monkeypatch)
    monkeypatch.setattr(master_control, "_release_memory", lambda reason: {})
    # A paused Studio with nothing actively held yet must not trip *this*
    # check (code_reload's other checks run independently of the pause).
    master_control.pause(mode="soft")
    assert master_control.held() == []
