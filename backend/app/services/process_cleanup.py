"""
Everything the Studio started goes when the Studio goes.

The backend runs in the desktop app's own process, so ending that process ends
uvicorn -- but on Windows `os._exit` does not take child processes with it,
and one thing the Studio starts is deliberately *not* a child: a headless
BuzzEdit (`produce_api.launch_buzzedit_process`, via `wscript.exe`), which in
turn owns its own Python backend and ComfyUI. Left running, that trio holds
Whisper, the aligner and ComfyUI's models on the GPU after the Studio window
is gone.

`stop_everything()` is the one call both exits make: closing the window
(`desktop_app.on_closing`) and `POST /api/studio/shutdown`. Never raises --
a shutdown must always finish.
"""

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("buzzcaf_ai.process_cleanup")

#: Set by `POST /api/studio/shutdown` before it closes the window, so the
#: window does not stop to ask "a video is being produced, close anyway?"
#: when nobody is at it to answer.
shutdown_requested = False


def _kill_tree(proc) -> List[int]:
    """Kill `proc` and everything under it; the pids actually killed."""
    import psutil

    try:
        victims = proc.children(recursive=True) + [proc]
    except psutil.Error:
        return []
    killed = []
    for victim in victims:
        try:
            victim.kill()
            killed.append(victim.pid)
        except psutil.Error:
            pass
    psutil.wait_procs(victims, timeout=5)
    return killed


def stop_children() -> List[int]:
    """Kill every process this one started (file dialogs, `lms`, the Vite
    dev server, ...) -- never this process itself."""
    try:
        import psutil

        me = psutil.Process(os.getpid())
        killed = []
        for child in me.children(recursive=False):
            try:
                if child.name().lower().startswith("msedgewebview2"):
                    continue  # the window's own WebView2; it exits with the window
            except psutil.Error:
                continue
            killed.extend(_kill_tree(child))
        if killed:
            logger.info("Shutdown: stopped %d child process(es) of the Studio.", len(killed))
        return killed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shutdown: could not stop child processes (%s).", exc)
        return []


def _started_headless(proc) -> bool:
    """A BuzzEdit the Studio launched carries BUZZEDIT_HEADLESS=1 in its
    environment; one the creator opened does not, and is left alone."""
    try:
        return proc.environ().get("BUZZEDIT_HEADLESS") == "1"
    except Exception:  # noqa: BLE001 - AccessDenied etc.: not provably ours
        return False


def _ledger_shell(psutil):
    """The Electron shell of the BuzzEdit the port ledger names, if it is alive."""
    from integrations.buzzcaf_ports import entry

    pid = (entry("buzzedit") or {}).get("pid")
    if not pid:
        return None
    backend = psutil.Process(int(pid))
    # The ledger names BuzzEdit's Python backend; its parent is the
    # Electron main process that owns it and ComfyUI.
    shell = backend
    for ancestor in backend.parents():
        if ancestor.name().lower().startswith("electron"):
            shell = ancestor
    return shell if (_started_headless(shell) or _started_headless(backend)) else None


def headless_buzzedit_roots() -> List[Any]:
    """Every BuzzEdit process tree the Studio started: the topmost process of
    each tree that carries BUZZEDIT_HEADLESS=1 (the launcher hands it to
    PowerShell, Electron, BuzzEdit's backend and ComfyUI alike).

    Found by that mark rather than only through the ledger, which names one
    BuzzEdit backend: a second BuzzEdit started while the first was still
    coming up, or an Electron whose backend died and left the entry stale,
    used to be left running after the Studio closed."""
    try:
        import psutil
    except ImportError:
        return []
    me = os.getpid()
    flagged: Dict[int, Any] = {}
    parent_of: Dict[int, int] = {}
    for proc in psutil.process_iter(["pid", "ppid"]):
        if proc.pid in (0, 4, me):
            continue
        if _started_headless(proc):
            flagged[proc.pid] = proc
            parent_of[proc.pid] = (proc.info or {}).get("ppid") or 0
    return [proc for pid, proc in flagged.items() if parent_of.get(pid) not in flagged]


def stop_headless_buzzedit() -> List[int]:
    """Stop every BuzzEdit the Studio started for a background render: its
    Electron shell and, with it, the Python backend and ComfyUI it spawned.
    One the creator opened has no headless mark and is left alone."""
    killed: List[int] = []
    try:
        import psutil
    except ImportError:
        return killed
    roots: List[Any] = []
    try:
        shell = _ledger_shell(psutil)
        if shell is not None:
            roots.append(shell)
    except Exception as exc:  # noqa: BLE001 - gone already, a stale entry
        logger.debug("Shutdown: the ledger names no live headless BuzzEdit (%s).", exc)
    try:
        roots.extend(headless_buzzedit_roots())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Shutdown: could not look for headless BuzzEdit processes (%s).", exc)
    seen = set()
    trees = 0
    for root in roots:
        if root.pid in seen:
            continue
        seen.add(root.pid)
        trees += 1
        try:
            seen.update(child.pid for child in root.children(recursive=True))
        except Exception:  # noqa: BLE001
            pass
        killed.extend(pid for pid in _kill_tree(root) if pid not in killed)
    if killed:
        logger.info("Shutdown: stopped the headless BuzzEdit the Studio started (%d process(es), %d tree(s)).",
                    len(killed), trees)
        # Killed, not quit: BuzzEdit never got to withdraw its ledger entry.
        try:
            from integrations import buzzcaf_ports

            record = buzzcaf_ports.entry("buzzedit") or {}
            if record.get("pid") and not buzzcaf_ports._pid_alive(record["pid"]):
                buzzcaf_ports.withdraw("buzzedit")
        except Exception:  # noqa: BLE001
            pass
    return killed


def stop_everything() -> None:
    # First, so the keep-alive watchdog cannot start BuzzEdit again behind us.
    try:
        from app.services import buzzedit_keepalive
        buzzedit_keepalive.stop()
    except Exception:  # noqa: BLE001 - shutting down regardless
        pass
    stop_children()
    stop_headless_buzzedit()
