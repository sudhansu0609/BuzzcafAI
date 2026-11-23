"""
The video-production queue: produce_video runs for any project, any channel,
one at a time (one GPU), with pause / resume / cancel / retry / restart.

Every run -- a fresh "Start video production", a review-gate continue, a
render re-attach -- is an item here, and a single worker thread drains the
queue in order. The worker only exists while there is runnable work: `kick()`
starts it, and it exits once nothing is left, so an idle Studio holds no
thread and a test can drive it synchronously.

Pausing is cooperative. The pipeline in `app/api/produce_api.py` calls
`checkpoint()` between its stages (after import, after transcription, after
visual planning); a pause or cancel request is honoured there, and the stage
to resume from is saved on the item, so "Resume" and "Retry" pick up where it
stopped instead of re-importing and re-transcribing. A BuzzEdit render itself
cannot be paused -- BuzzEdit's scheduler has no way to suspend a running job --
so once an item is rendering, "Pause queue" is what holds the next video.

State lives in `KNOWLEDGE_DIR/produce_queue.json` and survives a restart; an
item that was mid-run when the process died comes back as failed, ready to
retry from its last checkpoint.
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.produce_queue")

QUEUE_PATH = os.path.join(str(KNOWLEDGE_DIR), "produce_queue.json")

#: Where a run picks up. "start" imports the recording afresh; the rest map
#: to the checkpoints `produce_api` records between stages.
RESUME_POINTS = ("start", "transcribe", "plan", "finalize", "render")

#: Item states. `awaiting_review` is a run parked at a cut/plan review gate;
#: the continue endpoint moves it back to `queued`.
ACTIVE_STATES = ("queued", "running", "paused", "awaiting_review")
FINISHED_STATES = ("done", "failed", "cancelled")

#: An item that fails is put back in line by itself, from its last checkpoint,
#: until it has run this many times in all; only then does it stay failed for
#: the creator to look at. Every stage reuses what the earlier attempts made
#: (the imported recording, the eye-contact file, BuzzEdit's transcription
#: checkpoints, the visual plan, the generated pictures and clips), so a
#: retry costs the failed stage only. 2026-10-20: a transcription lost to a
#: BuzzEdit restart stayed "failed" overnight with nothing to do but retry.
AUTO_RETRY_ATTEMPTS = 4
#: Breathing room before a retry, so a BuzzEdit that crashed can come back
#: and a model that was unloaded is not reloaded in the same second.
AUTO_RETRY_DELAY_S = 60.0

#: How long the queue waits, before an item, for a BuzzEdit that has announced
#: it will restart itself onto changed code (its `/api/health` says
#: `reload_pending`). Its own reload needs an idle moment, and a queue that
#: starts the next item the instant the last one ends never gives it one.
RELOAD_WAIT_S = 300.0

_lock = threading.RLock()
_state: Optional[Dict[str, Any]] = None
_worker_active = False


class ProducePaused(Exception):
    """Raised at a checkpoint when the running item was asked to pause."""

    def __init__(self, resume_from: str):
        super().__init__(f"Paused before '{resume_from}'.")
        self.resume_from = resume_from


class ProduceCancelled(Exception):
    """Raised at a checkpoint when the running item was asked to cancel."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _open_stage(item: Dict[str, Any], stage: str) -> None:
    """Start timing `stage` on `item["stage_times"]` -- one entry per stage
    per attempt, so a resumed or retried run adds entries rather than
    overwriting the first try. Time spent waiting for a review or in the
    queue is not in any entry."""
    item.setdefault("stage_times", []).append(
        {"stage": stage, "started_at": _now(), "finished_at": None, "seconds": None, "outcome": None})


def _close_stage(item: Dict[str, Any], outcome: str, at: Optional[str] = None) -> None:
    """Stop the clock on the entry `_open_stage` left open, if any."""
    entry = next((e for e in reversed(item.get("stage_times") or []) if not e.get("finished_at")), None)
    if entry is None:
        return
    entry["finished_at"] = at or _now()
    entry["outcome"] = outcome
    try:
        started = datetime.fromisoformat(entry["started_at"])
        entry["seconds"] = max(0, int((datetime.fromisoformat(entry["finished_at"]) - started).total_seconds()))
    except (TypeError, ValueError):
        entry["seconds"] = None


