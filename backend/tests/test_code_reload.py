"""app/services/code_reload.py: the desktop Studio restarts itself onto changed
backend code, only once it is idle, and desktop_app.py's restart hand-over."""
import asyncio
import json
import os
import time

import pytest

from app.services import code_reload


@pytest.fixture(autouse=True)
def _no_real_buzzedit(monkeypatch):
    """busy_reason asks BuzzEdit's scheduler; the owner's real BuzzEdit may be rendering."""
    from app.api import produce_api
    from integrations.buzzedit_client import BuzzEditClient
    monkeypatch.setattr(produce_api, "buzzedit_job_active", lambda: False)
    monkeypatch.setattr(BuzzEditClient, "narration_busy", lambda self: False)


def test_code_mtime_sees_backend_sources_and_skips_tests_data_and_the_ui(tmp_path):
    (tmp_path / "app" / "services").mkdir(parents=True)
    (tmp_path / "app" / "static").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "knowledge").mkdir()
    src = tmp_path / "app" / "services" / "x.py"
    src.write_text("x = 1\n")
    old = time.time() - 100
    os.utime(src, (old, old))
    before = code_reload.code_mtime(tmp_path)
    assert before == pytest.approx(old, abs=2)
    (tmp_path / "tests" / "test_x.py").write_text("")
    (tmp_path / "app" / "static" / "index.html").write_text("")
    (tmp_path / "knowledge" / "memory.json").write_text("{}")
    assert code_reload.code_mtime(tmp_path) == before
    src.write_text("x = 2\n")
    assert code_reload.code_mtime(tmp_path) > before
    (tmp_path / "desktop_app.py").write_text("")
    assert code_reload.code_mtime(tmp_path) >= code_reload.code_mtime(tmp_path)


def test_inflight_counts_requests_but_not_the_event_feed_or_health():
    async def run(path):
        async def app(scope, receive, send):
            seen.append(code_reload._inflight)

        seen = []
        await code_reload.InflightMiddleware(app)({"type": "http", "path": path}, None, None)
        return seen[0]

    assert asyncio.run(run("/api/projects")) == 1
    assert asyncio.run(run("/api/studio/events")) == 0
    assert asyncio.run(run("/health")) == 0
    assert code_reload._inflight == 0


