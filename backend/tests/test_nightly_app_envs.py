"""Nightly run's app-environment preflight (2026-10-24): BuzzEdit's own
venv/engines/Electron build may be missing when the nightly task wakes the
PC; `run_tasks` repairs it first (waiting for it) and records the outcome,
without ever raising out of the batch."""
import nightly_run
from app.services import app_envs


def test_run_tasks_repairs_buzzedit_first_when_its_env_is_missing(monkeypatch):
    monkeypatch.setattr(nightly_run, "_wait_if_paused", lambda task: None)
    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True,
                                                          "missing": ["dist\\index.html"], "ok": False,
                                                          "repairing": False})
    calls = []

    def fake_repair(app, **kw):
        calls.append((app, kw))
        return {"status": "done", "exit_code": 0, "log_tail": ""}

    monkeypatch.setattr(app_envs, "repair", fake_repair)

    results = nightly_run.run_tasks(scope="__only_preflight_test__")
    entry = next(r for r in results if r["task"] == "app_envs")
    assert entry["app"] == "BuzzEdit" and entry["status"] == "done" and "error" not in entry
    assert calls and calls[0][0] == "BuzzEdit" and calls[0][1]["wait"] is True


def test_run_tasks_records_a_failed_repair_without_raising(monkeypatch):
    monkeypatch.setattr(nightly_run, "_wait_if_paused", lambda task: None)
    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True,
                                                          "missing": ["dist\\index.html"], "ok": False,
                                                          "repairing": False})
    monkeypatch.setattr(app_envs, "repair", lambda app, **kw: {"status": "timeout", "exit_code": None,
                                                               "log_tail": "still building"})

    results = nightly_run.run_tasks(scope="__only_preflight_test__")
    entry = next(r for r in results if r["task"] == "app_envs")
    assert entry["status"] == "timeout" and "timeout" in entry["error"] and "still building" in entry["error"]


def test_run_tasks_skips_repair_when_the_env_is_already_ok(monkeypatch):
    monkeypatch.setattr(nightly_run, "_wait_if_paused", lambda task: None)
    monkeypatch.setattr(app_envs, "status", lambda app: {"app": app, "installed": True, "missing": [],
                                                          "ok": True, "repairing": False})
    called = []
    monkeypatch.setattr(app_envs, "repair", lambda *a, **k: called.append(1))

    results = nightly_run.run_tasks(scope="__only_preflight_test__")
    assert not any(r["task"] == "app_envs" for r in results)
    assert not called
