"""One video at a time (creator rule 2026-10-26).

A video holds the slot from the moment its voice starts being made until its
production finishes: an Auto Story run holds it in this process (`turn()`)
until its production is queued, and from then on the queue item itself holds
it, queued or running. A paused item, a paused queue, a failed or finished one
hold nothing -- pausing the running video is how the creator lets the next one
start. Everything that waits does so in line, first come first served.

    active(exclude)    the video holding the slot, or None
    turn(...)          context manager: wait in line, hold the slot, release it
    other_holder(pid)  an in-process holder other than `pid` (the queue worker's check)

The API answers 409 `{"code": "video_running", ...}` to a start while the
slot is taken unless the caller passed `when_free`; the Studio page shows that
as the "another video is running" pop-up.
"""
import logging
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger("buzzcaf_ai.video_slot")

POLL_S = 15.0

_cond = threading.Condition()
_holders: Dict[str, Dict[str, Any]] = {}
_line: List[Dict[str, Any]] = []


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _queue_blocker(exclude: Optional[str]) -> Optional[Dict[str, Any]]:
    from app.services import produce_queue
    state = produce_queue.snapshot()
    items = state.get("items") or []
    for status in ("running", "queued"):
        if status == "queued" and state.get("paused"):
            break
        for it in items:
            if it.get("status") != status or it.get("project_id") == exclude:
                continue
            return {"project_id": it.get("project_id"), "title": it.get("title") or it.get("project_id"),
                    "brand": it.get("brand"), "what": "production" if status == "running" else "waiting in the queue",
                    "doing": it.get("message"), "progress_pct": round(float(it.get("progress") or 0) * 100),
                    "queue_item_id": it.get("id"), "status": status,
                    # The queue cannot pause a video BuzzEdit is rendering.
                    "can_pause": not (status == "running" and it.get("checkpoint") == "render")}
    return None


def _studio_project_for(buzzedit_project_id: Optional[str]) -> Dict[str, Any]:
    """The Studio project produced on BuzzEdit project `buzzedit_project_id`
    (its `metadata.buzzedit_project_id`), looked up through the queue items."""
    if not buzzedit_project_id:
        return {}
    try:
        from app.services import produce_queue
        from core.models.project import Project
        for it in reversed(produce_queue.snapshot().get("items") or []):
            try:
                p = Project.load(it.get("project_id"))
            except Exception:  # noqa: BLE001
                continue
            if (p.metadata or {}).get("buzzedit_project_id") == buzzedit_project_id:
                return {"id": p.id, "name": p.name, "brand": p.brand}
    except Exception:  # noqa: BLE001
        pass
    return {}


def _buzzedit_blocker() -> Optional[Dict[str, Any]]:
    """A render BuzzEdit is working on that the queue does not show as
    running: one it picked back up by itself after a restart, or one the
    Studio stopped following (2026-10-27: Harrison Okene rendered on while
    the queue was paused)."""
    try:
        from integrations.buzzedit_client import BuzzEditClient
        jobs = BuzzEditClient().get_jobs()
    except Exception:  # noqa: BLE001 - BuzzEdit down: nothing of its running
        return None
    current = jobs.get("current_job_id")
    if not current:
        return None
    job = next((j for j in jobs.get("jobs") or [] if (j.get("id") or j.get("job_id")) == current), {})
    studio = _studio_project_for(job.get("project_id"))
    return {"project_id": studio.get("id"), "title": studio.get("name") or "A video BuzzEdit is rendering",
            "brand": studio.get("brand") or "", "what": "rendering on BuzzEdit", "doing": job.get("message"),
            "progress_pct": round(float(job.get("progress") or 0) * 100), "queue_item_id": None,
            "status": "running", "can_pause": False}