def _load() -> Dict[str, Any]:
    """The queue, read once per process. An item still `running` on disk was
    cut off by a restart: it comes back failed, retryable from its checkpoint."""
    global _state
    if _state is not None:
        return _state
    state: Dict[str, Any] = {"paused": False, "items": []}
    try:
        with open(QUEUE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        state["paused"] = bool(data.get("paused"))
        state["items"] = [i for i in data.get("items") or [] if isinstance(i, dict) and i.get("id")]
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 - a corrupt queue must not take the Studio down
        logger.warning("produce_queue: could not read %s (%s); starting empty.", QUEUE_PATH, exc)
    for item in state["items"]:
        if item.get("status") == "running":
            # When it really stopped is unknown; the last write is the best guess.
            _close_stage(item, "interrupted", at=item.get("updated_at"))
            attempts = int(item.get("attempts") or 0)
            resume_from = item.get("checkpoint") or "start"
            if resume_from not in RESUME_POINTS:
                resume_from = "start"
            if attempts < AUTO_RETRY_ATTEMPTS and not item.get("cancel_requested"):
                # Back in line by itself: the Studio restarting (or crashing)
                # mid-run is no reason for the creator to press Retry in the
                # morning. Picks up from the last checkpoint once the queue is
                # kicked at startup.
                item.update(status="queued", resume_from=resume_from, finished_at=None,
                            checkpoint=None if resume_from == "start" else resume_from,
                            pause_requested=False, cancel_requested=False, auto_retry=True,
                            error=(f"Interrupted: the Studio stopped mid-run (attempt {attempts}). "
                                   f"Resuming from the '{resume_from}' stage."))
            else:
                item.update(status="failed", finished_at=_now(), pause_requested=False, cancel_requested=False,
                            error="Interrupted: the Studio stopped mid-run. Retry picks up from the last checkpoint.")
    _state = state
    return state


def _save() -> None:
    state = _load()
    os.makedirs(os.path.dirname(QUEUE_PATH), exist_ok=True)
    tmp = QUEUE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp, QUEUE_PATH)


def reset_for_tests() -> None:
    """Forget the in-memory queue so the next access re-reads `QUEUE_PATH`."""
    global _state, _worker_active
    with _lock:
        _state = None
        _worker_active = False


# ─────────────────────────────── reads ───────────────────────────────


def snapshot() -> Dict[str, Any]:
    with _lock:
        state = _load()
        return {
            "paused": state["paused"],
            "worker_active": _worker_active,
            "items": [dict(i) for i in state["items"]],
        }


def _find(item_id: str) -> Dict[str, Any]:
    for item in _load()["items"]:
        if item["id"] == item_id:
            return item
    raise KeyError(item_id)


def get(item_id: str) -> Dict[str, Any]:
    with _lock:
        return dict(_find(item_id))


def active_item_for(project_id: str) -> Optional[Dict[str, Any]]:
    """The project's one unfinished item, if any (a project is never queued twice)."""
    with _lock:
        for item in _load()["items"]:
            if item.get("project_id") == project_id and item.get("status") in ACTIVE_STATES:
                return dict(item)
    return None


def latest_item_for(project_id: str) -> Optional[Dict[str, Any]]:
    """The project's unfinished item, or else its most recently updated finished
    one -- what the queue panel shows for it, so the project panel can agree."""
    with _lock:
        mine = [i for i in _load()["items"] if i.get("project_id") == project_id]
    active = [i for i in mine if i.get("status") in ACTIVE_STATES]
    pool = active or mine
    if not pool:
        return None
    return dict(max(pool, key=lambda i: str(i.get("updated_at") or i.get("created_at") or "")))


def running_item() -> Optional[Dict[str, Any]]:
    with _lock:
        for item in _load()["items"]:
            if item.get("status") == "running":
                return dict(item)
    return None


# ─────────────────────────────── writes ───────────────────────────────


def _update(item_id: str, **fields: Any) -> Dict[str, Any]:
    item = _find(item_id)
    item.update(fields)
    item["updated_at"] = _now()
    _save()
    return dict(item)


def add(project_id: str, *, brand: str, title: str, recording_path: str,
        settings_override: Optional[Dict[str, Any]], mode: str, precut: bool,
        resume_from: str = "start", front: bool = False) -> Dict[str, Any]:
    """Queue a run. Raises ValueError if the project already has one."""
    with _lock:
        if active_item_for(project_id):
            raise ValueError("This project is already in the production queue.")
        item = {
            "id": uuid.uuid4().hex[:12],
            "project_id": project_id,
            "brand": brand,
            "title": title,
            "recording_path": recording_path,
            "settings_override": settings_override,
            "mode": mode,
            "precut": precut,
            "status": "queued",
            "resume_from": resume_from,
            "checkpoint": None if resume_from == "start" else resume_from,
            "pause_requested": False,
            "cancel_requested": False,
            "attempts": 0,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
            "started_at": None,
            "finished_at": None,
            "stage_times": [],
        }
        items = _load()["items"]
        items.insert(_front_index(items) if front else len(items), item)
        _save()
    kick()
    return dict(item)


