"""
Live progress for one Studio Assistant turn (2026-10-22).

A turn is one blocking POST: the strategist writes, then every delegation
(`[INVOKE_AGENT]`), web lookup, vault tag and studio tool it asked for runs
in order, and only then does the reply come back. With a local model that is
minutes of silence. The creator asked to see "time to time updates and
status" while it happens, so each turn is tracked here by a `turn_id` the
page makes up:

    tracker = chat_progress.start(turn_id, agent, channel)   # in run_chat
    with chat_progress.step("delegation", "FactChecker", task): ...
    chat_progress.finish(turn_id, "done")

`GET /api/studio/chat_progress/{turn_id}` returns the steps so far (the page
polls it every couple of seconds while the request is open) and every change
is also published on the event bus as `chat_progress`, so Dexter sees it.

The current turn is a ContextVar: `run_chat` runs in one worker thread from
start to end, so `process_agent_invocations` and the tag processors report
into it without a parameter on every signature, and a caller with no turn
(the unattended strategist runner, tests) costs nothing.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("buzzcaf_ai.chat_progress")

KEEP_SECONDS = 30 * 60      # a finished turn is readable this long (the page may re-poll)
MAX_TURNS = 200

_turns: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()
_current: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("chat_progress_turn", default=None)


def _publish(turn: Dict[str, Any]) -> None:
    try:
        from app.services.events import bus
        bus.publish("chat_progress", snapshot(turn["turn_id"]))
    except Exception as exc:  # the bus must never take a chat turn down
        logger.debug("chat_progress not published: %s", exc)


def _prune_locked(now: float) -> None:
    stale = [k for k, t in _turns.items() if t["status"] != "running" and now - t.get("ended", now) > KEEP_SECONDS]
    for k in stale:
        _turns.pop(k, None)
    if len(_turns) > MAX_TURNS:
        for k in sorted(_turns, key=lambda k: _turns[k]["started"])[: len(_turns) - MAX_TURNS]:
            _turns.pop(k, None)


def start(turn_id: Optional[str], agent: str, channel: str) -> Optional[str]:
    """Begin tracking a turn; returns the id (None when the caller gave none)."""
    turn_id = (turn_id or "").strip()[:80] or None
    if not turn_id:
        _current.set(None)
        return None
    now = time.time()
    with _lock:
        _prune_locked(now)
        _turns[turn_id] = {
            "turn_id": turn_id, "agent": agent, "channel": channel,
            "status": "running", "started": now, "updated": now, "ended": None,
            "steps": [],
        }
    _current.set(turn_id)
    _publish(_turns[turn_id])
    return turn_id


def current() -> Optional[str]:
    return _current.get()


def begin(kind: str, label: str, detail: str = "", turn_id: Optional[str] = None) -> Optional[int]:
    """Add a running step to the current turn; returns its index (None: no turn)."""
    turn_id = turn_id or _current.get()
    if not turn_id:
        return None
    now = time.time()
    with _lock:
        turn = _turns.get(turn_id)
        if not turn:
            return None
        index = len(turn["steps"])
        turn["steps"].append({
            "index": index, "kind": kind, "label": label, "detail": (detail or "")[:300],
            "status": "running", "started": now, "ended": None, "seconds": None, "note": "",
        })
        turn["updated"] = now
    _publish(turn)
    return index


def end(index: Optional[int], status: str = "done", note: str = "", turn_id: Optional[str] = None) -> None:
    turn_id = turn_id or _current.get()
    if index is None or not turn_id:
        return
    now = time.time()
    with _lock:
        turn = _turns.get(turn_id)
        if not turn or index >= len(turn["steps"]):
            return
        step = turn["steps"][index]
        step["status"] = status
        step["ended"] = now
        step["seconds"] = round(now - step["started"], 1)
        step["note"] = (note or "")[:300]
        turn["updated"] = now
    _publish(turn)


@contextmanager
def step(kind: str, label: str, detail: str = "") -> Iterator[Dict[str, Any]]:
    """`with step(...) as s:` -- done on exit, failed on an exception; set
    `s["note"]` / `s["status"]` inside to change what is recorded."""
    index = begin(kind, label, detail)
    record: Dict[str, Any] = {"note": "", "status": "done"}
    try:
        yield record
    except Exception as exc:
        end(index, "failed", str(exc)[:300])
        raise
    end(index, record.get("status") or "done", record.get("note") or "")


def note(text: str, kind: str = "note", turn_id: Optional[str] = None) -> None:
    """A step that is already over (a one-line fact, e.g. "3 tags skipped")."""
    index = begin(kind, text, turn_id=turn_id)
    end(index, "done", turn_id=turn_id)


def finish(turn_id: Optional[str], status: str = "done", note_text: str = "") -> None:
    turn_id = turn_id or _current.get()
    if not turn_id:
        return
    now = time.time()
    with _lock:
        turn = _turns.get(turn_id)
        if not turn:
            return
        for step_ in turn["steps"]:
            if step_["status"] == "running":
                step_["status"] = "failed" if status == "failed" else "done"
                step_["ended"] = now
                step_["seconds"] = round(now - step_["started"], 1)
        turn["status"] = status
        turn["ended"] = now
        turn["updated"] = now
        if note_text:
            turn["note"] = note_text[:300]
    _publish(turn)
    if _current.get() == turn_id:
        _current.set(None)


def snapshot(turn_id: str) -> Optional[Dict[str, Any]]:
    """What the page shows: the turn with elapsed seconds per step and in all."""
    with _lock:
        turn = _turns.get(turn_id)
        if not turn:
            return None
        now = time.time()
        steps: List[Dict[str, Any]] = []
        for s in turn["steps"]:
            item = dict(s)
            item["seconds"] = s["seconds"] if s["seconds"] is not None else round(now - s["started"], 1)
            steps.append(item)
        return {
            "turn_id": turn_id, "agent": turn["agent"], "channel": turn["channel"],
            "status": turn["status"], "started": turn["started"], "ended": turn["ended"],
            "elapsed": round((turn["ended"] or now) - turn["started"], 1),
            "note": turn.get("note", ""),
            "steps": steps,
        }


def steps_of(turn_id: Optional[str]) -> List[Dict[str, Any]]:
    """The finished step list for the reply payload ([] with no turn)."""
    snap = snapshot(turn_id) if turn_id else None
    return (snap or {}).get("steps") or []


def _reset_for_tests() -> None:
    with _lock:
        _turns.clear()
    _current.set(None)
