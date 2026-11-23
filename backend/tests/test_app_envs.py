"""Sibling-app environment discovery and self-repair (2026-10-24): `status()`
reads `installer/app.json`'s `health_paths` straight off disk, and `repair()`
runs `installer/setup_env.ps1` single-flight per app via a PID lock. No test
here may start a real installer -- `subprocess.Popen` is always stubbed."""
import json
import time

import pytest

from app.services import app_envs


def _make_app(tmp_path, name, health_paths, with_setup_script=True):
    root = tmp_path / name
    (root / "installer").mkdir(parents=True)
    (root / "installer" / "app.json").write_text(
        json.dumps({"id": name, "name": name, "health_paths": health_paths}), encoding="utf-8")
    if with_setup_script:
        (root / "installer" / "setup_env.ps1").write_text("# stub\n", encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def _sandbox_siblings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_envs, "SIBLINGS_ROOT", tmp_path)
    monkeypatch.setattr("app.services.master_control.wait_if_paused", lambda where, say=None: False)
    return tmp_path


def test_discover_apps_finds_installer_app_json(tmp_path):
    _make_app(tmp_path, "AppA", [])
    (tmp_path / "NotAnApp").mkdir()
    assert app_envs.discover_apps() == ["AppA"]


def test_status_reports_missing_health_paths_then_clears(tmp_path):
    root = _make_app(tmp_path, "AppB", [".venv\\Scripts\\python.exe", "dist\\index.html"])
    st = app_envs.status("AppB")
    assert st["ok"] is False
    assert set(st["missing"]) == {".venv\\Scripts\\python.exe", "dist\\index.html"}
    assert st["installed"] is False

    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / ".venv" / "Scripts" / "python.exe").write_bytes(b"")
    (root / "dist").mkdir()
    (root / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "installer" / "installed.json").write_text("{}", encoding="utf-8")

    st2 = app_envs.status("AppB")
    assert st2 == {"app": "AppB", "installed": True, "missing": [], "ok": True, "repairing": False, "self_test": None}


def _with_self_test(root, ok):
    info = json.loads((root / "installer" / "app.json").read_text(encoding="utf-8"))
    info["self_test"] = {"python": "py.exe", "script": "installer\\selftest.py", "result": "installer\\selftest.json"}
    (root / "installer" / "app.json").write_text(json.dumps(info), encoding="utf-8")
    (root / "py.exe").write_bytes(b"")
    (root / "installer" / "selftest.json").write_text(json.dumps({"ok": ok, "checks": [
        {"name": "Whisper's CUDA libraries load", "ok": ok, "required": True}]}), encoding="utf-8")


def test_a_failed_self_test_makes_files_that_exist_count_as_broken(tmp_path):
    root = _make_app(tmp_path, "AppS", [])
    _with_self_test(root, ok=False)
    st = app_envs.status("AppS")
    assert st["ok"] is False and st["missing"] == ["self-test: Whisper's CUDA libraries load"]


def test_ensure_working_repairs_and_tests_again(tmp_path, monkeypatch):
    root = _make_app(tmp_path, "AppT", [])
    _with_self_test(root, ok=False)
    runs = []

    def fake_run(cmd, **kwargs):  # the self-test: fails first, passes after the repair
        runs.append(cmd)
        (root / "installer" / "selftest.json").write_text(json.dumps({"ok": len(runs) > 1, "checks": []}),
                                                          encoding="utf-8")

    monkeypatch.setattr(app_envs.subprocess, "run", fake_run)
    monkeypatch.setattr(app_envs, "repair", lambda app, wait=False, status_callback=None: {"status": "done"})
    out = app_envs.ensure_working("AppT")
    assert out["ok"] is True and out["repaired"] is True and len(runs) == 2


def test_lock_alive_vs_stale_pid(tmp_path, monkeypatch):
    root = _make_app(tmp_path, "AppC", [])
    lock = root / "installer" / "setup.running"
    lock.write_text(json.dumps({"pid": 99999, "started": time.time()}), encoding="utf-8")

    monkeypatch.setattr("integrations.buzzcaf_ports._pid_alive", lambda pid: True)
    assert app_envs._lock_info("AppC") is not None
    assert app_envs.status("AppC")["repairing"] is True
    assert lock.exists()

    monkeypatch.setattr("integrations.buzzcaf_ports._pid_alive", lambda pid: False)
    assert app_envs._lock_info("AppC") is None
    assert not lock.exists()  # a dead PID's lock is stale and is cleared
    assert app_envs.status("AppC")["repairing"] is False


def test_repair_invokes_powershell_with_setup_env(tmp_path, monkeypatch):
    root = _make_app(tmp_path, "AppD", [])
    calls = []

    class FakeProc:
        pid = 4242

        def poll(self):
            return 0

    def fake_popen(cmd, **kw):
        calls.append((cmd, kw))
        return FakeProc()

    monkeypatch.setattr(app_envs.subprocess, "Popen", fake_popen)

    out = app_envs.repair("AppD", wait=True, timeout=5)
    assert out == {"app": "AppD", "status": "done", "exit_code": 0, "log_tail": ""}
    cmd, kw = calls[0]
    assert cmd[0].lower() == "powershell.exe"
    assert str(root / "installer" / "setup_env.ps1") in cmd
    assert kw["cwd"] == str(root)
    assert not (root / "installer" / "setup.running").exists()  # cleared once it finished


def test_repair_reports_already_running_while_the_lock_is_alive(tmp_path, monkeypatch):
    root = _make_app(tmp_path, "AppE", [])
    monkeypatch.setattr("integrations.buzzcaf_ports._pid_alive", lambda pid: True)
    (root / "installer" / "setup.running").write_text(
        json.dumps({"pid": 123, "started": time.time()}), encoding="utf-8")

    started = []
    monkeypatch.setattr(app_envs.subprocess, "Popen", lambda *a, **k: started.append(1))

    out = app_envs.repair("AppE", wait=False)
    assert out["status"] == "already_running" and not started


def test_repair_checks_master_pause_before_starting(tmp_path, monkeypatch):
    _make_app(tmp_path, "AppF", [])
    waited = []
    monkeypatch.setattr("app.services.master_control.wait_if_paused",
                        lambda where, say=None: waited.append(where) or False)

    class FakeProc:
        pid = 1

        def poll(self):
            return 0

    monkeypatch.setattr(app_envs.subprocess, "Popen", lambda *a, **k: FakeProc())
    app_envs.repair("AppF", wait=True, timeout=5)
    assert waited == ["app_envs.repair:AppF"]


def test_repair_errors_without_a_setup_script(tmp_path):
    _make_app(tmp_path, "AppG", [], with_setup_script=False)
    out = app_envs.repair("AppG")
    assert out["status"] == "error"


def test_repair_times_out_when_the_process_never_exits(tmp_path, monkeypatch):
    _make_app(tmp_path, "AppH", [])
    monkeypatch.setattr(app_envs.time, "sleep", lambda s: None)  # no real delay in the poll loop

    class NeverExits:
        pid = 7

        def poll(self):
            return None

    monkeypatch.setattr(app_envs.subprocess, "Popen", lambda *a, **k: NeverExits())
    out = app_envs.repair("AppH", wait=True, timeout=0.2)
    assert out["status"] == "timeout" and out["exit_code"] is None