def _front_index(items: List[Dict[str, Any]]) -> int:
    """Just after whatever is running: a resumed run goes ahead of new work,
    but never ahead of the one already on the GPU."""
    for idx, item in enumerate(items):
        if item.get("status") != "running":
            return idx
    return len(items)


def requeue(item_id: str, resume_from: str, front: bool = False) -> Dict[str, Any]:
    """Put a paused / parked / failed / cancelled item back in line."""
    if resume_from not in RESUME_POINTS:
        raise ValueError(f"Unknown resume point '{resume_from}'.")
    with _lock:
        item = _find(item_id)
        if item["status"] == "running":
            raise ValueError("This item is already running.")
        if item["status"] in FINISHED_STATES:
            other = active_item_for(item["project_id"])
            if other and other["id"] != item_id:
                raise ValueError("This project already has another run in the queue.")
        updated = _update(item_id, status="queued", resume_from=resume_from, error=None,
                          checkpoint=None if resume_from == "start" else resume_from,
                          pause_requested=False, cancel_requested=False, finished_at=None)
        if front:
            items = _load()["items"]
            items.remove(item)
            items.insert(_front_index(items), item)
            _save()
    kick()
    return updated


def pause(item_id: str) -> Dict[str, Any]:
    """Queued -> paused straight away; running -> paused at its next checkpoint."""
    with _lock:
        item = _find(item_id)
        if item["status"] == "queued":
            return _update(item_id, status="paused")
        if item["status"] == "running":
            if item.get("checkpoint") == "render":
                raise ValueError("BuzzEdit is already rendering this video and cannot pause mid-render. "
                                 "Pause the queue to hold the next video instead.")
            return _update(item_id, pause_requested=True)
        raise ValueError(f"A {item['status']} item cannot be paused.")


def resume(item_id: str) -> Dict[str, Any]:
    with _lock:
        item = _find(item_id)
        if item["status"] == "running" and item.get("pause_requested"):
            return _update(item_id, pause_requested=False)
        if item["status"] != "paused":
            raise ValueError(f"A {item['status']} item cannot be resumed.")
        resume_from = item.get("resume_from") or "start"
    return requeue(item_id, resume_from)


def cancel(item_id: str) -> Dict[str, Any]:
    """Anything unfinished -> cancelled; a running item stops at its next
    checkpoint (or, mid-render, stops being tracked)."""
    with _lock:
        item = _find(item_id)
        if item["status"] in FINISHED_STATES:
            raise ValueError(f"This item is already {item['status']}.")
        if item["status"] == "running":
            return _update(item_id, cancel_requested=True)
        return _update(item_id, status="cancelled", finished_at=_now(), pause_requested=False)


def retry(item_id: str) -> Dict[str, Any]:
    """A failed or cancelled run, from its last checkpoint."""
    with _lock:
        item = _find(item_id)
        if item["status"] not in ("failed", "cancelled"):
            raise ValueError("Only a failed or cancelled item can be retried.")
        resume_from = item.get("checkpoint") or "start"
    return requeue(item_id, resume_from)


def restart(item_id: str) -> Dict[str, Any]:
    """From scratch: re-import and re-transcribe the recording."""
    with _lock:
        item = _find(item_id)
        if item["status"] == "running":
            raise ValueError("Cancel this run before restarting it.")
        if not item.get("recording_path"):
            raise ValueError("This item has no recording path to restart from.")
        _update(item_id, checkpoint=None, attempts=0, stage_times=[])
    return requeue(item_id, "start")


def recut(item_id: str) -> Dict[str, Any]:
    """From the transcription on: the cut is planned again on BuzzEdit under
    the current rules (no Whisper), then visuals and the render follow. For a
    finished or stopped run whose cut rules changed since (2026-10-08)."""
    with _lock:
        item = _find(item_id)
        if item["status"] == "running":
            raise ValueError("Cancel this run before re-cutting it.")
        _update(item_id, checkpoint="transcribe", attempts=0, stage_times=[], recut=True)
    return requeue(item_id, "transcribe")


def consume_recut(item_id: str) -> None:
    """The re-cut has been handed to BuzzEdit: a later retry of this item must
    not plan the cut a second time."""
    with _lock:
        _update(item_id, recut=False)


