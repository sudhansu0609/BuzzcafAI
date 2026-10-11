"""`app/services/process_cleanup.py` -- what closing the Studio stops. Every
process here is a fake; nothing real is killed."""
from types import SimpleNamespace

import pytest

from app.services import process_cleanup


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


def test_a_second_buzzedit_is_not_started_while_the_first_is_coming_up(monkeypatch, tmp_path):
    from app.api import produce_api

    (tmp_path / "START_APP.vbs").write_text("")
    launched = []
    monkeypatch.setattr(produce_api, "get_buzzedit_dir", lambda: str(tmp_path))
    monkeypatch.setattr(produce_api.subprocess, "Popen", lambda *a, **k: launched.append(a))
    starting = SimpleNamespace(create_time=lambda: produce_api.time.time() - 20)
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [starting])
    assert produce_api.launch_buzzedit_process() and launched == []

    # Past its grace it is hung: stopped, and a fresh one launched.
    stopped = []
    hung = SimpleNamespace(create_time=lambda: produce_api.time.time() - 600)
    monkeypatch.setattr(process_cleanup, "headless_buzzedit_roots", lambda: [hung])
    monkeypatch.setattr(process_cleanup, "stop_headless_buzzedit", lambda: stopped.append(1) or [])
    monkeypatch.setattr(produce_api.sys, "platform", "win32")
    assert produce_api.launch_buzzedit_process() and stopped == [1] and len(launched) == 1
