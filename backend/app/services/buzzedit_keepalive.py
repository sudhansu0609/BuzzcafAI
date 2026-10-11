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

logger = logging.getLogger("buzzcaf_ai.buzzedit_keepalive")

SETTING = "buzzedit_keep_alive"
FIRST_CHECK_S = 20.0   # let the Studio finish starting first
CHECK_S = 60.0

_started = False
_lock = threading.Lock()
_stop = threading.Event()


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


def check_once() -> bool:
    """Start BuzzEdit if keep-alive is on and it is not answering. True when it is up."""
    from integrations.buzzedit_client import BuzzEditClient
    if BuzzEditClient().health() is not None:
        return True
    if not enabled():
        return False
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
