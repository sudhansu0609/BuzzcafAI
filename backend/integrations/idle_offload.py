"""Unload the local models the Studio used once nothing has run for a while.

Every LLM call, workflow run and production-queue item holds a `busy()` slot.
When the last slot is released and `idle_offload_seconds` (config, default
300; 0 turns it off) passes with no new work, the watcher unloads what the
Studio actually used since the last offload:

- LM Studio: `lms unload --all` (JIT-reloads on the next call)
- Ollama: `keep_alive: 0` on every resident model (reloads on demand)
- ComfyUI / BuzzEdit's Whisper: `clear_vram`, only when BuzzEdit has no job
- the headless BuzzEdit the Studio started: *stopped*, and with it its
  backend's RAM, Whisper and the ComfyUI it brought (the next use starts it
  again). Not while `buzzedit_keep_alive` is on or BuzzEdit's queue has a
  job -- then only its models are cleared

Nothing is unloaded while a nightly run holds its lock (it runs in its own
process on the same servers, and offloads when it ends).
- llama.cpp: the server is *stopped* -- the Studio cannot restart it, and it
  is BuzzCode's engine too, so only with `idle_offload_llamacpp: true`

Work done on BuzzEdit also unloads LM Studio, which BuzzEdit's own passes
use. A provider the Studio never touched is left alone. While offloaded,
/health does not auto-load the model back (`offloaded()`); the next real
call does.
"""
import functools
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Optional, Set

logger = logging.getLogger("buzzcaf_ai.idle_offload")

DEFAULT_IDLE_SECONDS = 300
# Checked often enough that "idle for 5 minutes" unloads at 5:00-5:10.
_POLL_SECONDS = 10
# A nightly run's lock younger than this means it is still going (nightly_run.py).
_NIGHTLY_LOCK_FRESH_S = 4 * 3600
# What the end-of-task offload unloads, whoever loaded it.
_EVERYTHING = ("lm_studio", "ollama", "comfyui")

_lock = threading.Lock()
_in_flight = 0
_last_activity = time.monotonic()
_used: Set[str] = set()
_offloaded = False
_watcher: Optional[threading.Thread] = None


