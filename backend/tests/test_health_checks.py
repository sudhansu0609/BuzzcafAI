"""The health checks (2026-10-22): every watchdog's state as a row, the
silent failures as FAIL rows, and a check that breaks is itself a row."""
import threading
import time

from fastapi.testclient import TestClient

from app.services import app_envs, code_reload, health_checks as H
from integrations import idle_offload


class _ImmediateThread:
    """Runs its target synchronously, so a test does not race the real
    background thread `check_app_envs` starts for an automatic repair."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def test_the_reload_watcher_s_error_is_a_fail_row():
    code_reload._state.update({"started": True, "last_error": "TypeError: unsupported operand", "last_check_at": 1.0})
    row = H.check_code_reload()
    assert row["state"] == "fail" and "TypeError" in row["detail"]
    code_reload._state.update({"last_error": "", "pending": False})
    code_reload._pending = False
    assert H.check_code_reload()["state"] == "ok"
    code_reload._state["started"] = False
    assert H.check_code_reload()["state"] == "off"


def test_the_idle_offload_s_error_is_a_fail_row(monkeypatch):
    monkeypatch.setattr(idle_offload, "status", lambda: {"watcher_alive": True, "last_error": "work check: TypeError: x",
                                                        "used": ["lm_studio"], "in_flight": 0, "offloaded": False})
    assert H.check_idle_offload()["state"] == "fail"
    monkeypatch.setattr(idle_offload, "status", lambda: {"watcher_alive": False, "last_error": "", "used": []})
    assert H.check_idle_offload()["state"] == "fail"
    monkeypatch.setattr(idle_offload, "status", lambda: {"watcher_alive": True, "last_error": "", "used": ["lm_studio"],
                                                        "in_flight": 0, "offloaded": False, "idle_for_s": 30,
                                                        "idle_seconds_setting": 300, "last_check_at": 0})
    row = H.check_idle_offload()
    assert row["state"] == "ok" and "lm_studio" in row["summary"]


def test_run_all_never_raises_and_counts_states(monkeypatch):
    def boom():
        raise RuntimeError("nvidia-smi exploded")

    monkeypatch.setattr(H, "CHECKS", [lambda: H._row("a", "A", "ok", "fine"), boom,
                                      lambda: [H._row("b", "B", "fail", "bad", "why"), H._row("c", "C", "off", "n/a")]])
    out = H.run_all()
    ids = [r["id"] for r in out["checks"]]
    assert ids == ["a", "boom", "b", "c"]
    assert out["checks"][1]["state"] == "warn" and "exploded" in out["checks"][1]["detail"]
    assert out["overall"] == "fail" and out["counts"] == {"ok": 1, "warn": 1, "fail": 1, "off": 1}
    assert all(r.get("checked_at") for r in out["checks"])


def test_recent_errors_reads_the_log_tail(tmp_path, monkeypatch):
    from core import paths
    log = tmp_path / "studio.log"
    from datetime import datetime, timedelta
    now = datetime.now()
    old = (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    new = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    log.write_text(f"{old},000 ERROR x: ancient\n{new},000 INFO fine\n{new},000 ERROR buzzcaf: the queue broke\n", encoding="utf-8")
    monkeypatch.setattr(paths, "LOGS_DIR", str(tmp_path))
    monkeypatch.setattr(H, "check_recent_errors", H.check_recent_errors)
    import importlib
    row = H.check_recent_errors()
    assert row["state"] == "warn" and row["count"] == 1 and "queue broke" in row["detail"]


def test_the_route_answers():
    from app.main import app
    body = TestClient(app).get("/api/health/checks").json()
    assert body["overall"] in ("ok", "warn", "fail") and len(body["checks"]) >= 10
    assert {"id", "label", "state", "summary"} <= set(body["checks"][0])


def test_check_app_envs_ok_row_and_missing_row_starts_a_repair(monkeypatch):
    monkeypatch.setattr(threading, "Thread", _ImmediateThread)
    H._last_app_env_repair.clear()
    monkeypatch.setattr(app_envs, "discover_apps", lambda: ["Alpha", "Beta"])
    monkeypatch.setattr(app_envs, "status", lambda app: (
        {"app": "Alpha", "installed": True, "missing": [], "ok": True, "repairing": False} if app == "Alpha"
        else {"app": "Beta", "installed": True, "missing": ["node_modules\\electron\\dist\\electron.exe"],
             "ok": False, "repairing": False}))
    monkeypatch.setattr(app_envs, "log_tail", lambda app, lines=20: "setup failed partway through")
    started = []
    monkeypatch.setattr(app_envs, "repair", lambda app, **kw: started.append((app, kw)))

    rows = {r["id"]: r for r in H.check_app_envs()}
    assert rows["app_env_Alpha"]["state"] == "ok"
    beta = rows["app_env_Beta"]
    assert beta["state"] == "warn"
    assert "electron.exe" in beta["summary"] and "repair started" in beta["summary"]
    assert "setup failed partway through" in beta["detail"]
    assert started == [("Beta", {"wait": False})]


def test_check_app_envs_shows_repair_running_and_honours_the_cooldown(monkeypatch):
    monkeypatch.setattr(threading, "Thread", _ImmediateThread)
    H._last_app_env_repair.clear()
    monkeypatch.setattr(app_envs, "discover_apps", lambda: ["Gamma"])
    monkeypatch.setattr(app_envs, "log_tail", lambda app, lines=20: "")
    started = []
    monkeypatch.setattr(app_envs, "repair", lambda app, **kw: started.append(app))

    # Already repairing (locked): the row says so and does not start another.
    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True, "missing": ["y"],
                                                          "ok": False, "repairing": True})
    row = H.check_app_envs()[0]
    assert "repair running" in row["summary"] and not started

    # Not locked, but the cooldown from a moment-ago auto-repair still holds.
    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True, "missing": ["y"],
                                                          "ok": False, "repairing": False})
    H._last_app_env_repair["Gamma"] = time.time()
    row2 = H.check_app_envs()[0]
    assert "repair started" not in row2["summary"] and not started