def move(item_id: str, direction: str) -> Dict[str, Any]:
    with _lock:
        items = _load()["items"]
        item = _find(item_id)
        idx = items.index(item)
        step = -1 if direction == "up" else 1
        target = idx + step
        if 0 <= target < len(items) and items[target].get("status") != "running" and item["status"] != "running":
            items[idx], items[target] = items[target], items[idx]
            _save()
        return dict(item)


def remove(item_id: str) -> None:
    with _lock:
        item = _find(item_id)
        if item["status"] in ("running",):
            raise ValueError("Cancel this run before removing it.")
        _load()["items"].remove(item)
        _save()


def clear_finished() -> int:
    with _lock:
        state = _load()
        before = len(state["items"])
        state["items"] = [i for i in state["items"] if i.get("status") not in ("done", "cancelled")]
        _save()
        return before - len(state["items"])


def set_paused(paused: bool) -> None:
    with _lock:
        _load()["paused"] = paused
        _save()
    if not paused:
        kick()


# ─────────────────────── hooks called by the pipeline ───────────────────────


def checkpoint(project_id: str, resume_from: str) -> None:
    """Record that `project_id`'s running item can resume from `resume_from`,
    then honour any pause/cancel request. No-op for a run outside the queue."""
    with _lock:
        item = next((i for i in _load()["items"]
                     if i.get("project_id") == project_id and i.get("status") == "running"), None)
        if item is None:
            return
        _close_stage(item, "done")
        _update(item["id"], checkpoint=resume_from)
        if item.get("cancel_requested"):
            raise ProduceCancelled()
        if item.get("pause_requested") and resume_from != "render":
            raise ProducePaused(resume_from)
        _open_stage(item, resume_from)
        _save()
    if resume_from != "render":
        # The master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): held here,
        # between this item's own stages, on the worker thread -- never
        # inside `_lock`, so a snapshot or a cancel request is never blocked
        # by it. The render stage is not held here: BuzzEdit cannot suspend
        # a render mid-way (see the module docstring); a running render is
        # left to finish, same as the per-item pause already does.
        from app.services import master_control
        master_control.wait_if_paused(f"produce_queue: project {project_id} -> {resume_from}")


def cancel_requested(project_id: str) -> bool:
    with _lock:
        return any(i.get("project_id") == project_id and i.get("status") == "running"
                   and i.get("cancel_requested") for i in _load()["items"])


# ─────────────────────────────── worker ───────────────────────────────


def _next_runnable() -> Optional[Dict[str, Any]]:
    state = _load()
    if state["paused"]:
        return None
    for item in state["items"]:
        if item.get("status") == "running":
            return None  # one at a time
        if item.get("status") == "queued":
            # One video at a time (2026-10-26): another project's voice being
            # made holds the slot; its release kicks the worker again.
            from app.services import video_slot
            if video_slot.other_holder(item.get("project_id")):
                return None
            return item
    return None


def kick() -> None:
    """Start the worker if there is runnable work and none is draining yet."""
    global _worker_active
    with _lock:
        if _worker_active or _next_runnable() is None:
            return
        _worker_active = True
    threading.Thread(target=_drain, name="produce-queue", daemon=True).start()


def _await_buzzedit_reload() -> None:
    """Wait for a BuzzEdit restart that is pending on new code, so the next item
    runs on the code as it is now (the fixed editor, not the one that failed).
    A new pid answering, or the flag gone, ends the wait; RELOAD_WAIT_S ends it
    regardless. BuzzEdit down or not asked is not a reason to wait."""
    try:
        from integrations.buzzedit_client import BuzzEditClient
        client = BuzzEditClient()
        health = client.health()
        if not health or not health.get("reload_pending"):
            return
        old_pid = health.get("pid")
        logger.info("produce_queue: BuzzEdit has new code pending; waiting for it to restart "
                    "before the next item (up to %.0f s).", RELOAD_WAIT_S)
        deadline = time.time() + RELOAD_WAIT_S
        while time.time() < deadline:
            time.sleep(5.0)
            health = client.health()
            if health and (health.get("pid") != old_pid or not health.get("reload_pending")):
                logger.info("produce_queue: BuzzEdit is back on its new code (pid %s).", health.get("pid"))
                return
        logger.warning("produce_queue: BuzzEdit did not restart within %.0f s; going on with the one running.",
                       RELOAD_WAIT_S)
    except Exception as exc:  # noqa: BLE001 - a courtesy wait, never a reason not to run
        logger.debug("produce_queue: reload wait skipped (%s)", exc)


