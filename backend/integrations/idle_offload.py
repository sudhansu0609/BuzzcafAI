"""Unload the local models the Studio used once nothing has run for a while.

Every LLM call, workflow run and production-queue item holds a `busy()` slot.
When the last slot is released and `idle_offload_seconds` (config, default
300; 0 turns it off) passes with no new work, the watcher unloads what the
Studio actually used since the last offload:

- LM Studio: `lms unload --all` (JIT-reloads on the next call)
- Ollama: `keep_alive: 0` on every resident model (reloads on demand)
- ComfyUI / BuzzEdit's Whisper: `clear_vram`, only when BuzzEdit has no job
- llama.cpp: the server is *stopped* -- the Studio cannot restart it, and it
  is BuzzCode's engine too, so only with `idle_offload_llamacpp: true`

A provider the Studio never touched is left alone. While offloaded, /health
does not auto-load the model back (`offloaded()`); the next real call does.
"""
import functools
import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional, Set

logger = logging.getLogger("buzzcaf_ai.idle_offload")

DEFAULT_IDLE_SECONDS = 300
_POLL_SECONDS = 30

_lock = threading.Lock()
_in_flight = 0
_last_activity = time.monotonic()
_used: Set[str] = set()
_offloaded = False
_watcher: Optional[threading.Thread] = None


def mark_used(provider: str) -> None:
    """Record that `provider` ("lm_studio", "ollama", "llamacpp", "comfyui")
    now holds a model on this machine's behalf."""
    global _offloaded
    with _lock:
        _used.add(provider)
        _offloaded = False


@contextmanager
def busy():
    global _in_flight, _last_activity, _offloaded
    with _lock:
        _in_flight += 1
        _last_activity = time.monotonic()
        _offloaded = False
    try:
        yield
    finally:
        with _lock:
            _in_flight -= 1
            _last_activity = time.monotonic()


def tracked(fn: Callable) -> Callable:
    """Decorator form of `busy()`."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with busy():
            return fn(*args, **kwargs)
    return wrapper


def offloaded() -> bool:
    """True after an idle offload, until the next piece of work starts."""
    with _lock:
        return _offloaded


def _idle_seconds() -> int:
    from integrations.llm import load_config

    try:
        return max(0, int(load_config().get("idle_offload_seconds", DEFAULT_IDLE_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_IDLE_SECONDS


def _flag(key: str, default: bool) -> bool:
    from integrations.llm import load_config

    return str(load_config().get(key, default)).lower() not in ("false", "0", "no")


def _other_work_running() -> bool:
    """Work that does not pass through `busy()`: a produce run started outside
    the queue, or a BuzzEdit render nobody here is tracking."""
    from app.api import produce_api
    from app.services import produce_queue

    if produce_queue.running_item() is not None or produce_api.render_in_progress():
        return True
    return produce_api.buzzedit_job_active()


def check_once(now: Optional[float] = None) -> bool:
    """Offload if the Studio has been idle long enough. Returns True when it did."""
    global _offloaded
    limit = _idle_seconds()
    if not limit:
        return False
    now = time.monotonic() if now is None else now
    with _lock:
        if _in_flight or not _used or now - _last_activity < limit:
            return False
        used, seen_activity = set(_used), _last_activity
    try:
        if _other_work_running():
            return False
    except Exception as exc:  # noqa: BLE001 - unsure means busy
        logger.debug("idle_offload: could not check for running work (%s).", exc)
        return False
    with _lock:  # work may have started while we asked BuzzEdit
        if _in_flight or _last_activity != seen_activity:
            return False
        _used.difference_update(used)
        _offloaded = True
    _offload(used)
    return True


def offload_now(reason: str = "task finished") -> bool:
    """End of a production task: unload every local model right away rather
    than after the idle window -- the GPU policy (load a model on a cleared
    card, offload everything when the task is done). LM Studio, Ollama and
    ComfyUI are always included, whoever loaded them; llama.cpp only with
    `idle_offload_llamacpp` (it is BuzzCode's engine too). Skipped while other
    Studio work holds a `busy()` slot. Returns True when it offloaded."""
    global _offloaded
    with _lock:
        if _in_flight:
            logger.info("offload_now(%s): other work in flight, leaving models loaded.", reason)
            return False
    # BuzzEdit's own work counts too: a transcription or render still running
    # there (one the Studio gave up on, or started from BuzzEdit's UI) uses
    # LM Studio for its fluency/verify passes and the GPU for Whisper. The
    # idle watcher offloads once BuzzEdit is quiet (`_other_work_running`).
    try:
        from app.api import produce_api
        if produce_api.buzzedit_job_active():
            logger.info("offload_now(%s): BuzzEdit is still working, leaving models loaded.", reason)
            return False
    except Exception as exc:  # noqa: BLE001 - unsure means offload, as before
        logger.debug("offload_now: could not ask BuzzEdit (%s).", exc)
    with _lock:
        if _in_flight:
            return False
        used = set(_used) | {"lm_studio", "ollama", "comfyui"}
    if _flag("idle_offload_llamacpp", False):
        used.add("llamacpp")  # _offload still re-checks the flag
    with _lock:
        _used.clear()
        _offloaded = True
    logger.info("offload_now: %s -- unloading all models.", reason)
    _offload(used)
    return True


def _offload(used: Set[str]) -> None:
    from app.api import produce_api
    from integrations.llm import load_config

    cfg = load_config()
    steps = []
    if "lm_studio" in used:
        steps.append(("LM Studio", produce_api._unload_lm_studio))
    if "ollama" in used:
        steps.append(("Ollama", produce_api._unload_ollama))
    if "llamacpp" in used and _flag("idle_offload_llamacpp", False):
        steps.append(("llama.cpp", produce_api._stop_llamacpp))
    if "comfyui" in used:
        steps.append(("ComfyUI", lambda _p, _c: produce_api.BuzzEditClient().clear_vram()))
    logger.info("idle_offload: idle for %ss, unloading %s.", _idle_seconds(), ", ".join(n for n, _ in steps) or "nothing")
    for name, step in steps:
        try:
            step("idle", cfg)
        except Exception as exc:  # noqa: BLE001 - one stuck server must not block the others
            logger.warning("idle_offload: could not unload %s (%s).", name, exc)


def _watch() -> None:
    while True:
        time.sleep(_POLL_SECONDS)
        try:
            check_once()
        except Exception:  # noqa: BLE001 - the watcher must outlive any one bad check
            logger.exception("idle_offload: check failed")


def start() -> None:
    global _watcher
    with _lock:
        if _watcher is not None:
            return
        _watcher = threading.Thread(target=_watch, name="idle-offload", daemon=True)
    _watcher.start()


def reset_for_tests() -> None:
    global _in_flight, _last_activity, _offloaded
    with _lock:
        _in_flight = 0
        _last_activity = time.monotonic()
        _used.clear()
        _offloaded = False