def _fake_world(monkeypatch, busy):
    clock = {"t": 0.0, "mtime": 0.0}
    monkeypatch.setattr(code_reload, "code_mtime", lambda root=None: clock["mtime"])
    monkeypatch.setattr(code_reload, "busy_reason", busy)
    monkeypatch.setattr(code_reload.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(code_reload.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(code_reload, "_pending", False)
    return clock


def test_changed_code_restarts_once_idle_long_enough(monkeypatch):
    calls = {"n": 0}

    def busy():
        calls["n"] += 1
        return "a production is running" if calls["n"] < 3 else None

    clock = _fake_world(monkeypatch, busy)
    restarted = []

    def sleep(s):
        clock["t"] += s
        clock["mtime"] = 1.0        # the source changes after the watch has started

    monkeypatch.setattr(code_reload.time, "sleep", sleep)
    code_reload.watch(lambda: restarted.append(True), check_s=30, quiet_s=120)
    assert restarted == [True] and code_reload.reload_pending()
    # Two busy samples reset the quiet clock; then 120 s of idle samples passed.
    assert calls["n"] >= 3 + 4


def test_never_restarts_while_busy(monkeypatch):
    clock = _fake_world(monkeypatch, lambda: "2 request(s) open")
    mt = [0.0]
    monkeypatch.setattr(code_reload, "code_mtime", lambda root=None: (mt.__setitem__(0, mt[0] + 1) or mt[0]))
    restarted = []
    ticks = {"n": 0}

    def sleep(s):
        ticks["n"] += 1
        if ticks["n"] > 50:
            raise KeyboardInterrupt
        clock["t"] += s

    monkeypatch.setattr(code_reload.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        code_reload.watch(lambda: restarted.append(True), check_s=30, quiet_s=120)
    assert restarted == []


def test_busy_reason_reads_the_queue_and_open_requests(monkeypatch):
    from app.services import produce_queue
    from integrations import idle_offload

    monkeypatch.setattr(idle_offload, "_other_work_running", lambda: False)
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": False, "items": [{"status": "running"}]})
    assert code_reload.busy_reason() == "a production is running"
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": False, "items": [{"status": "queued"}]})
    assert code_reload.busy_reason() == "a production is waiting to run"
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": True, "items": [{"status": "queued"}]})
    assert code_reload.busy_reason() is None
    monkeypatch.setattr(code_reload, "_inflight", 2)
    assert code_reload.busy_reason() == "2 request(s) open"
    monkeypatch.setattr(code_reload, "_inflight", 0)
    monkeypatch.setattr(idle_offload, "_other_work_running", lambda: True)
    assert code_reload.busy_reason() == "production work is running outside the queue"


def test_the_next_studio_waits_for_its_predecessor(tmp_path, monkeypatch):
    import desktop_app

    record = tmp_path / "restart.json"
    monkeypatch.setattr(desktop_app, "RESTART_RECORD", str(record))
    monkeypatch.setattr(desktop_app, "PREDECESSOR_WAIT_S", 5.0)
    alive = {"n": 3}

    def pid_alive(pid):
        alive["n"] -= 1
        return alive["n"] > 0

    monkeypatch.setattr(desktop_app.buzzcaf_ports, "_pid_alive", pid_alive)
    monkeypatch.setattr(desktop_app, "_studio_answering", lambda url, timeout=5.0: False)
    monkeypatch.setattr(desktop_app.time, "sleep", lambda s: None)
    record.write_text(json.dumps({"pid": 4242, "port": 8099, "at": time.time()}), encoding="utf-8")
    desktop_app._await_predecessor()
    assert alive["n"] == 0 and not record.exists()      # waited until the pid was gone, record consumed

    # No record: nothing to wait for. A stale record is ignored too.
    desktop_app._await_predecessor()
    record.write_text(json.dumps({"pid": 4242, "port": 8099, "at": time.time() - 3600}), encoding="utf-8")
    alive["n"] = 3
    desktop_app._await_predecessor()
    assert alive["n"] == 3 and not record.exists()


def test_restart_writes_the_record_then_spawns_then_closes(monkeypatch, tmp_path):
    import desktop_app
    from app.api import studio_api

    record = tmp_path / "restart.json"
    monkeypatch.setattr(desktop_app, "RESTART_RECORD", str(record))
    order = []
    monkeypatch.setattr(desktop_app, "_spawn_detached", lambda cmd: order.append(("spawn", cmd)) or True)
    monkeypatch.setattr(studio_api, "_shutdown_process", lambda: order.append(("close",)))
    assert desktop_app.restart_onto_new_code(8099)
    assert [o[0] for o in order] == ["spawn", "close"]
    assert json.loads(record.read_text(encoding="utf-8"))["pid"] == os.getpid()

    # The next Studio could not be started: this one stays up, on the old code.
    order.clear()
    monkeypatch.setattr(desktop_app, "_spawn_detached", lambda cmd: False)
    assert not desktop_app.restart_onto_new_code(8099)
    assert order == [] and not record.exists()


def test_a_background_job_holding_the_idle_guard_counts_as_busy(monkeypatch):
    """An auto story being narrated holds idle_offload.busy(); the restart must wait for it."""
    from app.services import code_reload, produce_queue
    from integrations import idle_offload
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": False, "items": []})
    monkeypatch.setattr(idle_offload, "_other_work_running", lambda: False)
    with idle_offload.busy():
        assert "background job" in (code_reload.busy_reason() or "")
    assert code_reload.busy_reason() is None


def test_a_buzzedit_narration_counts_as_busy(monkeypatch):
    """A Studio restart must not take a headless BuzzEdit down mid-narration
    (STUDIO_DIRECTOR_PLAN.md enhancement 2/5), same as it already waits for a
    rendering reel."""
    from app.services import produce_queue
    from integrations import buzzedit_client, idle_offload
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": False, "items": []})
    monkeypatch.setattr(idle_offload, "_other_work_running", lambda: False)

    class _FakeClient:
        def vibe_reel_busy(self):
            return False

        def narration_busy(self):
            return True

    monkeypatch.setattr(buzzedit_client, "BuzzEditClient", lambda: _FakeClient())
    assert code_reload.busy_reason() == "BuzzEdit is narrating"
