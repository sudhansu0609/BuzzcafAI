"""
Master pause / resume for the whole Studio + BuzzEdit + the model servers
(docs/STUDIO_DIRECTOR_PLAN.md Part 1).

One switch holds every automated job at its nearest safe point -- the
production queue, Story Desk jobs, the long-form nightly run, story
adaptations, the Shorts Desk batch, the Audience Desk, the Instagram
scheduler, the nightly Windows task's own tasks, and BuzzEdit's scheduler and
vibe-reel renderer (mirrored over HTTP through `pause_buzzedit`/
`resume_buzzedit`) -- and releases every model so the memory is free while it
is held.

State is a small file (`CONFIG_DIR/master_control.json`, git-ignored like the
desktop shell's own runtime state): durable across a restart of either app or
the PC. `pause(mode, reason)` writes it, pauses BuzzEdit, then frees memory
(LM Studio, Ollama, ComfyUI, BuzzEdit's in-process models, the Studio's own
idle offload) -- in that order, so nothing new loads behind the hold.
`resume()` clears it and un-pauses `produce_queue` and BuzzEdit; nothing
preloads, exactly as an idle Studio behaves today.

Every long-running loop calls `wait_if_paused(where, say)` between its safe
points: it blocks (polling, logging once) while `is_paused()` and returns the
moment `resume()` runs -- the loop then carries on from its own checkpoint,
the same as it already does across a plain restart. An outside script (a
scheduled task, a scratchpad runner) polls `GET /api/master/state` instead;
see AGENTS.md.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

from core.paths import CONFIG_DIR

logger = logging.getLogger("buzzcaf_ai.master_control")

STATE_PATH = os.path.join(str(CONFIG_DIR), "master_control.json")

#: How often `wait_if_paused` polls the state file while a hold point is blocked.
POLL_S = 2.0

MODES = ("soft", "now")

_lock = threading.Lock()
#: where -> since (iso), every hold point currently blocked in `wait_if_paused`.
_held: Dict[str, str] = {}
_state_cache: Optional[Dict[str, Any]] = None


def _default() -> Dict[str, Any]:
    return {"paused": False, "since": None, "reason": "", "mode": "soft", "by": "", "resume_at": None, "prior": {}}


def _load() -> Dict[str, Any]:
    global _state_cache
    if _state_cache is not None:
        return _state_cache
    data: Dict[str, Any] = {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except Exception:  # noqa: BLE001 - no file yet, or unreadable: start fresh
        data = {}
    state = _default()
    state.update({k: v for k, v in data.items() if k in state})
    _state_cache = state
    return state


def _save(state: Dict[str, Any]) -> None:
    global _state_cache
    _state_cache = dict(state)
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except Exception as exc:  # noqa: BLE001 - the in-memory state still holds
        logger.warning("master_control: could not write %s (%s)", STATE_PATH, exc)


def is_paused() -> bool:
    with _lock:
        return bool(_load().get("paused"))


def current_mode() -> str:
    with _lock:
        return str(_load().get("mode") or "soft")


def held() -> List[str]:
    """Where work is sitting right now (hold points currently blocked)."""
    with _lock:
        return sorted(_held.keys())


def state() -> Dict[str, Any]:
    """The Dashboard / `GET /api/master/state` view: the durable fields plus
    what is held right now."""
    with _lock:
        data = dict(_load())
    data["held"] = held()
    data.setdefault("reason", "")
    data.pop("prior", None)
    return data


def _mark(where: str) -> None:
    with _lock:
        _held[where] = datetime.now().isoformat(timespec="seconds")


def _unmark(where: str) -> None:
    with _lock:
        _held.pop(where, None)


def wait_if_paused(where: str, say: Optional[Callable[[str], None]] = None) -> bool:
    """Block while the master pause is on; log once where this call is
    waiting. Returns True if it ever waited, so a caller can re-read its own
    state (a project, a job record) before going on, in case something else
    changed it while this was held.

    Never raises: a `say` callback that fails is logged and ignored rather
    than ending the hold.
    """
    if not is_paused():
        return False
    _mark(where)
    told = False
    try:
        while is_paused():
            if not told:
                msg = f"master pause: holding at {where}"
                logger.info(msg)
                if say:
                    try:
                        say(msg)
                    except Exception:  # noqa: BLE001 - a progress callback must never wedge a hold
                        logger.debug("master pause: progress callback for %s failed", where, exc_info=True)
                told = True
            time.sleep(POLL_S)
    finally:
        _unmark(where)
    return told


# ─────────────────────────────── BuzzEdit mirror ───────────────────────────────


def _pause_buzzedit(mode: str, reason: str = "", by: str = "") -> Dict[str, Any]:
    try:
        from integrations.buzzedit_client import BuzzEditClient
        return BuzzEditClient().master_pause(mode, reason, by) or {}
    except Exception as exc:  # noqa: BLE001 - BuzzEdit down is not a reason to fail the Studio's own pause
        logger.info("master pause: BuzzEdit not paused (%s)", exc)
        return {"error": str(exc)[:200]}


def _resume_buzzedit() -> Dict[str, Any]:
    try:
        from integrations.buzzedit_client import BuzzEditClient
        return BuzzEditClient().master_resume() or {}
    except Exception as exc:  # noqa: BLE001
        logger.info("master resume: BuzzEdit not resumed (%s)", exc)
        return {"error": str(exc)[:200]}


# ──────────────────────────────── memory release ───────────────────────────────


def _memory_snapshot() -> Dict[str, Any]:
    """RAM/VRAM free and what each local model server has loaded, best effort."""
    out: Dict[str, Any] = {"ram_free_mb": None, "vram_free_mb": None, "vram_total_mb": None,
                           "loaded_models": {"lm_studio": [], "ollama": []}}
    try:
        import psutil
        out["ram_free_mb"] = round(psutil.virtual_memory().available / (1024 * 1024))
    except Exception as exc:  # noqa: BLE001
        logger.debug("master_control: RAM read failed (%s)", exc)
    try:
        import shutil
        exe = shutil.which("nvidia-smi")
        if exe:
            text = subprocess.run(
                [exe, "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5, creationflags=_NO_WINDOW,
            ).stdout.strip()
            used, total = (float(p.strip()) for p in text.splitlines()[0].split(","))
            out["vram_total_mb"] = round(total)
            out["vram_free_mb"] = round(total - used)
    except Exception as exc:  # noqa: BLE001
        logger.debug("master_control: VRAM read failed (%s)", exc)
    try:
        from integrations.llm import get_loaded_lm_studio_models
        out["loaded_models"]["lm_studio"] = list(get_loaded_lm_studio_models() or [])
    except Exception as exc:  # noqa: BLE001
        logger.debug("master_control: LM Studio read failed (%s)", exc)
    try:
        from integrations.llm import ollama_resident_models
        out["loaded_models"]["ollama"] = [m.get("name") or m.get("model") for m in (ollama_resident_models() or [])]
    except Exception as exc:  # noqa: BLE001
        logger.debug("master_control: Ollama read failed (%s)", exc)
    return out


def _release_memory(reason: str) -> Dict[str, Any]:
    """LM Studio, Ollama and ComfyUI unload, the Studio's own idle offload --
    reusing `idle_offload.offload_now`, which already defers (and leaves the
    models marked for the idle watcher to catch) rather than unloading
    something mid-call. Returns {before, after, offloaded}."""
    before = _memory_snapshot()
    offloaded = False
    try:
        from integrations import idle_offload
        offloaded = bool(idle_offload.offload_now(reason))
    except Exception as exc:  # noqa: BLE001 - never fail the pause over the release
        logger.warning("master pause: release skipped (%s)", exc)
    after = _memory_snapshot()
    return {"before": before, "after": after, "offloaded": offloaded}


# ──────────────────────────────── pause / resume ───────────────────────────────


def pause(mode: str = "soft", reason: str = "", by: str = "", resume_at: Optional[str] = None) -> Dict[str, Any]:
    """Hold everything. Idempotent: pausing an already-paused Studio just
    updates the mode/reason/who (e.g. escalating "soft" to "now").

    `by` is who asked (the Dashboard, Dexter, the tray, a channel/username);
    `resume_at` is an optional ISO instant recorded for the UI only -- there
    is no scheduler that acts on it. A pause is never lifted by anything but
    an explicit `resume()` call; the Studio does not auto-resume."""
    mode = mode if mode in MODES else "soft"
    with _lock:
        data = _load()
        already = bool(data.get("paused"))
        if already:
            data["mode"] = mode
            if reason:
                data["reason"] = reason
            if by:
                data["by"] = by
            if resume_at is not None:
                data["resume_at"] = resume_at
            _save(data)
        else:
            prior: Dict[str, Any] = {}
            try:
                from app.services import produce_queue
                prior["produce_queue_paused"] = bool(produce_queue.snapshot().get("paused"))
                if not prior["produce_queue_paused"]:
                    produce_queue.set_paused(True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("master pause: produce_queue not paused (%s)", exc)
            data.update(paused=True, since=datetime.now().isoformat(timespec="seconds"),
                       reason=reason, mode=mode, by=by, resume_at=resume_at, prior=prior)
            _save(data)
    logger.warning("Master pause (%s) by %s: %s", mode, by or "unknown", reason or "no reason given")
    buzzedit = _pause_buzzedit(mode, reason, by)
    memory = _release_memory(f"master pause ({mode}): {reason}" if reason else f"master pause ({mode})")
    result = state()
    result["buzzedit"] = buzzedit
    result["memory"] = memory
    return result


def resume() -> Dict[str, Any]:
    """Let everything held continue from its own checkpoint. Models are not
    preloaded -- they load again on first use, as always. Only ever called
    explicitly (the API, the Dashboard, Dexter) -- nothing in this process
    calls it on a timer."""
    with _lock:
        data = _load()
        was_paused = bool(data.get("paused"))
        if was_paused:
            prior = dict(data.get("prior") or {})
            data.update(paused=False, since=None, reason="", mode="soft", by="", resume_at=None, prior={})
            _save(data)
    # `state()` re-acquires `_lock` -- never call it from inside the `with`
    # block above (a plain Lock is not reentrant; it deadlocked here once).
    if not was_paused:
        return state()
    try:
        from app.services import produce_queue
        if not prior.get("produce_queue_paused"):
            produce_queue.set_paused(False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("master resume: produce_queue not resumed (%s)", exc)
    buzzedit = _resume_buzzedit()
    logger.warning("Master resume: held work continues from its checkpoint.")
    result = state()
    result["buzzedit"] = buzzedit
    return result