def mark_used(provider: str) -> None:
    """Record that `provider` ("lm_studio", "ollama", "llamacpp", "comfyui",
    or "buzzedit" for a headless BuzzEdit the Studio launched) now holds a
    model or a process on this machine's behalf. Counts as activity."""
    global _offloaded, _last_activity
    with _lock:
        _used.add(provider)
        _last_activity = time.monotonic()
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
    the queue, a nightly run (its own process, on the same LM Studio and
    BuzzEdit; it offloads when it ends), or a BuzzEdit render nobody here is
    tracking."""
    from app.api import produce_api
    from app.services import produce_queue

    if produce_queue.running_item() is not None or produce_api.render_in_progress():
        return True
    if _nightly_running():
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
        # Recorded for the health page: this is the failure that kept every
        # model loaded for hours on 2026-10-22 and only a DEBUG line said so.
        with _lock:
            _health["last_error"] = f"work check: {type(exc).__name__}: {exc}"[:300]
        logger.warning("idle_offload: could not check for running work (%s); staying busy.", exc)
        return False
    with _lock:
        _health["last_error"] = ""
    with _lock:  # work may have started while we asked BuzzEdit
        if _in_flight or _last_activity != seen_activity:
            return False
        _used.difference_update(used)
        _offloaded = True
    if used & {"comfyui", "buzzedit"}:
        used.add("lm_studio")  # BuzzEdit's fluency/verify passes load Gemma there
    _offload(used, stop_buzzedit=True)
    return True


def offload_now(reason: str = "task finished") -> bool:
    """End of a production task: unload every local model right away rather
    than after the idle window -- the GPU policy (load a model on a cleared
    card, offload everything when the task is done). LM Studio, Ollama and
    ComfyUI are always included, whoever loaded them; llama.cpp only with
    `idle_offload_llamacpp` (it is BuzzCode's engine too). Skipped while other
    Studio work holds a `busy()` slot. Returns True when it offloaded.

    A skipped offload is not dropped: everything it would have unloaded is
    left to the idle watcher, which unloads it once that work is done. A
    headless BuzzEdit stays up here (the next queued item may need it) and is
    stopped by the watcher after the idle window."""
    global _offloaded
    everything = set(_EVERYTHING)
    if _flag("idle_offload_llamacpp", False):
        everything.add("llamacpp")  # _offload still re-checks the flag
    with _lock:
        if _in_flight:
            _used.update(everything)
            logger.info("offload_now(%s): other work in flight, leaving models loaded.", reason)
            return False
    # BuzzEdit's own work counts too: a transcription or render still running
    # there (one the Studio gave up on, or started from BuzzEdit's UI) uses
    # LM Studio for its fluency/verify passes and the GPU for Whisper. The
    # idle watcher offloads once BuzzEdit is quiet (`_other_work_running`).
    try:
        from app.api import produce_api
        if produce_api.buzzedit_job_active():
            with _lock:
                _used.update(everything)
            logger.info("offload_now(%s): BuzzEdit is still working, leaving models loaded.", reason)
            return False
    except Exception as exc:  # noqa: BLE001 - unsure means offload, as before
        logger.debug("offload_now: could not ask BuzzEdit (%s).", exc)
    with _lock:
        if _in_flight:
            _used.update(everything)
            return False
        used = set(_used) | everything
        _used.intersection_update({"buzzedit"})
        _offloaded = True
    logger.info("offload_now: %s -- unloading all models.", reason)
    _offload(used)
    return True


def _nightly_running() -> bool:
    from pathlib import Path

    from core.paths import KNOWLEDGE_DIR

    # KNOWLEDGE_DIR is a str (core/paths.py); as a Path operand this raised
    # TypeError on every check, which "unsure means busy" turned into: the
    # Studio never idle-offloaded and never restarted itself (2026-10-22).
    lock = Path(KNOWLEDGE_DIR) / "nightly" / "running.lock"
    try:
        return time.time() - lock.stat().st_mtime < _NIGHTLY_LOCK_FRESH_S
    except OSError:
        return False


def _buzzedit_hold() -> Optional[str]:
    """Why the headless BuzzEdit must stay up now, or None to stop it."""
    from app.api import produce_api
    from app.services import buzzedit_keepalive
    from integrations.buzzedit_client import BuzzEditUnavailable

    from integrations.buzzedit_client import BuzzEditTimeout

    if buzzedit_keepalive.enabled():
        return "kept alive"
    if produce_api._studio_using_buzzedit():
        return "a production is running on it"
    client = produce_api.BuzzEditClient()
    try:
        jobs = client.get_jobs().get("jobs") or []
    except BuzzEditTimeout:
        # Accepts connections, answers late: busy on the GPU, not hung.
        return "it is busy (slow to answer)"
    except BuzzEditUnavailable:
        jobs = []  # refusing connections after a whole idle window: gone or hung
    except Exception as exc:  # noqa: BLE001 - unsure means keep it
        return f"its queue could not be read ({exc})"
    if any(job.get("status") in ("pending", "running") for job in jobs):
        return "its queue has a job"
    # A transcription is not a scheduler job but holds the GPU just the same.
    try:
        if client.transcription_jobs():
            return "it is transcribing"
    except Exception:  # noqa: BLE001 - an older BuzzEdit without the endpoint
        pass
    # A vibe reel or a narration (Story Desk / nightly auto stories) is
    # neither a scheduler job nor a transcription, but holds BuzzEdit's GPU
    # and process just the same (Fable review row 5, STUDIO_DIRECTOR_PLAN.md
    # enhancement 2): the idle watcher must not take it down mid-job.
    try:
        if client.vibe_reel_busy():
            return "a reel is rendering"
    except Exception:  # noqa: BLE001 - an older BuzzEdit without the endpoint
        pass
    try:
        if client.narration_busy():
            return "a narration is running"
    except Exception:  # noqa: BLE001 - an older BuzzEdit without the endpoint
        pass
    return None


def _release_buzzedit(stop: bool, clear: bool) -> None:
    """Stop the headless BuzzEdit the Studio started (`stop`), else clear the
    models of the BuzzEdit that stays up (`clear`). One kept up for a reason
    that can pass is asked again one idle window later."""
    global _last_activity
    from app.api import produce_api
    from app.services import process_cleanup

    if stop:
        hold = _buzzedit_hold()
        if hold is None:
            killed = process_cleanup.stop_headless_buzzedit()
            if killed:
                logger.info("idle_offload: stopped the headless BuzzEdit the Studio started (%d process(es)).",
                            len(killed))
                return
        else:
            logger.info("idle_offload: leaving BuzzEdit running (%s); clearing its models.", hold)
            if hold != "kept alive":
                with _lock:
                    _used.add("buzzedit")
                    _last_activity = time.monotonic()
            clear = True
    if clear:
        produce_api.BuzzEditClient().clear_vram()


def _offload(used: Set[str], stop_buzzedit: bool = False) -> None:
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
    stop = stop_buzzedit and "buzzedit" in used
    if stop:
        # Master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): a held vibe-reel
        # job or a paused scheduler lives in BuzzEdit's own process -- the
        # idle watcher must never take it down while that hold is on, only
        # its models (still unloaded below via "comfyui").
        try:
            from app.services import master_control
            if master_control.is_paused():
                stop = False
        except Exception:  # noqa: BLE001 - unsure: do not risk a held job, stay soft
            stop = False
    if stop or "comfyui" in used:
        name = "BuzzEdit" if stop else "ComfyUI"
        steps.append((name, lambda _p, _c: _release_buzzedit(stop, "comfyui" in used)))
    logger.info("idle_offload: idle for %ss, unloading %s.", _idle_seconds(), ", ".join(n for n, _ in steps) or "nothing")
    for name, step in steps:
        try:
            step("idle", cfg)
        except Exception as exc:  # noqa: BLE001 - one stuck server must not block the others
            logger.warning("idle_offload: could not unload %s (%s).", name, exc)


#: For the health page (2026-10-22): when the watcher last looked, and the
#: last reason a check could not decide (`check_once` treats "unsure" as
#: busy, so an error here means nothing is ever offloaded).
_health: Dict[str, Any] = {"last_check_at": 0.0, "last_error": "", "last_offload_at": 0.0, "last_offload_reason": ""}


def status() -> Dict[str, Any]:
    with _lock:
        out = dict(_health)
        out.update({
            "watcher_alive": _watcher is not None and _watcher.is_alive(),
            "in_flight": _in_flight,
            "used": sorted(_used),
            "offloaded": _offloaded,
            "idle_for_s": round(time.monotonic() - _last_activity) if _last_activity else None,
        })
    out["idle_seconds_setting"] = _idle_seconds()
    return out


def _watch() -> None:
    while True:
        time.sleep(_POLL_SECONDS)
        try:
            with _lock:
                _health["last_check_at"] = time.time()
            if check_once():
                with _lock:
                    _health["last_offload_at"] = time.time()
                    _health["last_offload_reason"] = "idle"
        except Exception as exc:  # noqa: BLE001 - the watcher must outlive any one bad check
            with _lock:
                _health["last_error"] = f"{type(exc).__name__}: {exc}"[:300]
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
