"""Restart the Studio onto changed code by itself, once it is idle.

The desktop Studio is one process: the window on the main thread, uvicorn on a
daemon thread. A fix to the backend used to wait for someone to close and
reopen the app -- and a fix made during a production waited until the creator
noticed. The rule (2026-10-21, the same one BuzzEdit's runtime/code_reload.py
follows): a fix applies by itself, nobody restarts anything by hand.

`watch(restart)` runs on its own thread. Every CHECK_S it compares the newest
backend source mtime with the one at start; once the source is newer it waits
for QUIET_S of idleness -- no production running or waiting to run, no nightly
run, no BuzzEdit job the Studio tracks, no request open -- and calls `restart`,
which `desktop_app.py` implements as "start the next Studio outside the
launcher's job object, then close this one the way the X does".

`InflightMiddleware` counts open requests; long-lived streams (the event
feed) and health probes are not work and are not counted.
"""
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]
_SOURCE_DIRS = ("app", "core", "integrations", "runtime")
_SOURCE_FILES = ("desktop_app.py", "preflight.py")
_SKIP_DIRS = {"tests", "__pycache__", "static", "knowledge", "config", "prompts", "data",
              "node_modules", ".venv", "venv"}
CHECK_S = 30.0
QUIET_S = 120.0
_IGNORED_PATHS = ("/health", "/api/health", "/api/studio/events")

_inflight = 0
_lock = threading.Lock()
_pending = False
#: What the health page shows (2026-10-22): the watcher used to fail
#: silently for hours (a str/Path slip in the idle check), and nothing but
#: a log line said so.
_state: dict = {"last_check_at": 0.0, "last_error": "", "busy_reason": None, "idle_since": None, "started": False}


def status() -> dict:
    """The reload watcher's state for the health page."""
    with _lock:
        out = dict(_state)
    out["pending"] = _pending
    return out


def code_mtime(root: Path = BACKEND_DIR) -> float:
    """The newest mtime of a backend source file; tests, data and the built
    UI are not code this process runs."""
    newest = 0.0
    for name in _SOURCE_FILES:
        try:
            newest = max(newest, (root / name).stat().st_mtime)
        except OSError:
            pass
    for sub in _SOURCE_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for filename in filenames:
                if filename.endswith(".py"):
                    try:
                        newest = max(newest, os.path.getmtime(os.path.join(dirpath, filename)))
                    except OSError:
                        pass
    return newest


def reload_pending() -> bool:
    return _pending


class InflightMiddleware:
    """Pure ASGI: counts requests in flight (a workflow step runs inside its
    request, so one open request is one running step)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _inflight
        counted = scope.get("type") in ("http", "websocket") and \
            not str(scope.get("path", "")).startswith(_IGNORED_PATHS)
        if counted:
            with _lock:
                _inflight += 1
        try:
            await self.app(scope, receive, send)
        finally:
            if counted:
                with _lock:
                    _inflight -= 1


def busy_reason() -> Optional[str]:
    """Why the Studio must not restart now, or None."""
    from app.services import produce_queue
    from integrations import idle_offload

    # A master pause with nothing held is not busy -- a paused Studio with an
    # empty queue and no running job may still reload. One *with* held work
    # must never restart onto it mid-hold (docs/STUDIO_DIRECTOR_PLAN.md P1):
    # the held loop is blocked in a thread, and a restart would drop it the
    # way an ordinary restart drops any other in-flight work.
    try:
        from app.services import master_control
        mc_held = master_control.held() if master_control.is_paused() else []
        if mc_held:
            return f"master paused with {len(mc_held)} held: {', '.join(mc_held[:3])}"
    except Exception:  # noqa: BLE001 - unsure means busy, same as every other check here
        pass

    state = produce_queue.snapshot()
    if any(i.get("status") == "running" for i in state.get("items", [])):
        return "a production is running"
    if not state.get("paused") and any(i.get("status") == "queued" for i in state.get("items", [])):
        return "a production is waiting to run"
    if idle_offload._other_work_running():
        return "production work is running outside the queue"
    # A background job (a Shorts find, an auto story being narrated, an
    # audience run) holds `idle_offload.busy()`, not an HTTP request; it is
    # work all the same (2026-10-23: a restart mid-narration lost the job).
    try:
        jobs = int(idle_offload.status().get("in_flight") or 0)
    except Exception:  # noqa: BLE001
        jobs = 0
    if jobs:
        return f"{jobs} background job(s) running"
    # A reel rendering on BuzzEdit: a Studio restart takes a headless BuzzEdit down with
    # it (its Studio-pid watchdog), which killed a reel mid-render (2026-10-24 01:06).
    try:
        from integrations.buzzedit_client import BuzzEditClient
        client = BuzzEditClient()
        if client.vibe_reel_busy():
            return "BuzzEdit is rendering a reel"
        # Same reasoning for a narration (STUDIO_DIRECTOR_PLAN.md enhancement 2/5):
        # it holds BuzzEdit's GPU/process just as a reel render does.
        if client.narration_busy():
            return "BuzzEdit is narrating"
        # A render the Studio gave up on (wrongly called stuck, 2026-10-26)
        # keeps going on BuzzEdit; restarting would take it down with BuzzEdit.
        from app.api.produce_api import buzzedit_job_active
        if buzzedit_job_active():
            return "BuzzEdit is working a job"
    except Exception:  # noqa: BLE001 - BuzzEdit down: nothing of its to protect
        pass
    try:
        from app.services import video_slot
        if video_slot.waiting():
            return f"{len(video_slot.waiting())} video(s) waiting their turn"
    except Exception:  # noqa: BLE001
        pass
    with _lock:
        open_requests = _inflight
    if open_requests:
        return f"{open_requests} request(s) open"
    return None


def watch(restart: Callable[[], None], check_s: float = CHECK_S, quiet_s: float = QUIET_S) -> None:
    """Block until the source changed and the Studio has been idle for
    `quiet_s`; then call `restart` once and return."""
    global _pending
    started = code_mtime()
    idle_since: Optional[float] = None
    announced = False
    with _lock:
        _state["started"] = True
    while True:
        time.sleep(check_s)
        try:
            with _lock:
                _state["last_check_at"] = time.time()
            if code_mtime() <= started:
                continue
            if not announced:
                _pending = True
                logger.info("Code reload: backend source changed since start; the Studio restarts "
                            "itself at the first idle moment.")
                announced = True
            reason = busy_reason()
            with _lock:
                _state["busy_reason"] = reason
                _state["last_error"] = ""
            if reason:
                idle_since = None
                continue
            now = time.monotonic()
            idle_since = idle_since or now
            with _lock:
                _state["idle_since"] = time.time() - (now - idle_since)
            if now - idle_since < quiet_s:
                continue
            logger.warning("Code reload: idle for %.0f s on changed code; restarting the Studio.",
                           now - idle_since)
            restart()
            return
        except Exception as exc:  # noqa: BLE001 - never take the Studio down over this
            with _lock:
                _state["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Code reload check failed: %s", exc)
