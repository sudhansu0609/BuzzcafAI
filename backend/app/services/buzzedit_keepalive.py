"""Keep BuzzEdit running in the background while the Studio is open.

Off by default (BuzzEdit brings ComfyUI with it). When `buzzedit_keep_alive`
is on, the Studio starts the headless BuzzEdit shortly after launch and checks
every CHECK_S seconds, starting it again if it has stopped -- so eye-contact
correction, renders and the rest never find it missing. The Studio still stops
the BuzzEdit it started when it shuts down (app/services/process_cleanup.py).
"""
import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("buzzcaf_ai.buzzedit_keepalive")

SETTING = "buzzedit_keep_alive"
FIRST_CHECK_S = 20.0   # let the Studio finish starting first
CHECK_S = 60.0

# How long BuzzEdit may answer with ComfyUI unreachable (or stuck
# "down"/"repair_failed") before this watchdog says so -- and how often it
# repeats that, so a long outage logs once an hour rather than on every
# 60s poll. See the 2026-10-20 incident: an 8-day ComfyUI outage went
# unnoticed until the finished video had no B-roll.
COMFYUI_DOWN_WARN_AFTER_MIN = 15.0
COMFYUI_DOWN_WARN_EVERY_S = 3600.0

_started = False
_lock = threading.Lock()
_stop = threading.Event()
_comfyui_down_since: Optional[float] = None
_comfyui_last_warned: Optional[float] = None


def enabled() -> bool:
    try:
        from integrations.llm import load_config
        return bool(load_config().get(SETTING, False))
    except Exception:  # noqa: BLE001 - unreadable config means off
        return False


def set_enabled(value: bool) -> bool:
    from integrations.llm import load_config, save_config
    cfg = load_config()
    cfg[SETTING] = bool(value)
    save_config(cfg)
    if value:
        start()
        threading.Thread(target=check_once, name="buzzedit-keepalive-now", daemon=True).start()
    return bool(value)


def _buzzedit_alive() -> bool:
    """Whether a BuzzEdit process is there even though it did not answer: a
    headless tree the Studio started, or a backend the port ledger names
    whose pid is alive (one the creator opened)."""
    try:
        from app.services import process_cleanup
        if process_cleanup.headless_buzzedit_roots():
            return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Keep-alive: could not look for BuzzEdit processes (%s).", exc)
    try:
        from integrations import buzzcaf_ports
        record = buzzcaf_ports.entry("buzzedit") or {}
        return bool(record.get("pid")) and buzzcaf_ports._pid_alive(record["pid"])
    except Exception:  # noqa: BLE001
        return False


def _watch_comfyui(health: Dict[str, Any]) -> None:
    """BuzzEdit answered, but how long has ComfyUI itself been unreachable
    (or stuck "down"/"repair_failed")? Past COMFYUI_DOWN_WARN_AFTER_MIN, log
    it and publish `comfyui_down` on the event bus -- at most once an hour,
    so a long outage does not spam either."""
    global _comfyui_down_since, _comfyui_last_warned
    state = health.get("comfyui_state")
    connected = bool(health.get("comfyui_connected"))
    down = (not connected) or state in ("down", "repair_failed")
    now = time.time()
    if not down:
        _comfyui_down_since = None
        _comfyui_last_warned = None
        return
    if _comfyui_down_since is None:
        _comfyui_down_since = now
        return
    minutes = (now - _comfyui_down_since) / 60.0
    if minutes <= COMFYUI_DOWN_WARN_AFTER_MIN:
        return
    if _comfyui_last_warned is not None and now - _comfyui_last_warned < COMFYUI_DOWN_WARN_EVERY_S:
        return
    _comfyui_last_warned = now
    detail = str(health.get("comfyui_detail") or "")
    logger.warning("Keep-alive: ComfyUI has been unreachable for %.0f min (state=%s%s).",
                   minutes, state or "unknown", f", {detail}" if detail else "")
    try:
        from app.services.events import bus as event_bus
        event_bus.publish("comfyui_down", {"state": state, "detail": detail, "minutes": round(minutes, 1)})
    except Exception as exc:  # noqa: BLE001 - a missed event must not break the watchdog
        logger.debug("Keep-alive: could not publish comfyui_down (%s).", exc)


def check_once() -> bool:
    """Start BuzzEdit if keep-alive is on and it is not *running*. True when it is up.

    Not answering is not the same as not running: a BuzzEdit the Studio
    started that is still alive (its process tree is there) is busy -- Whisper,
    the cut planner, an ffmpeg join -- and is left alone. Treating one missed
    health probe as "not running" had this watchdog relaunch (and so kill) a
    BuzzEdit 30 minutes into a transcription, three times on 2026-10-20."""
    from integrations.buzzedit_client import BuzzEditClient
    health = BuzzEditClient().health()
    if health is not None:
        _watch_comfyui(health)
        return True
    if not enabled():
        return False
    if _buzzedit_alive():
        logger.info("Keep-alive: BuzzEdit is not answering but its process is alive; busy, leaving it alone.")
        return True
    logger.info("Keep-alive: BuzzEdit is not running; starting it in the background.")
    try:
        from app.api.produce_api import ensure_buzzedit_running
        ensure_buzzedit_running(timeout=90.0)
        return True
    except Exception as exc:  # noqa: BLE001 - try again on the next check
        logger.warning("Keep-alive: could not start BuzzEdit (%s); will retry.", exc)
        return False


def _loop() -> None:
    if _stop.wait(FIRST_CHECK_S):
        return
    while not _stop.is_set():
        if enabled():
            try:
                check_once()
            except Exception as exc:  # noqa: BLE001 - the watchdog must not die
                logger.debug("Keep-alive check failed: %s", exc)
        if _stop.wait(CHECK_S):
            return


def start() -> None:
    """Start the watchdog thread once (it idles while the setting is off)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name="buzzedit-keepalive", daemon=True).start()


def stop() -> None:
    _stop.set()
