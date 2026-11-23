"""Everything waiting on the creator, in one list (2026-10-26).

The creator found the Studio confusing: a project waiting for his voice
looked like work in progress, approvals sat on the Dashboard and the Story
Desk where he did not look, and the Director's approvals lived in their own
panel. `GET /api/needs_you` gathers them so the app can raise one bright
pop-up. Each item carries the buttons that settle it (a method, a path and a
body the frontend calls as-is), so the pop-up needs no per-kind logic.

Kinds, most urgent first:
- `publish`        an Auto Story video made by itself, waiting for Approve / Reject
- `step_approval`  a workflow step paused for his approval
- `review_gate`    a production parked at the cut / plan / effects review
- `director`       a Studio Director action waiting for Approve / Decline
- `voice`          a long video whose script is done and needs his voice
                   (record it, or let his cloned voice narrate it)
- `shorts_record`  one summary row: Shorts scripts waiting to be recorded

A project already in the production queue, or being narrated right now, is
not waiting on him and is left out.

Seen (2026-10-27): he can mark an item "seen it" (or dismiss them all): it
leaves the pop-up and never raises it again, but stays in the list as
`seen: true` until it is settled, so "show all pending" still finds it. The
marks live in `knowledge/needs_you/seen.json`; a mark whose item is gone is
dropped, so an item that comes back later is new again.
"""
import json
import os
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

#: Steps where a long video stops for his voice.
VOICE_STEPS = ("Voice Recording", "Ready to record")
#: Auto Story states that mean the cloned voice / take is being made now.
NARRATING_STATES = ("script", "narration", "take", "queued", "plan", "rendering", "producing", "publishing")
#: A narrating state older than this is a run that died, not one in progress.
NARRATING_STALE = timedelta(hours=4)
SHORTS_WORKFLOW = "shorts_ready"
GATE_LABEL = {"cut_review": "the cut", "plan_review": "the visual plan", "effects_review": "the effects sample"}


def _action(label: str, path: str, *, style: str = "default", body: Optional[Dict[str, Any]] = None,
            ask: Optional[str] = None, confirm: Optional[str] = None, background: bool = False) -> Dict[str, Any]:
    """One button. `ask` prompts for a reason sent as body.reason; `background`
    means the call can run long (a whole workflow step), so the pop-up fires it
    and moves on instead of waiting for the answer."""
    out: Dict[str, Any] = {"label": label, "method": "POST", "path": path, "style": style, "body": body or {}}
    if ask:
        out["ask"] = ask
    if confirm:
        out["confirm"] = confirm
    if background:
        out["background"] = True
    return out


