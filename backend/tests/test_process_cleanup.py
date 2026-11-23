"""`app/services/process_cleanup.py` -- what closing the Studio stops. Every
process here is a fake; nothing real is killed."""
from types import SimpleNamespace

import pytest

from app.services import process_cleanup

# conftest stubs it out for every other test; psutil is faked here.
_REAL_STOP_HEADLESS = process_cleanup.stop_headless_buzzedit


@pytest.fixture(autouse=True)
def _real_stop_headless(monkeypatch):
    monkeypatch.setattr(process_cleanup, "stop_headless_buzzedit", _REAL_STOP_HEADLESS)


class _Error(Exception):
    pass


class _Proc:
    def __init__(self, pid, name, env=None, children=(), parents=()):
        self.pid, self._name, self._env = pid, name, env or {}
        self._children, self._parents = list(children), list(parents)
        self.killed = False

    def name(self):
        return self._name

    def environ(self):
        return self._env

    def children(self, recursive=False):
        return self._children

    def parents(self):
        return self._parents

    def kill(self):
        self.killed = True


def _fake_psutil(monkeypatch, procs, me_pid=1):
    fake = SimpleNamespace(
        Error=_Error,
        Process=lambda pid: procs[pid],
        wait_procs=lambda victims, timeout=None: (victims, []),
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake)
    monkeypatch.setattr(process_cleanup.os, "getpid", lambda: me_pid)


def test_children_are_killed_but_not_the_window_engine(monkeypatch):
    grandchild = _Proc(12, "node.exe")
    vite = _Proc(11, "cmd.exe", children=[grandchild])
    webview = _Proc(13, "msedgewebview2.exe")
    me = _Proc(1, "python.exe", children=[vite, webview])
    _fake_psutil(monkeypatch, {1: me})

    killed = process_cleanup.stop_children()

    assert sorted(killed) == [11, 12]
    assert not webview.killed and not me.killed


def _buzzedit(monkeypatch, env):
    electron = _Proc(50, "electron.exe", env=env)
    comfy = _Proc(52, "python.exe")
    backend = _Proc(51, "python.exe", parents=[electron])
    electron._children = [backend, comfy]
    _fake_psutil(monkeypatch, {51: backend})
    monkeypatch.setattr("integrations.buzzcaf_ports.entry", lambda app: {"pid": 51} if app == "buzzedit" else None)
    return electron, backend, comfy


def test_a_headless_buzzedit_the_studio_started_is_stopped_with_its_backend_and_comfyui(monkeypatch):
    electron, backend, comfy = _buzzedit(monkeypatch, {"BUZZEDIT_HEADLESS": "1"})
    assert sorted(process_cleanup.stop_headless_buzzedit()) == [50, 51, 52]
    assert electron.killed and backend.killed and comfy.killed


def test_a_buzzedit_the_creator_opened_is_left_alone(monkeypatch):
    electron, backend, comfy = _buzzedit(monkeypatch, {})
    assert process_cleanup.stop_headless_buzzedit() == []
    assert not (electron.killed or backend.killed or comfy.killed)


def _scan_psutil(monkeypatch, procs, ledger_pid=None, me_pid=1):
    """A fake psutil whose process list is `procs` (each `_Proc` gets the
    `info` and parent link `process_iter` reports)."""
    by_pid = {p.pid: p for p in procs}

    def process(pid):
        if pid not in by_pid:
            raise _Error(f"no process {pid}")
        return by_pid[pid]

    fake = SimpleNamespace(
        Error=_Error, Process=process,
        process_iter=lambda attrs=None: iter(procs),
        wait_procs=lambda victims, timeout=None: (victims, []),
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake)
    monkeypatch.setattr(process_cleanup.os, "getpid", lambda: me_pid)
    monkeypatch.setattr("integrations.buzzcaf_ports.entry",
                        lambda app: {"pid": ledger_pid} if app == "buzzedit" and ledger_pid else None)
    monkeypatch.setattr("integrations.buzzcaf_ports.withdraw", lambda app: None)


def _tree(root_pid, env, ppid=900):
    """PowerShell -> Electron -> (backend, ComfyUI), all carrying `env`."""
    comfy = _Proc(root_pid + 3, "python.exe", env=env)
    backend = _Proc(root_pid + 2, "python.exe", env=env)
    electron = _Proc(root_pid + 1, "electron.exe", env=env, children=[backend, comfy])
    shell = _Proc(root_pid, "powershell.exe", env=env, children=[electron, backend, comfy])
    backend._parents = [electron, shell]
    for proc, parent in ((shell, ppid), (electron, root_pid), (backend, root_pid + 1), (comfy, root_pid + 1)):
        proc.info = {"pid": proc.pid, "ppid": parent}
    return [shell, electron, backend, comfy]


