"""Studio Director memory (docs/STUDIO_DIRECTOR_PLAN.md Part 4): the creator's
mission (goals, intentions, plans), the running conversation, past incidents
and the promises the Director made.

Everything lives under `studio_director.DIRECTOR_DIR` -- resolved at call
time, so a test that moves the directory moves this too:

    mission.md               the mission (seeded from prompts/director/mission_seed.md)
    conversation.jsonl       the last KEEP_TURNS chat turns
    conversation_summary.md  older turns, one line each
    incidents.jsonl          problem -> cause -> fix, and whether it worked
    promises.jsonl           what the Director said it would do / is waiting on
"""
import json
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

_LOCK = threading.RLock()
MISSION_CAP = 6000
REPLAY_TURNS = 8
REPLAY_CHARS = 3000
KEEP_TURNS = 40
SUMMARY_CAP = 4000
INCIDENTS_KEEP = 200
PROMISES_OPEN_MAX = 30
PROMISE_EXPIRE_DAYS = 14
MISSION_CONV_HEADING = "## From conversation"

_GOAL_RE = re.compile(r"\[GOAL:\s*(.*?)\]\s*(.*?)\s*\[/GOAL\]", re.I | re.S)
_PROMISE_RE = re.compile(r"\[PROMISE\]\s*(.*?)\s*\[/PROMISE\]", re.I | re.S)
_DONE_RE = re.compile(r"\[DONE:\s*([a-f0-9]{6,12})\]", re.I | re.S)
_TICKET_RE = re.compile(r"\[TICKET:\s*(.*?)\]\s*(.*?)\s*\[/TICKET\]", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _sd():
    from app.services import studio_director
    return studio_director


def _path(name: str) -> str:
    return os.path.join(_sd().DIRECTOR_DIR, name)


def _seed_path() -> str:
    from core.paths import PROMPTS_DIR
    return os.path.join(str(PROMPTS_DIR), "director", "mission_seed.md")


# --- mission ------------------------------------------------------------------------------

def read_mission() -> str:
    path = _path("mission.md")
    if not os.path.isfile(path):
        try:
            with open(_seed_path(), encoding="utf-8") as f:
                seed = f.read()
        except OSError:
            seed = "# The creator's mission\n\n## Goals\n(none yet)\n\n" + MISSION_CONV_HEADING + "\n(nothing yet)\n"
        _sd()._write_text(path, seed)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def mission_text(cap: int = MISSION_CAP) -> str:
    text = _COMMENT_RE.sub("", read_mission()).strip()
    if len(text) > cap:
        text = text[:cap] + "\n...(mission trimmed)"
    return text


def set_mission(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return read_mission()
    _sd()._write_text(_path("mission.md"), text + "\n")
    return text + "\n"


def append_goal(section: str, text: str) -> Dict[str, Any]:
    sd = _sd()
    allowed = ("Goals", "Intentions", "Upcoming plans", "Priorities", "Constraints")
    section = next((a for a in allowed if a.lower() == str(section or "").strip().lower()), "Goals")
    text = " ".join(str(text or "").split())[:300]
    with _LOCK:
        return _append_goal(sd, section, text)


def _append_goal(sd, section: str, text: str) -> Dict[str, Any]:
    current = read_mission()
    entry = f"- [{sd._now()}] **{section}**: {text}"
    m = re.search(rf"^{re.escape(MISSION_CONV_HEADING)}\s*$(.*?)(?=^##\s|\Z)", current, re.I | re.S | re.M)
    bullets: List[str] = []
    if m:
        bullets = [ln for ln in m.group(1).splitlines() if ln.strip().startswith("- ")]
    bullets.append(entry)
    bullets = bullets[-40:]
    new_section = MISSION_CONV_HEADING + "\n\n" + "\n".join(bullets) + "\n"
    if m:
        current = current[:m.start()] + new_section + current[m.end():]
    else:
        current = current.rstrip() + "\n\n" + new_section
    sd._write_text(_path("mission.md"), current)
    return {"section": section, "text": text}


# --- conversation -------------------------------------------------------------------------

def record_turn(role: str, text: str) -> None:
    with _LOCK:
        _record_turn(role, text)


def _record_turn(role: str, text: str) -> None:
    from app.services import director_knowledge
    sd = _sd()
    path = _path("conversation.jsonl")
    rows = sd._read_jsonl(path)
    rows.append({"at": sd._now(), "role": "director" if role == "director" else "user",
                 "text": director_knowledge._scrub(str(text or ""))[:2000]})
    if len(rows) > KEEP_TURNS:
        overflow, rows = rows[:-KEEP_TURNS], rows[-KEEP_TURNS:]
        _roll_into_summary(overflow)
    sd._write_jsonl(path, rows)


def _roll_into_summary(rows: List[Dict[str, Any]]) -> None:
    sd = _sd()
    path = _path("conversation_summary.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        lines = []
    he, day = "", ""
    for r in rows:
        text = " ".join(str(r.get("text") or "").split())[:140]
        if r.get("role") == "user":
            he, day = text, str(r.get("at") or "")[:10]
        else:
            lines.append(f"- [{day or str(r.get('at') or '')[:10]}] he: {he} / me: {text}")
            he, day = "", ""
    if he:
        lines.append(f"- [{day}] he: {he} / me: ")
    while lines and len("\n".join(lines)) > SUMMARY_CAP:
        lines.pop(0)
    sd._write_text(path, "\n".join(lines) + "\n")


def _summary() -> str:
    try:
        with open(_path("conversation_summary.md"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def conversation_messages() -> List[Dict[str, str]]:
    rows = _sd()._read_jsonl(_path("conversation.jsonl"))[-REPLAY_TURNS * 2:]
    msgs = [{"role": "assistant" if r.get("role") == "director" else "user", "content": str(r.get("text") or "")[:700]}
            for r in rows if r.get("text")]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    while msgs and msgs[-1]["role"] != "assistant":
        msgs.pop()
    while msgs and sum(len(m["content"]) for m in msgs) > REPLAY_CHARS:
        msgs.pop(0)
        while msgs and msgs[0]["role"] != "user":
            msgs.pop(0)
    return msgs


def clear_conversation() -> None:
    for name in ("conversation.jsonl", "conversation_summary.md"):
        try:
            os.remove(_path(name))
        except OSError:
            pass


# --- incidents ----------------------------------------------------------------------------

def add_incident(problem: str, symptoms: Any, cause: str, fix: str, worked: Optional[bool],
                 resolved: Any = None, ticket: Optional[str] = None) -> Dict[str, Any]:
    with _LOCK:
        return _add_incident(problem, symptoms, cause, fix, worked, resolved, ticket)


def _add_incident(problem: str, symptoms: Any, cause: str, fix: str, worked: Optional[bool],
                 resolved: Any = None, ticket: Optional[str] = None) -> Dict[str, Any]:
    sd = _sd()
    path = _path("incidents.jsonl")
    rows = sd._read_jsonl(path)
    row = {"id": uuid.uuid4().hex[:10], "at": sd._now(), "problem": str(problem or "")[:300],
           "symptoms": symptoms, "cause": str(cause or "")[:300], "fix": str(fix or "")[:300],
           "worked": worked, "resolved": resolved, "ticket": ticket}
    rows.append(row)
    sd._write_jsonl(path, rows[-INCIDENTS_KEEP:])
    return row


def list_incidents(k: int = 10) -> List[Dict[str, Any]]:
    return _sd()._read_jsonl(_path("incidents.jsonl"))[-k:]


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9_]{3,}", str(text or "").lower()))


def search_incidents(text: str, k: int = 3) -> List[Dict[str, Any]]:
    want = _tokens(text)
    scored = []
    for row in _sd()._read_jsonl(_path("incidents.jsonl")):
        have = _tokens(" ".join(str(row.get(f) or "") for f in ("problem", "symptoms", "cause", "fix")))
        score = len(want & have)
        if score > 0:
            score += 1 if row.get("worked") else 0
            scored.append((score, row))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [r for _, r in scored[:k]]


# --- promises -----------------------------------------------------------------------------

def add_promise(text: str) -> Dict[str, Any]:
    with _LOCK:
        return _add_promise(text)


def _add_promise(text: str) -> Dict[str, Any]:
    sd = _sd()
    path = _path("promises.jsonl")
    rows = sd._read_jsonl(path)
    row = {"id": uuid.uuid4().hex[:8], "at": sd._now(), "text": str(text or "")[:200], "state": "open"}
    rows.append(row)
    open_rows = [r for r in rows if r.get("state") == "open"]
    if len(open_rows) > PROMISES_OPEN_MAX:
        drop = {id(r) for r in open_rows[:len(open_rows) - PROMISES_OPEN_MAX]}
        rows = [r for r in rows if id(r) not in drop]
    sd._write_jsonl(path, rows)
    return row


def list_promises(state: str = "open") -> List[Dict[str, Any]]:
    with _LOCK:
        return _list_promises(state)


def _list_promises(state: str = "open") -> List[Dict[str, Any]]:
    sd = _sd()
    path = _path("promises.jsonl")
    rows = sd._read_jsonl(path)
    cutoff = (datetime.now() - timedelta(days=PROMISE_EXPIRE_DAYS)).isoformat(timespec="seconds")
    changed = False
    for r in rows:
        if r.get("state") == "open" and str(r.get("at") or "") < cutoff:
            r["state"] = "expired"
            changed = True
    if changed:
        sd._write_jsonl(path, rows)
    return [r for r in rows if not state or r.get("state") == state]


def close_promise(pid: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        return _close_promise(pid)


def _close_promise(pid: str) -> Optional[Dict[str, Any]]:
    sd = _sd()
    path = _path("promises.jsonl")
    rows = sd._read_jsonl(path)
    found = None
    for r in rows:
        if (r.get("id") == pid or (len(str(pid)) >= 6 and str(r.get("id") or "").startswith(str(pid))))                 and r.get("state") == "open":
            r["state"] = "done"
            r["closed_at"] = sd._now()
            found = r
            break
    if found:
        sd._write_jsonl(path, rows)
    return found


# --- tags in a reply ----------------------------------------------------------------------

def parse_tags(reply: str) -> Dict[str, List[Any]]:
    reply = reply or ""
    return {
        "goals": [(m.group(1).strip(), m.group(2).strip()) for m in _GOAL_RE.finditer(reply) if m.group(2).strip()],
        "promises": [m.group(1).strip() for m in _PROMISE_RE.finditer(reply) if m.group(1).strip()],
        "done": [m.group(1).lower() for m in _DONE_RE.finditer(reply)],
        "tickets": [(m.group(1).strip(), m.group(2).strip()) for m in _TICKET_RE.finditer(reply)],
    }


# --- what the Director is shown before every chat -----------------------------------------

def memory_section(message: str) -> str:
    promises = list_promises("open")[:10]
    prom = "\n".join(f"- ({p.get('id')}) {p.get('text')}" for p in promises) or "(none)"
    inc = []
    for r in search_incidents(message, 2):
        inc.append(f"- {r.get('problem')} -> {r.get('cause')} -> {r.get('fix')} "
                   f"({'worked' if r.get('worked') else 'did not work' if r.get('worked') is False else 'unverified'})")
    return (
        "## The creator's mission (his goals; serve them)\n" + mission_text() + "\n\n"
        "## What you promised / are waiting on\n" + prom + "\n\n"
        "## Earlier conversation (summary)\n" + (_summary()[-1500:] or "(none)") + "\n\n"
        "## Past incidents like this\n" + ("\n".join(inc) or "(none)") + "\n"
    )