def _projects() -> List[Dict[str, Any]]:
    import core.paths
    root = str(core.paths.PROJECTS_DIR)
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return out
    for pid in os.listdir(root):
        try:
            with open(os.path.join(root, pid, "project.json"), encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001 - a broken project just isn't listed
            continue
        if isinstance(data, dict):
            data.setdefault("id", pid)
            out.append(data)
    return out


def _narrating(project_id: str, rec: Dict[str, Any]) -> bool:
    from app.services import auto_story
    if project_id in auto_story._live:
        return True
    if rec.get("state") not in NARRATING_STATES:
        return False
    try:
        return datetime.now() - datetime.fromisoformat(str(rec.get("updated_at"))) < NARRATING_STALE
    except (TypeError, ValueError):
        return False


def _busy(project_id: str, rec: Dict[str, Any]) -> bool:
    from app.services import produce_queue
    try:
        if produce_queue.active_item_for(project_id):
            return True
    except Exception:  # noqa: BLE001 - a queue read error never hides an item
        pass
    from app.services import video_slot
    if any(w.get("project_id") == project_id for w in video_slot.waiting()):
        return True  # in line behind the video being made: started, not waiting on him
    return _narrating(project_id, rec)


_seen_lock = threading.Lock()


def _seen_path() -> str:
    from core.paths import KNOWLEDGE_DIR
    return os.path.join(str(KNOWLEDGE_DIR), "needs_you", "seen.json")


def _read_seen() -> Dict[str, str]:
    try:
        with open(_seen_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 - no file yet, or a broken one: nothing seen
        return {}


def _write_seen(seen: Dict[str, str]) -> None:
    path = _seen_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=1)
    os.replace(tmp, path)


def mark_seen(keys: List[str], seen: bool = True) -> Dict[str, Any]:
    """Marks `keys` seen (or, with `seen=False`, brings them back)."""
    with _seen_lock:
        marks = _read_seen()
        for key in keys or []:
            key = str(key).strip()
            if not key:
                continue
            if seen:
                marks.setdefault(key, datetime.now().isoformat(timespec="seconds"))
            else:
                marks.pop(key, None)
        _write_seen(marks)
    return collect()


def _last_step(project: Dict[str, Any]) -> Dict[str, Any]:
    history = project.get("steps_history") or []
    return history[-1] if history and isinstance(history[-1], dict) else {}


def collect() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    shorts: List[Dict[str, Any]] = []

    for p in _projects():
        pid = p["id"]
        if p.get("status") in ("completed", "archived"):
            continue
        meta = p.get("metadata") or {}
        rec = meta.get("auto_story") if isinstance(meta.get("auto_story"), dict) else {}
        name, brand = p.get("name") or pid, p.get("brand") or ""
        base = {"project_id": pid, "title": name, "brand": brand}
        last = _last_step(p)

        if (rec.get("review") or {}).get("state") == "needs_review":
            items.append({**base, "key": f"publish:{pid}", "kind": "publish", "tab": "story_desk",
                          "since": (rec.get("review") or {}).get("at") or rec.get("updated_at"),
                          "what": "Made by itself -- approve it to publish, or reject it.",
                          "actions": [
                              _action("Approve & publish", f"/api/auto_story/{pid}/approve", style="primary"),
                              _action("Reject", f"/api/auto_story/{pid}/reject", style="danger",
                                      ask="Why reject it? (teaches the Studio)"),
                          ]})
            continue

        if last.get("status") == "paused_for_approval":
            step = last.get("step_name") or p.get("current_step") or "a step"
            items.append({**base, "key": f"step:{pid}:{step}", "kind": "step_approval", "tab": "projects",
                          "since": last.get("started_at"),
                          "what": f"'{step}' is done and waits for your OK before the next step runs.",
                          "actions": [_action("Approve", f"/api/projects/{pid}/approve", style="primary",
                                              background=True)]})
            continue

        gate = meta.get("produce_gate") if isinstance(meta.get("produce_gate"), dict) else None
        if gate and gate.get("stage") in GATE_LABEL:
            stage = gate["stage"]
            items.append({**base, "key": f"gate:{pid}:{stage}", "kind": "review_gate", "tab": "projects",
                          "since": None,
                          "what": f"The production stopped for you to check {GATE_LABEL[stage]}.",
                          "actions": [_action("Looks good, continue", f"/api/projects/{pid}/produce_video/continue",
                                              style="primary", body={"stage": stage})]})
            continue

        if p.get("current_step") in VOICE_STEPS and not _busy(pid, rec):
            if p.get("workflow_name") == SHORTS_WORKFLOW:
                shorts.append({"project_id": pid, "title": name, "brand": brand, "created_at": p.get("created_at")})
                continue
            from app.services import auto_story
            cloned = not auto_story.voice_clone_paused()
            items.append({**base, "key": f"voice:{pid}", "kind": "voice", "tab": "projects",
                          "since": last.get("completed_at") or p.get("updated_at") or p.get("created_at"),
                          "what": ("The script is ready and needs your voice: record it, or let your cloned voice narrate it."
                                   if cloned else "The script is ready and needs your voice: record it."),
                          "actions": ([_action("Use my cloned voice", f"/api/auto_story/{pid}/run", style="primary",
                                               confirm=f"Narrate '{name}' in your cloned voice and produce it?")]
                                      if cloned else [])})

    try:
        from app.services import studio_director
        for row in studio_director.list_approvals("pending"):
            item = row.get("item") or {}
            aid = row.get("id")
            if not aid:
                continue
            label = item.get("title") or str(item.get("action") or "a Director action").replace("_", " ").capitalize()
            items.append({"key": f"director:{aid}", "kind": "director", "tab": "dashboard", "project_id": None,
                          "title": str(label), "brand": item.get("channel") or "",
                          "since": row.get("at"),
                          "what": str(item.get("why") or item.get("reason") or "The Studio Director asks before doing this."),
                          "actions": [
                              _action("Approve", f"/api/director/approvals/{aid}/approve", style="primary",
                                      background=True),
                              _action("Decline", f"/api/director/approvals/{aid}/decline", style="danger",
                                      ask="Why not? (optional)"),
                          ]})
    except Exception:  # noqa: BLE001 - the Director's file is optional
        pass

    try:
        from datetime import datetime
        from integrations import gemini_limit
        lim = gemini_limit.active()
        if lim:
            hhmm = lambda s: datetime.fromisoformat(str(s)).astimezone().strftime("%H:%M")  # noqa: E731
            est = " (estimated)" if lim.get("estimated") else ""
            items.append({"key": "gemini_rate_limit", "kind": "rate_limit", "tab": "dashboard", "project_id": None,
                          "title": "Gemini hit its rate limit", "brand": "", "since": lim.get("since"),
                          "what": (f"Since {hhmm(lim.get('since'))}. Next window about {hhmm(lim.get('until'))}{est}. "
                                   "Scripts are written by Gemma until then."),
                          "actions": []})
    except Exception:  # noqa: BLE001 - the limit file is optional
        pass

    if shorts:
        shorts.sort(key=lambda s: str(s.get("created_at") or ""))
        by_brand: Dict[str, int] = {}
        for s in shorts:
            by_brand[s["brand"]] = by_brand.get(s["brand"], 0) + 1
        items.append({"key": "shorts_record", "kind": "shorts_record", "tab": "projects", "project_id": None,
                      "title": f"{len(shorts)} Shorts scripts waiting to be recorded",
                      "brand": ", ".join(f"{b} {n}" for b, n in sorted(by_brand.items())),
                      "since": shorts[0].get("created_at"), "count": len(shorts),
                      "what": "Open the Shorts list to record them.", "actions": []})

    order = {"publish": 0, "step_approval": 1, "review_gate": 2, "director": 3, "voice": 4, "shorts_record": 5, "rate_limit": 6}
    items.sort(key=lambda i: (order.get(i["kind"], 9), str(i.get("since") or "")))
    with _seen_lock:
        marks = _read_seen()
        live = {i["key"] for i in items}
        if any(k not in live for k in marks):
            # Settled (or gone) items lose their mark: if one comes back, it is new.
            marks = {k: v for k, v in marks.items() if k in live}
            try:
                _write_seen(marks)
            except OSError:
                pass
    for item in items:
        item["seen"] = item["key"] in marks
        if item["seen"]:
            item["seen_at"] = marks[item["key"]]
    unseen = [i for i in items if not i["seen"]]
    return {"items": items, "count": len(items),
            "decisions": sum(1 for i in unseen if i["kind"] != "shorts_record"),
            "seen": len(items) - len(unseen)}
