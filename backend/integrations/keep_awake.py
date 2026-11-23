"""Keep Windows from sleeping while a production runs.

`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` resets the
system idle timer for as long as the calling *thread* holds it, so the
production queue's worker thread calls `hold()` when an item starts and
`release()` when it ends. The display may still turn off; only sleep and
hibernation are held off. Nothing happens on other platforms, and a failure
here never reaches the caller -- a production that runs while the PC might
sleep is still better than one that does not run.

This holds off the OS's own idle sleep. A tool that puts the machine to sleep
explicitly (Sentinel's [power] rule did so after 180 idle minutes, 2026-10-17)
ignores it; that rule has to know about the queue itself.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger("buzzcaf_ai.keep_awake")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_AWAYMODE_REQUIRED = 0x00000040

_held_for: str = ""


def _set(flags: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))
    except Exception as exc:  # noqa: BLE001 - never the caller's problem
        logger.debug("SetThreadExecutionState failed (%s).", exc)
        return False


def hold(reason: str = "") -> bool:
    """Keep the system awake from this thread until `release()`."""
    global _held_for
    ok = _set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED) or _set(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    if ok:
        _held_for = reason
        logger.info("Keeping the PC awake for %s.", reason or "a production")
    return ok


def release() -> None:
    global _held_for
    if _held_for:
        logger.info("Released the keep-awake hold (%s).", _held_for)
    _held_for = ""
    _set(ES_CONTINUOUS)


def held_for() -> str:
    return _held_for