def _drain() -> None:
    global _worker_active
    try:
        while True:
            if _next_runnable() is not None:
                _await_buzzedit_reload()
            with _lock:
                item = _next_runnable()
                if item is None:
                    _worker_active = False
                    return
                _open_stage(_find(item["id"]), item.get("resume_from") or "start")
                _update(item["id"], status="running", started_at=_now(), error=None,
                        attempts=int(item.get("attempts") or 0) + 1)
                item = dict(item)
            retrying = _run(item)
            from app.services import video_slot
            video_slot.notify()
            if retrying and AUTO_RETRY_DELAY_S > 0:
                time.sleep(AUTO_RETRY_DELAY_S)
    except Exception:  # noqa: BLE001 - the worker must never wedge the flag on
        logger.exception("produce_queue: worker crashed")
        with _lock:
            _worker_active = False


def _run(item: Dict[str, Any]) -> None:
    from integrations import idle_offload, keep_awake

    # Windows must not sleep under a production: an idle-timer sleep mid-render
    # took ComfyUI's GPU context with it (2026-10-17). Held for this thread
    # until the item ends, whatever way it ends.
    keep_awake.hold(f"production item {item.get('id')}")
    try:
        return _run_item(item)
    finally:
        keep_awake.release()
        # GPU policy: once a production task ends (done, failed, paused or
        # cancelled), every model it loaded is offloaded straight away.
        try:
            idle_offload.offload_now(f"production item {item.get('id')} finished")
        except Exception as exc:  # noqa: BLE001 - offload must never fail the queue
            logger.warning("offload after production item failed: %s", exc)


def _run_item(item: Dict[str, Any]) -> bool:
    """Run one item. True when it failed and was put back in line to retry
    by itself (the worker then waits `AUTO_RETRY_DELAY_S` before going on)."""
    from app.api import produce_api

    from integrations import idle_offload

    item_id = item["id"]
    try:
        idle_offload.mark_used("comfyui")
        with idle_offload.busy():
            outcome = produce_api.run_queue_item(item)
    except ProducePaused as paused:
        with _lock:
            _close_stage(_find(item_id), "paused")
            _update(item_id, status="paused", resume_from=paused.resume_from, pause_requested=False)
        return False
    except ProduceCancelled:
        with _lock:
            _close_stage(_find(item_id), "cancelled")
            _update(item_id, status="cancelled", finished_at=_now(), cancel_requested=False)
        return False
    except Exception as exc:  # noqa: BLE001 - recorded on the item, surfaced in the UI
        with _lock:
            current = _find(item_id)
            _close_stage(current, "failed")
            attempts = int(current.get("attempts") or 0)
            # An error that says the creator must act first (`retryable =
            # False` on the exception, e.g. a session whose greeting was not
            # found) is final at once: another run would find the same thing.
            retryable = getattr(exc, "retryable", True) is not False
            if retryable and attempts < AUTO_RETRY_ATTEMPTS and not current.get("cancel_requested"):
                resume_from = current.get("checkpoint") or "start"
                if resume_from not in RESUME_POINTS:
                    resume_from = "start"
                note = (f"Attempt {attempts} of {AUTO_RETRY_ATTEMPTS} failed at the '{resume_from}' stage "
                        f"({str(exc)[:300]}); retrying from there in {int(AUTO_RETRY_DELAY_S)}s.")
                logger.warning("produce_queue: item %s (%s) %s", item_id, current.get("project_id"), note)
                _update(item_id, status="queued", resume_from=resume_from, error=note,
                        checkpoint=None if resume_from == "start" else resume_from,
                        pause_requested=False, finished_at=None, auto_retry=True)
                items = _load()["items"]
                items.remove(current)
                items.insert(_front_index(items), current)
                _save()
                try:
                    produce_api._set_status(current["project_id"], state="queued", message=note)
                except Exception:  # noqa: BLE001 - the status line is a courtesy
                    pass
                return True
            _update(item_id, status="failed", error=str(exc), finished_at=_now(),
                    pause_requested=False, cancel_requested=False, auto_retry=False)
        return False
    with _lock:
        _close_stage(_find(item_id), "awaiting_review" if outcome == "awaiting_review" else "done")
        if outcome == "awaiting_review":
            _update(item_id, status="awaiting_review", pause_requested=False)
        else:
            _update(item_id, status="done", finished_at=_now(), pause_requested=False, cancel_requested=False)
    return False