def test_every_headless_buzzedit_is_stopped_even_two_and_with_a_stale_ledger(monkeypatch):
    headless = {"BUZZEDIT_HEADLESS": "1"}
    first, second = _tree(100, headless), _tree(200, headless)
    mine = _tree(300, {})                       # one the creator opened
    me = _Proc(1, "python.exe", env=headless)   # never the Studio itself
    me.info = {"pid": 1, "ppid": 0}
    _scan_psutil(monkeypatch, first + second + mine + [me], ledger_pid=999)   # 999: long gone

    killed = process_cleanup.stop_headless_buzzedit()

    assert sorted(killed) == [100, 101, 102, 103, 200, 201, 202, 203]
    assert not any(p.killed for p in mine) and not me.killed


def test_buzzedit_is_told_the_studio_pid_only_by_the_desktop_studio(monkeypatch, tmp_path):
    from app.api import produce_api

    (tmp_path / "START_APP.vbs").write_text("")
    seen = {}
    monkeypatch.setattr(produce_api, "get_buzzedit_dir", lambda: str(tmp_path))
    monkeypatch.setattr(produce_api, "_headless_buzzedit_starting", lambda: False)
    monkeypatch.setattr(produce_api.sys, "platform", "win32")
    monkeypatch.setattr(produce_api.subprocess, "Popen", lambda *a, **k: seen.update(k["env"]))
    monkeypatch.setenv("BUZZCAF_DESKTOP_PID", str(produce_api.os.getpid()))
    assert produce_api.launch_buzzedit_process()
    assert seen["BUZZCAF_STUDIO_PID"] == str(produce_api.os.getpid()) and seen["BUZZEDIT_HEADLESS"] == "1"

    seen.clear()
    monkeypatch.setenv("BUZZCAF_DESKTOP_PID", "424242")       # e.g. the nightly runner
    monkeypatch.setenv("BUZZCAF_STUDIO_PID", "424242")
    assert produce_api.launch_buzzedit_process()
    assert "BUZZCAF_STUDIO_PID" not in seen


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    """`launch_buzzedit_process` with every real-world input faked: no
    production running, nothing on the port ledger, BuzzEdit never answered."""
    from app.api import produce_api
    from integrations import buzzedit_client

    (tmp_path / "START_APP.vbs").write_text("")
    launched, stopped = [], []
    monkeypatch.setattr(produce_api, "get_buzzedit_dir", lambda: str(tmp_path))
    monkeypatch.setattr(produce_api.subprocess, "Popen", lambda *a, **k: launched.append(a))
    monkeypatch.setattr(produce_api.sys, "platform", "win32")
    monkeypatch.setattr(produce_api, "_studio_using_buzzedit", lambda: False)
    monkeypatch.setattr(produce_api, "_buzzedit_ledger_alive", lambda: False)
    monkeypatch.setattr(buzzedit_client, "_last_answer_at", None)
    monkeypatch.setattr(process_cleanup, "stop_headless_buzzedit", lambda: stopped.append(1) or [])
    return produce_api, launched, stopped


def _root_tree(age_s: float):
    import time
    return SimpleNamespace(create_time=lambda: time.time() - age_s)


def test_a_second_buzzedit_is_not_started_while_the_first_is_coming_up(launcher, monkeypatch):
    produce_api, launched, stopped = launcher
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [_root_tree(20)])
    assert produce_api.launch_buzzedit_process() and launched == [] and stopped == []

    # Past its startup grace, never answered, not on the ledger: it failed to
    # start. Stopped, and a fresh one launched.
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [_root_tree(600)])
    assert produce_api.launch_buzzedit_process() and stopped == [1] and len(launched) == 1