def other_holder(project_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """An Auto Story run of another project holding the slot in this process.
    Read without the condition lock: the queue worker calls this under its
    own lock, and `active()` takes the two in the other order."""
    for pid, info in list(_holders.items()):
        if pid != project_id:
            return dict(info)
    return None


def active(exclude: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The video holding the slot (other than `exclude`), or None."""
    holder = other_holder(exclude)
    if holder:
        return holder
    try:
        blocker = _queue_blocker(exclude)
    except Exception as exc:  # noqa: BLE001 - an unreadable queue never blocks a start
        logger.warning("video_slot: queue unreadable (%s)", exc)
        blocker = None
    return blocker or _buzzedit_blocker_except(exclude)


def _buzzedit_blocker_except(exclude: Optional[str]) -> Optional[Dict[str, Any]]:
    found = _buzzedit_blocker()
    if found and exclude and found.get("project_id") == exclude:
        return None
    return found


def waiting() -> List[Dict[str, Any]]:
    with _cond:
        return [dict(w) for w in _line]


def busy_detail(info: Dict[str, Any]) -> Dict[str, Any]:
    """The 409 body for a start refused because `info` holds the slot."""
    pct = info.get("progress_pct")
    doing = info.get("doing") or info.get("what") or "being made"
    return {"code": "video_running",
            "message": (f"Another video is being made: '{info.get('title')}' ({doing}"
                        + (f", {pct}%" if pct else "") + "). Only one video is made at a time."),
            "active": info}


@contextmanager
def turn(project_id: str, *, title: str, brand: str = "", what: str = "voice",
         say: Callable[[str], None] = lambda _m: None,
         on_wait: Optional[Callable[[Dict[str, Any]], None]] = None) -> Iterator[None]:
    """Wait in line until no other video holds the slot, then hold it for the
    body. The master pause is honoured while waiting."""
    from app.services import master_control
    entry = {"project_id": project_id, "title": title, "brand": brand, "since": _now()}
    with _cond:
        if not any(w["project_id"] == project_id for w in _line):
            _line.append(entry)
    announced: Optional[str] = None
    try:
        while True:
            # Outside _cond: see other_holder(). A render of this project's own
            # queue item cannot be running while its voice is still to be made.
            blocker = _queue_blocker(project_id) or _buzzedit_blocker_except(project_id)
            with _cond:
                blocker = other_holder(project_id) or blocker
                first = _line[0]["project_id"] == project_id if _line else True
                if blocker is None and first:
                    _line[:] = [w for w in _line if w["project_id"] != project_id]
                    _holders[project_id] = {"project_id": project_id, "title": title, "brand": brand,
                                            "what": what, "doing": what, "since": _now(), "can_pause": False}
                    break
                ahead = blocker or dict(_line[0])
            if announced != ahead.get("title"):
                announced = ahead.get("title")
                say(f"Waiting for '{announced}' to finish (one video at a time)")
                logger.info("video_slot: %s waits for %s", project_id, announced)
                if on_wait:
                    try:
                        on_wait(ahead)
                    except Exception:  # noqa: BLE001 - a record write never breaks the wait
                        logger.exception("video_slot: on_wait failed for %s", project_id)
            master_control.wait_if_paused(f"video_slot: {project_id} waiting for its turn", say)
            with _cond:
                _cond.wait(timeout=POLL_S)
        yield
    finally:
        with _cond:
            _line[:] = [w for w in _line if w["project_id"] != project_id]
            _holders.pop(project_id, None)
            _cond.notify_all()
        try:
            from app.services import produce_queue
            produce_queue.kick()
        except Exception:  # noqa: BLE001
            pass


def reserve(project_id: str, *, title: str, brand: str = "") -> None:
    """Join the line now, before the waiting thread starts (a restart puts
    the waiting videos back in their old order)."""
    with _cond:
        if not any(w["project_id"] == project_id for w in _line):
            _line.append({"project_id": project_id, "title": title, "brand": brand, "since": _now()})


def set_doing(project_id: str, doing: str) -> None:
    """What the holder is doing now, for the pop-up and the Director."""
    info = _holders.get(project_id)
    if info is not None:
        info["doing"] = doing


def notify() -> None:
    """Something changed in the queue: let waiters look again now."""
    with _cond:
        _cond.notify_all()


def reset_for_tests() -> None:
    with _cond:
        _holders.clear()
        _line.clear()
        _cond.notify_all()