def test_a_busy_buzzedit_is_never_killed(launcher, monkeypatch):
    """2026-10-20: the watchdog stopped a BuzzEdit 30 minutes into a
    transcription because one health probe timed out. A process that answered
    recently, or that a production is running on, is busy -- left alone."""
    from integrations import buzzedit_client

    produce_api, launched, stopped = launcher
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [_root_tree(45 * 60)])

    # Answered a minute ago: busy.
    monkeypatch.setattr(buzzedit_client, "_last_answer_at", buzzedit_client.time.monotonic() - 60)
    assert produce_api.launch_buzzedit_process() and stopped == [] and launched == []

    # Silent for longer than the hung threshold, but a production is on it.
    monkeypatch.setattr(buzzedit_client, "_last_answer_at",
                        buzzedit_client.time.monotonic() - produce_api.BUZZEDIT_HUNG_AFTER_S - 1)
    monkeypatch.setattr(produce_api, "_studio_using_buzzedit", lambda: True)
    assert produce_api.launch_buzzedit_process() and stopped == [] and launched == []

    # Never answered this Studio, but its backend is on the ledger and alive: wait.
    monkeypatch.setattr(produce_api, "_studio_using_buzzedit", lambda: False)
    monkeypatch.setattr(buzzedit_client, "_last_answer_at", None)
    monkeypatch.setattr(produce_api, "_buzzedit_ledger_alive", lambda: True)
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [_root_tree(10 * 60)])
    assert produce_api.launch_buzzedit_process() and stopped == [] and launched == []

    # Silent past the threshold with nothing running on it: hung, replaced.
    monkeypatch.setattr(buzzedit_client, "_last_answer_at",
                        buzzedit_client.time.monotonic() - produce_api.BUZZEDIT_HUNG_AFTER_S - 1)
    assert produce_api.launch_buzzedit_process() and stopped == [1] and len(launched) == 1


def test_studio_using_buzzedit_reads_the_queue_and_the_run_status(monkeypatch):
    from app.api import produce_api
    from app.services import produce_queue

    monkeypatch.setattr(produce_api, "render_in_progress", lambda: False)
    monkeypatch.setattr(produce_queue, "running_item", lambda: None)
    assert produce_api._studio_using_buzzedit() is False
    monkeypatch.setattr(produce_queue, "running_item", lambda: {"id": "x"})
    assert produce_api._studio_using_buzzedit() is True
    monkeypatch.setattr(produce_queue, "running_item", lambda: None)
    monkeypatch.setattr(produce_api, "render_in_progress", lambda: True)
    assert produce_api._studio_using_buzzedit() is True


def test_buzzedit_ledger_alive_requires_a_matching_health_answer(monkeypatch):
    """2026-10-20: a live pid on the ledger is not proof by itself -- the
    Studio's own backend can take BuzzEdit's old port while BuzzEdit is
    closed, leaving BuzzEdit's ledger entry naming a pid that is alive but is
    no longer BuzzEdit. The entry's health route has to still say buzzedit,
    unless it is too young to have answered at all yet."""
    from datetime import datetime, timedelta, timezone

    from app.api import produce_api
    from integrations import buzzcaf_ports

    monkeypatch.setattr(produce_api, "_stale_buzzedit_ledger_logged", False)
    record = {"pid": 123, "health": "http://127.0.0.1:8100/api/health",
              "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    monkeypatch.setattr(buzzcaf_ports, "entry", lambda app: dict(record) if app == "buzzedit" else None)
    monkeypatch.setattr(buzzcaf_ports, "_pid_alive", lambda pid: True)

    # Answers, but as the Studio itself, not BuzzEdit: stale.
    monkeypatch.setattr(buzzcaf_ports, "_probe", lambda url: {"app": "buzzcaf"})
    assert produce_api._buzzedit_ledger_alive() is False

    # Answers as BuzzEdit: alive.
    monkeypatch.setattr(buzzcaf_ports, "_probe", lambda url: {"app": "buzzedit"})
    assert produce_api._buzzedit_ledger_alive() is True

    # No answer yet, but still inside the startup grace: give it the benefit
    # of the doubt.
    monkeypatch.setattr(buzzcaf_ports, "_probe", lambda url: None)
    assert produce_api._buzzedit_ledger_alive() is True

    # No answer, and past the startup grace: stale.
    record["started_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=produce_api.BUZZEDIT_STARTUP_GRACE_S + 5)
    ).isoformat(timespec="seconds")
    assert produce_api._buzzedit_ledger_alive() is False


def test_keep_alive_leaves_an_alive_but_silent_buzzedit_alone(monkeypatch):
    from app.services import buzzedit_keepalive
    from integrations import buzzedit_client

    monkeypatch.setattr(buzzedit_client.BuzzEditClient, "health", lambda self: None)
    monkeypatch.setattr(buzzedit_keepalive, "enabled", lambda: True)
    started = []

    import app.api.produce_api as produce_api
    monkeypatch.setattr(produce_api, "ensure_buzzedit_running", lambda **kw: started.append(1))

    # Its process tree is there: busy, not restarted.
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [_root_tree(600)])
    assert buzzedit_keepalive.check_once() is True and started == []

    # No process at all: started.
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [])
    monkeypatch.setattr(buzzedit_keepalive, "_buzzedit_alive", lambda: False)
    assert buzzedit_keepalive.check_once() is True and started == [1]
