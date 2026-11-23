"""Studio Director (docs/STUDIO_DIRECTOR_PLAN.md Part 3): one master agent on
the Dashboard that sees every channel and job, plans the day/week, acts
through the Studio's own services (making content by itself), asks before
publishing/deleting/changing settings, learns from the creator's decisions,
and writes a morning briefing.

    snapshot()        one compact JSON view of the whole Studio
    plan(horizon)      the strategist tool loop (app/services/strategist_runner.py)
                       over the snapshot -> {"items": [...]}, stored under
                       knowledge/director/plans/<date>.json
    act(plan)          runs a plan's MAKE items one at a time through the
                       existing services; anything else becomes an approval
                       request (knowledge/director/approvals.jsonl)
    learn()            decisions + approvals + Audience Desk -> per-channel
                       rules distilled into knowledge/director/rules.md
    briefing(date)      the morning briefing markdown
    ask(message)        a chat turn with the Director

Only the eight `MAKE_ALLOWLIST` actions ever run unattended; everything else
-- publishing, deleting, a settings change, an Instagram/YouTube post, a
nightly scheduler toggle -- becomes an approval request that only runs once
the creator approves it on the Dashboard. Every hold point here calls
`master_control.wait_if_paused` the same way the rest of the Studio does, so
the Director itself holds while the master pause is on.
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.studio_director")

AGENT_NAME = "StudioDirector"

#: Kept in the order the creator named the channels (STUDIO_DIRECTOR_PLAN.md D1 brief).
CHANNELS = ["Raat3Baje", "Beyond3Baje", "Life3Baje", "Khayal3Baje", "TheTallStoryteller", "Originals"]

DIRECTOR_DIR = os.path.join(str(KNOWLEDGE_DIR), "director")

#: Content-making actions the Director can run by itself, one at a time,
#: through the existing services (they already sequence the GPU). An action
#: not in this set is never run unattended -- it always becomes an approval
#: request, whatever the plan item's own `needs_approval` said.
MAKE_ALLOWLIST = (
    "auto_story_make", "auto_story_make_mood_reel", "longform_run_slot",
    "story_adapt_start", "story_adapt_resume", "produce_queue_add",
    "retry_step", "retry_record",
)

#: A long-form item the Director will not finish without the creator's own
#: on-camera intro -- not a MAKE action, so it always becomes "needs you".
NEEDS_INTRO_ACTION = "needs_intro"

CREATOR_SECTION_HEADING = "## Creator's rules"
CONVERSATION_SECTION_HEADING = "## From conversation"
LEARNED_SECTION_HEADING = "## Learned from use"

DEFAULT_SETTINGS: Dict[str, Any] = {
    # Off until the creator turns it on from the Dashboard (STUDIO_DIRECTOR_PLAN.md D3):
    # the nightly task still learns, briefs and plans with this off, it just
    # never runs a MAKE item by itself.
    "autoplan": False,
    # Which model answers the Director's chat and plan: "" = the Studio's selection.
    "provider": "",
}

PROVIDERS = ("", "claude", "gemini", "lm_studio")

#: Rough nightly render budget referenced in the planning task (hours); not a
#: hard limit -- the Director is told to spend it in `why`, the services
#: themselves are what actually gate the GPU.
GPU_HOUR_BUDGET = 6.0


def _noop(_msg: str) -> None:
    pass


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().date().isoformat()


# --- small JSON/text helpers (atomic writes, like the rest of the Studio) ----------------

def _write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _plans_dir() -> str:
    return os.path.join(DIRECTOR_DIR, "plans")


def _briefings_dir() -> str:
    return os.path.join(DIRECTOR_DIR, "briefings")


def _plan_path(day: str) -> str:
    return os.path.join(_plans_dir(), f"{day}.json")


def _briefing_path(day: str) -> str:
    return os.path.join(_briefings_dir(), f"{day}.md")


def _rules_path() -> str:
    return os.path.join(DIRECTOR_DIR, "rules.md")


def _approvals_path() -> str:
    return os.path.join(DIRECTOR_DIR, "approvals.jsonl")


def _settings_path() -> str:
    return os.path.join(DIRECTOR_DIR, "settings.json")


def _decisions_log_path() -> str:
    """The same `knowledge/decisions/log.jsonl` `auto_story._log_decision`
    writes to -- read-only from here, so this module stays decoupled from
    `auto_story`'s own internals (another agent is editing that file)."""
    return os.path.join(str(KNOWLEDGE_DIR), "decisions", "log.jsonl")


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def _write_jsonl(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp, path)


# --- settings (the "Auto-plan nightly" toggle) --------------------------------------------

def settings() -> Dict[str, Any]:
    data = _read_json(_settings_path(), {}) or {}
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return out


def set_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    if "provider" in (patch or {}) and patch["provider"] not in PROVIDERS:
        raise ValueError("provider must be one of: '', 'claude', 'gemini', 'lm_studio'")
    if (patch or {}).get("provider") == "gemini":
        from integrations.llm import load_config, is_local_gemini
        cfg = load_config()
        if cfg.get("local_only") and not is_local_gemini(cfg):
            raise ValueError("Gemini cloud is blocked while Strict Local is on")
    current = settings()
    current.update({k: v for k, v in (patch or {}).items() if k in DEFAULT_SETTINGS})
    _write_json(_settings_path(), current)
    return current


def _llm(purpose: str):
    from integrations.llm import LLMService
    return LLMService(forced_provider=settings().get("provider") or None, purpose=purpose)


# --- snapshot: one compact view of the whole Studio ----------------------------------------

def _queued_project_ids() -> set:
    try:
        from app.services import produce_queue
        return {it.get("project_id") for it in produce_queue.snapshot().get("items") or []
                if it.get("status") in ("running", "queued", "paused")}
    except Exception:  # noqa: BLE001
        return set()


def _auto_story_channel_view() -> Dict[str, Any]:
    channels: Dict[str, Any] = {ch: {"recent": [], "needs_review": [], "failed": []} for ch in CHANNELS}
    try:
        from app.services import auto_story
        records = auto_story.list_records()
    except Exception as exc:  # noqa: BLE001 - a broken subsystem is itself a finding
        return {"error": str(exc)[:200], "channels": channels}
    in_queue = _queued_project_ids()
    for r in records:
        ch = r.get("brand") or "?"
        bucket = channels.setdefault(ch, {"recent": [], "needs_review": [], "failed": []})
        entry = {k: r.get(k) for k in ("project_id", "name", "format", "state", "updated_at", "error")}
        if r.get("project_id") in in_queue:
            # The record is older than the queue: a project being produced is
            # not failed, whatever its Auto Story record last said.
            entry.update(state="in production queue", error=None)
            bucket["recent"].append(entry)
            continue
        bucket["recent"].append(entry)
        if (r.get("review") or {}).get("state") == "needs_review":
            bucket["needs_review"].append(entry)
        if r.get("state") == "failed" or r.get("error"):
            bucket["failed"].append({**entry, "reason": r.get("error")})
    for bucket in channels.values():
        bucket["recent"] = bucket["recent"][:5]
        bucket["failed"] = bucket["failed"][:5]
    return {"channels": channels}


def _commit_memory() -> Dict[str, Any]:
    """Windows commit (RAM + page file) in use. A full commit, not low free
    RAM, is what crashes ComfyUI and the Studio window (2026-10-26)."""
    try:
        import ctypes

        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        st = _Status()
        st.dwLength = ctypes.sizeof(_Status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return {}
        gb = 1024 ** 3
        limit = st.ullTotalPageFile / gb
        return {"commit_used_gb": round(limit - st.ullAvailPageFile / gb, 1), "commit_limit_gb": round(limit, 1),
                "ram_free_gb": round(st.ullAvailPhys / gb, 1)}
    except Exception:  # noqa: BLE001 - not Windows, or no kernel32
        return {}


def right_now() -> Dict[str, Any]:
    """What is happening this minute, live: the production queue with its own
    progress, voices being made, what waits on him, the pause, memory, open
    promises and the latest incidents. Put first in the snapshot so it is never
    cut off; the rest of the snapshot is records that may be older."""
    now: Dict[str, Any] = {}
    try:
        from app.services import produce_queue
        items = produce_queue.snapshot().get("items") or []
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        now["production"] = [
            {"title": it.get("title"), "brand": it.get("brand"), "status": it.get("status"),
             "doing": it.get("message"), "progress_pct": round(float(it.get("progress") or 0) * 100),
             "stage": it.get("checkpoint"), "attempts": it.get("attempts"), "started_at": it.get("started_at"),
             "error": it.get("error")}
            for it in items
            if it.get("status") in ("running", "queued", "paused")
            or str(it.get("finished_at") or "") >= cutoff][:8]
    except Exception as exc:  # noqa: BLE001
        now["production"] = {"error": str(exc)[:200]}
    try:
        from app.services import auto_story
        now["voices_being_made"] = [r.get("name") or r.get("project_id") for r in auto_story.list_records()
                                    if r.get("state") == "narration"][:10]
        from integrations.buzzedit_client import BuzzEditClient
        busy = BuzzEditClient()._get("/api/narration/busy", timeout=(2, 5)).json()
        if busy.get("busy") and busy.get("job_id"):
            job = BuzzEditClient()._get(f"/api/narration/jobs/{busy['job_id']}", timeout=(2, 5)).json()
            now["voice_engine"] = {"project": os.path.basename(os.path.dirname(str(job.get("out_dir") or ""))),
                                   "doing": job.get("message"),
                                   "progress_pct": round(float(job.get("progress") or 0) * 100)}
        else:
            now["voice_engine"] = "idle"
    except Exception as exc:  # noqa: BLE001
        now.setdefault("voices_being_made", [])
        now["voice_engine"] = {"error": str(exc)[:160]}
    try:
        from app.services import video_slot
        # One video at a time: the ones started but waiting their turn.
        now["videos_in_line"] = [w.get("title") for w in video_slot.waiting()]
    except Exception as exc:  # noqa: BLE001
        now["videos_in_line"] = {"error": str(exc)[:160]}
    try:
        from app.services import needs_you
        now["waiting_for_you"] =[{"kind": i.get("kind"), "title": i.get("title")}
                                  for i in (needs_you.collect().get("items") or [])][:10]
    except Exception as exc:  # noqa: BLE001
        now["waiting_for_you"] = {"error": str(exc)[:200]}
    try:
        from app.services import master_control
        st = master_control.state()
        now["master_pause"] = {k: st.get(k) for k in ("paused", "mode", "by", "since")}
        mem = master_control._memory_snapshot()
        now["memory"] = {**_commit_memory(), "vram_free_mb": mem.get("vram_free_mb"),
                         "vram_total_mb": mem.get("vram_total_mb"), "llms_loaded": mem.get("loaded_models")}
    except Exception as exc:  # noqa: BLE001
        now["memory"] = {**_commit_memory(), "error": str(exc)[:160]}
    try:
        from app.services import director_memory
        now["open_promises"] = [p.get("text") for p in director_memory.list_promises("open")][:8]
        now["recent_incidents"] = [{k: i.get(k) for k in ("at", "problem", "cause", "fix")}
                                   for i in director_memory.list_incidents(4)]
    except Exception as exc:  # noqa: BLE001
        now["open_promises"] = {"error": str(exc)[:160]}
    return now


def snapshot() -> Dict[str, Any]:
    """One compact JSON view of the whole Studio for the Director to plan
    from. Every section is best-effort: a subsystem that fails to answer is
    recorded as an `"error"` string rather than breaking the rest of the
    snapshot."""
    out: Dict[str, Any] = {"at": _now(), "right_now": right_now(), "channels": {}}
    try:
        from integrations.llm import load_config
        cfg = load_config()
        out["llm"] = {"selected_provider": cfg.get("selected_provider"),
                      "director_provider": settings().get("provider") or "",
                      "local_only": cfg.get("local_only")}
    except Exception as exc:  # noqa: BLE001
        out["llm"] = {"error": str(exc)[:200]}
    try:
        from app.services import director_knowledge
        out["errors_24h"] = director_knowledge.log_digest(24)[:5]
    except Exception as exc:  # noqa: BLE001
        out["errors_24h"] = {"error": str(exc)[:200]}

    auto_view = _auto_story_channel_view()
    out["channels"] = auto_view.get("channels", {})
    if "error" in auto_view:
        out["auto_story_error"] = auto_view["error"]

    try:
        from app.services import auto_story
        conf = auto_story.settings()
        out["auto_story_settings"] = {k: conf.get(k) for k in
                                      ("enabled", "per_channel", "formats", "publish", "last_run")}
    except Exception as exc:  # noqa: BLE001
        out["auto_story_settings"] = {"error": str(exc)[:200]}

    try:
        from app.services import longform_nightly
        lf = longform_nightly.settings()
        out["longform"] = {"settings": {k: lf.get(k) for k in
                                        ("enabled", "per_channel", "minutes", "channels", "last_run")},
                           "status": longform_nightly.read_status()}
    except Exception as exc:  # noqa: BLE001
        out["longform"] = {"error": str(exc)[:200]}

    try:
        from app.services import produce_queue
        q = produce_queue.snapshot()
        out["queue"] = {"paused": q.get("paused"),
                        "items": [{k: it.get(k) for k in ("id", "project_id", "title", "status", "error")}
                                  for it in (q.get("items") or [])[:20]]}
    except Exception as exc:  # noqa: BLE001
        out["queue"] = {"error": str(exc)[:200]}

    try:
        from app.services import topic_store
        vault = topic_store.load_topics()
        top = sorted(vault, key=lambda t: t.get("viral_potential") or 0, reverse=True)[:10]
        out["vault_top"] = [{"id": t.get("id"), "topic": t.get("topic"), "channel": t.get("channel"),
                             "viral_potential": t.get("viral_potential"), "stage": t.get("stage")} for t in top]
    except Exception as exc:  # noqa: BLE001
        out["vault_top"] = {"error": str(exc)[:200]}

    try:
        from app.services import audience_desk
        audience: Dict[str, Any] = {}
        for ch in CHANNELS:
            latest = audience_desk.latest(ch)
            if latest:
                findings = sorted(latest.get("findings") or [], key=lambda f: f.get("score") or 0, reverse=True)
                audience[ch] = {"ran_at": latest.get("ran_at"),
                                "top": [{k: f.get(k) for k in ("kind", "topic", "summary", "mentions", "score")}
                                        for f in findings[:5]]}
        out["audience"] = audience
    except Exception as exc:  # noqa: BLE001
        out["audience"] = {"error": str(exc)[:200]}

    try:
        from app.services import health_checks
        health = health_checks.run_all()
        out["health"] = {"overall": health.get("overall"), "counts": health.get("counts"),
                         "problems": [{k: r.get(k) for k in ("id", "label", "state", "summary")}
                                     for r in health.get("checks", []) if r.get("state") in ("warn", "fail")]}
    except Exception as exc:  # noqa: BLE001
        out["health"] = {"error": str(exc)[:200]}

    try:
        from integrations import instagram_publish
        accounts = instagram_publish.status().get("accounts") or {}
        out["instagram"] = {name: {k: s.get(k) for k in ("connected", "username", "enabled", "post_times")}
                            for name, s in accounts.items()}
    except Exception as exc:  # noqa: BLE001
        out["instagram"] = {"error": str(exc)[:200]}

    try:
        from integrations import youtube_publish
        st = youtube_publish.status()
        out["youtube"] = {"has_client": st.get("has_client"),
                          "channels": [{k: c.get(k) for k in ("id", "title", "brand", "signed_in")}
                                       for c in (st.get("channels") or [])]}
    except Exception as exc:  # noqa: BLE001
        out["youtube"] = {"error": str(exc)[:200]}

    try:
        from app.services import master_control
        out["master_pause"] = master_control.state()
        out["memory"] = master_control._memory_snapshot()
    except Exception as exc:  # noqa: BLE001
        out["master_pause"] = {"error": str(exc)[:200]}
        out["memory"] = {}

    try:
        out["approvals_pending"] = len(list_approvals("pending"))
    except Exception as exc:  # noqa: BLE001
        out["approvals_pending"] = 0

    try:
        from app.services import director_fix, director_memory
        out["director"] = {
            "fixes_today": len(director_fix.fixes_today()),
            "open_tickets": len([t for t in director_fix.list_tickets() if t.get("state") == "open"]),
            "open_promises": len(director_memory.list_promises("open")),
        }
    except Exception as exc:  # noqa: BLE001
        out["director"] = {"error": str(exc)[:200]}

    return out


# --- plan: the strategist tool loop over the snapshot ---------------------------------------

def _plan_task(horizon: str, snap: Dict[str, Any], rules: str, mission: str = "") -> str:
    from app.services import director_fix
    return (
        f"Plan the {horizon} across every channel from this snapshot of the whole Studio.\n\n"
        "## The creator's mission (every item must serve one of these)\n" + (mission or "(not set)") + "\n\n"
        "## Snapshot\n" + json.dumps(snap, ensure_ascii=False, default=str)[:8000] + "\n\n"
        "## Learned rules (read these before deciding)\n" + (rules[:4000] or "(none yet)") + "\n\n"
        "## What to do\n"
        "1. Order a night's work: long-form scripts first (no GPU, cheapest), then the Raat3Baje reel, "
        "then Beyond3Baje, then mood reels last (cheapest, most tolerant of being bumped).\n"
        "2. Only use these exact action names for anything you want to run by yourself: "
        + ", ".join(MAKE_ALLOWLIST) + f" (or '{NEEDS_INTRO_ACTION}' when a long script needs his on-camera intro).\n"
        "   These fixes may also run without approval, but only when the snapshot shows that service down: "
        + ", ".join(director_fix.SAFE_FIXES) + ". These need his approval (needs_approval: true): "
        + ", ".join(director_fix.APPROVAL_FIXES) + ".\n"
        "3. Anything that publishes, deletes or changes a setting is never one of those actions -- still put it "
        "on the plan with needs_approval: true if it is worth doing; he decides it on the Dashboard.\n"
        "4. Respect the master pause and RAM/VRAM in the snapshot; if the Studio is paused, plan nothing that runs "
        "tonight.\n\n"
        f"Rough GPU-hour budget tonight: about {GPU_HOUR_BUDGET:g} hour(s) of render time (a long-form script "
        "costs none of it; a story reel ~1-3h; a mood reel ~15-30min). Spend it on the highest-value items first "
        "and say in `why` what you dropped or carried to tomorrow if you run out.\n\n"
        "Finish with:\n"
        '[FINAL_PLAN]{"items": [{"channel": "ChannelName or null", "action": "one of the names above", '
        '"params": {}, "when": "tonight/today/tomorrow", "why": "one line", '
        '"goal": "the Goals / Upcoming plans bullet this serves", "needs_approval": true or false}]}'
        "[/FINAL_PLAN]"
    )


def plan(horizon: str = "day", *, on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Runs the Director through the unattended strategist tool loop
    (`app/services/strategist_runner.py`) over today's snapshot; returns and
    stores `{horizon, generated_at, items: [...]}` under
    `knowledge/director/plans/<date>.json`. `needs_approval` on every item is
    recomputed here from `MAKE_ALLOWLIST`, never trusted from the model."""
    if horizon not in ("day", "week"):
        raise ValueError("horizon must be 'day' or 'week'")
    from app.services import master_control
    say = on_event or _noop
    master_control.wait_if_paused("studio_director: plan", say)
    from app.services import strategist_runner, director_fix, director_memory
    snap = snapshot()
    rules = read_rules()
    mission = director_memory.mission_text()
    out = strategist_runner.run(AGENT_NAME, "Studio", _plan_task(horizon, snap, rules, mission), on_event=say,
                              llm=_llm("director_plan"))
    raw_items = (out.get("plan") or {}).get("items")
    items: List[Dict[str, Any]] = []
    for it in (raw_items if isinstance(raw_items, list) else []):
        if not isinstance(it, dict):
            continue
        action = str(it.get("action") or "").strip()
        if not action:
            continue
        items.append({
            "channel": it.get("channel"),
            "action": action,
            "params": it.get("params") if isinstance(it.get("params"), dict) else {},
            "when": it.get("when") or horizon,
            "why": str(it.get("why") or "")[:300],
            "goal": str(it.get("goal") or "")[:160],
            "needs_approval": action not in MAKE_ALLOWLIST and action not in director_fix.SAFE_FIXES,
        })
    plan_obj = {"horizon": horizon, "generated_at": _now(), "turns": out.get("turns"), "items": items}
    _write_json(_plan_path(today()), plan_obj)
    return plan_obj


def read_plan(day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return _read_json(_plan_path(day or today()), None)


# --- act: MAKE items run; everything else becomes an approval request -----------------------

def _run_make_action(action: str, channel: Optional[str], params: Dict[str, Any],
                     say: Callable[[str], None]) -> Any:
    if action == "auto_story_make":
        from app.services import auto_story
        fmt = params.get("format") or params.get("fmt")
        if not fmt:
            raise ValueError("auto_story_make needs a 'format'.")
        return auto_story.make(channel, fmt, params.get("length"),
                               voice=params.get("voice") or auto_story.default_voice_for(channel),
                               publish=bool(params.get("publish")), style=params.get("style"),
                               theme=params.get("theme"), progress=say)
    if action == "auto_story_make_mood_reel":
        from app.services import auto_story
        return auto_story.make_mood_reel(channel, params.get("length"), style=params.get("style"),
                                         theme=params.get("theme"), progress=say)
    if action == "longform_run_slot":
        from app.services import auto_story
        minutes = params.get("minutes") or params.get("length")
        return auto_story.make(channel, auto_story.LONG_STORY, minutes,
                               voice=params.get("voice") or auto_story.default_voice_for(channel),
                               publish=bool(params.get("publish")), progress=say)
    if action == "story_adapt_start":
        from app.services import story_adapt
        if not params.get("entry_id"):
            raise ValueError("story_adapt_start needs an 'entry_id'.")
        project_id = story_adapt.adapt(
            params["entry_id"], parts=params.get("parts") or 1,
            minutes_per_part=params.get("minutes_per_part") or 20, inspired=bool(params.get("inspired")),
            run=False, story_index=params.get("story_index"), story_title=params.get("story_title"),
            channel=channel or story_adapt.DEFAULT_CHANNEL)
        return story_adapt.start_job(project_id)
    if action == "story_adapt_resume":
        from app.services import story_adapt
        if not params.get("project_id"):
            raise ValueError("story_adapt_resume needs a 'project_id'.")
        return story_adapt.start_job(params["project_id"])
    if action == "produce_queue_add":
        from app.services import produce_queue
        if not params.get("project_id"):
            raise ValueError("produce_queue_add needs a 'project_id'.")
        return produce_queue.add(params["project_id"], brand=params.get("brand") or channel or "",
                                 title=params.get("title") or "", recording_path=params.get("recording_path") or "",
                                 settings_override=params.get("settings_override"),
                                 mode=params.get("mode") or "auto", precut=bool(params.get("precut")),
                                 resume_from=params.get("resume_from") or "start", front=bool(params.get("front")))
    if action == "retry_step":
        from runtime.workflow import WorkflowEngine
        if not params.get("project_id"):
            raise ValueError("retry_step needs a 'project_id'.")
        return WorkflowEngine().execute_next(params["project_id"])
    if action == "retry_record":
        from app.services import produce_queue
        if not params.get("item_id"):
            raise ValueError("retry_record needs an 'item_id'.")
        return produce_queue.retry(params["item_id"])
    raise ValueError(f"'{action}' is not a MAKE action.")


def add_approval(item: Dict[str, Any]) -> Dict[str, Any]:
    rows = _read_jsonl(_approvals_path())
    row = {"id": uuid.uuid4().hex[:12], "at": _now(), "item": item, "state": "pending"}
    rows.append(row)
    _write_jsonl(_approvals_path(), rows)
    return row


def list_approvals(state: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _read_jsonl(_approvals_path())
    return [r for r in rows if state is None or r.get("state") == state]


def _set_approval_state(approval_id: str, **fields: Any) -> Dict[str, Any]:
    rows = _read_jsonl(_approvals_path())
    found = None
    for row in rows:
        if row.get("id") == approval_id:
            row.update(fields)
            found = row
            break
    if found is None:
        raise ValueError(f"No such approval: {approval_id}")
    _write_jsonl(_approvals_path(), rows)
    return found


def _log_approval_decision(item: Dict[str, Any], decision: str, reason: str = "") -> None:
    """A line `learn()` reads back later, same shape as `auto_story`'s own
    decision log (`{at, channel, format, action, reason}` plus `decision`)."""
    path = _decisions_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"at": _now(), "project_id": (item.get("params") or {}).get("project_id"),
             "channel": item.get("channel"), "format": (item.get("params") or {}).get("format"),
             "action": item.get("action"), "decision": decision, "reason": reason or None,
             "source": "studio_director"}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def _run_approved_action(item: Dict[str, Any], say: Callable[[str], None]) -> Any:
    """What "approving executes it" actually does for an action outside the
    MAKE allowlist. Only the actions with a clear, existing, safe service
    function behind them are wired; the rest (a generic settings change, a
    nightly scheduler toggle, deleting a project) have no safe primitive
    anywhere in the codebase yet and are refused here rather than guessed at
    -- the approval is still recorded as approved, with that refusal as its
    error, so nothing is silently dropped."""
    action = str(item.get("action") or "")
    params = dict(item.get("params") or {})
    from app.services import director_fix
    if action in director_fix.ALL_FIXES:
        return director_fix.run_fix(action, params, by="approval", approved=True)
    from app.services import master_control
    master_control.wait_if_paused(f"studio_director: approved {action}", say)
    if action in MAKE_ALLOWLIST:
        return _run_make_action(action, item.get("channel"), params, say)
    if action == NEEDS_INTRO_ACTION:
        return {"noted": "waiting on the creator's own on-camera intro; nothing to run."}
    if action in ("auto_story_approve", "approve", "publish_youtube"):
        from app.services import auto_story
        if not params.get("project_id"):
            raise ValueError(f"'{action}' needs a 'project_id'.")
        return auto_story.approve(params["project_id"])
    if action in ("auto_story_reject", "reject"):
        from app.services import auto_story
        if not params.get("project_id"):
            raise ValueError(f"'{action}' needs a 'project_id'.")
        return auto_story.reject(params["project_id"], reason=params.get("reason") or "")
    if action == "post_instagram":
        from app.services import auto_story
        if not params.get("project_id"):
            raise ValueError("post_instagram needs a 'project_id'.")
        return auto_story.post_instagram(params["project_id"], force=bool(params.get("force")))
    raise ValueError(f"'{action}' has no automatic handler yet; apply it by hand on the relevant page.")


def act(plan_obj: Dict[str, Any], *, on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Executes a plan's MAKE items one at a time through the existing
    services (they already sequence the GPU); everything else becomes an
    approval request. Holds while the master pause is on, at the same
    checkpoint the services themselves use."""
    say = on_event or _noop
    from app.services import master_control
    results: List[Dict[str, Any]] = []
    for item in (plan_obj.get("items") or []):
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "").strip()
        channel = item.get("channel")
        params = dict(item.get("params") or {})
        from app.services import director_fix
        if action in director_fix.SAFE_FIXES:
            results.append({"item": item, "status": "fix",
                            "result": director_fix.run_fix(action, params, by="plan")})
            continue
        if action not in MAKE_ALLOWLIST:
            row = add_approval(item)
            results.append({"item": item, "status": "approval_requested", "approval_id": row["id"]})
            continue
        master_control.wait_if_paused(f"studio_director: act {action}", say)
        say(f"Running {action} for {channel or 'the Studio'}")
        try:
            result = _run_make_action(action, channel, params, say)
            results.append({"item": item, "status": "ran", "result": result})
        except Exception as exc:  # noqa: BLE001 - one item failing never stops the rest of the plan
            logger.warning("studio_director: action %s failed: %s", action, exc)
            results.append({"item": item, "status": "failed", "error": str(exc)[:300]})
    return {"at": _now(), "results": results}


class ApprovalNotPending(ValueError):
    """The approval was already decided."""


def approve_approval(approval_id: str, *, on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Approves a pending approval request and runs it."""
    say = on_event or _noop
    stored = next((r for r in _read_jsonl(_approvals_path()) if r.get("id") == approval_id), None)
    if stored is not None and stored.get("state", "pending") != "pending":
        raise ApprovalNotPending(f"Approval {approval_id} is already {stored.get('state')}; not run again.")
    row = _set_approval_state(approval_id, state="approved", decided_at=_now())
    item = row.get("item") or {}
    try:
        row["result"] = _run_approved_action(item, say)
    except Exception as exc:  # noqa: BLE001 - the approval still stands; the error is on record
        row["error"] = str(exc)[:300]
    _log_approval_decision(item, "approved")
    rows = _read_jsonl(_approvals_path())
    for r in rows:
        if r.get("id") == approval_id:
            r.update(row)
            break
    _write_jsonl(_approvals_path(), rows)
    return row


def decline_approval(approval_id: str, reason: str = "") -> Dict[str, Any]:
    row = _set_approval_state(approval_id, state="declined", decided_at=_now(), reason=reason or "")
    _log_approval_decision(row.get("item") or {}, "declined", reason)
    return row


# --- learn: decisions + approvals + Audience Desk -> per-channel rules -----------------------

def _extract_section(text: str, heading: str, placeholder: str) -> str:
    """`heading`'s whole block (up to the next `## ` heading or the end of
    the file), verbatim -- or a fresh placeholder block when it is missing."""
    m = re.search(rf"({re.escape(heading)}.*?)(?=\n##\s|\Z)", text, re.I | re.S)
    if m:
        return m.group(1).rstrip() + "\n"
    return f"{heading}\n\n{placeholder}\n"


def read_rules() -> str:
    try:
        with open(_rules_path(), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def set_creator_rules(text: str) -> str:
    """Overwrites just the hand-written "Creator's rules" section; everything
    else in rules.md (learned rules, conversation notes) is left as is."""
    current = read_rules() or f"# Studio Director -- learned rules\n\n{LEARNED_SECTION_HEADING}\n\n(nothing learned yet.)\n"
    body = (text or "").strip() or "(none yet -- write your own rules here; they are never overwritten.)"
    new_section = f"{CREATOR_SECTION_HEADING}\n\n{body}\n"
    if re.search(re.escape(CREATOR_SECTION_HEADING), current, re.I):
        current = re.sub(rf"{re.escape(CREATOR_SECTION_HEADING)}.*?(?=\n##\s|\Z)", new_section, current,
                         count=1, flags=re.I | re.S)
    else:
        current = new_section + "\n" + current.lstrip()
    os.makedirs(DIRECTOR_DIR, exist_ok=True)
    with open(_rules_path(), "w", encoding="utf-8") as f:
        f.write(current)
    return current


def _append_conversation_rule(channel: str, text: str) -> Dict[str, Any]:
    current = read_rules() or f"# Studio Director -- learned rules\n\n{CREATOR_SECTION_HEADING}\n\n(none yet.)\n"
    entry = f"- [{_now()}] **{channel or 'General'}**: {text}"
    existing = _extract_section(current, CONVERSATION_SECTION_HEADING, "")
    body = existing[len(CONVERSATION_SECTION_HEADING):].strip()
    new_section = (f"{CONVERSATION_SECTION_HEADING}\n\n{entry}\n" if not body or body.startswith("(nothing")
                  else f"{CONVERSATION_SECTION_HEADING}\n\n{body}\n{entry}\n")
    if re.search(re.escape(CONVERSATION_SECTION_HEADING), current, re.I):
        current = re.sub(rf"{re.escape(CONVERSATION_SECTION_HEADING)}.*?(?=\n##\s|\Z)", new_section, current,
                         count=1, flags=re.I | re.S)
    else:
        current = current.rstrip() + "\n\n" + new_section
    os.makedirs(DIRECTOR_DIR, exist_ok=True)
    with open(_rules_path(), "w", encoding="utf-8") as f:
        f.write(current)
    return {"channel": channel or "General", "text": text}


def learn() -> str:
    """Reads the decision log (approvals/rejections + reasons from both
    `auto_story` and the Director's own approvals), posts made and the
    Audience Desk's own findings; distils per-channel rules into
    `knowledge/director/rules.md`, newest evidence first, each rule with its
    evidence count. Never touches the "Creator's rules" or "From
    conversation" sections -- they are carried over verbatim."""
    existing = read_rules()
    creator_section = _extract_section(
        existing, CREATOR_SECTION_HEADING,
        "(none yet -- write your own rules here; they are never overwritten.)")
    conversation_section = _extract_section(
        existing, CONVERSATION_SECTION_HEADING, "(nothing from conversation yet.)")

    by_channel: Dict[str, Dict[str, Any]] = {}

    def bucket(channel: Optional[str]) -> Dict[str, Any]:
        return by_channel.setdefault(channel or "General",
                                     {"reasons": {}, "approvals": 0, "latest": "", "audience": []})

    def note_reason(channel: Optional[str], reason: str, at: str) -> None:
        b = bucket(channel)
        reason = (reason or "no reason given").strip() or "no reason given"
        info = b["reasons"].setdefault(reason, {"count": 0, "latest": ""})
        info["count"] += 1
        if at and at > info["latest"]:
            info["latest"] = at
        if at and at > b["latest"]:
            b["latest"] = at

    for d in _read_jsonl(_decisions_log_path()):
        action = d.get("action") or d.get("decision")
        if action in ("reject", "declined", "rejected"):
            note_reason(d.get("channel"), str(d.get("reason") or ""), str(d.get("at") or ""))
        elif action in ("approve", "approved"):
            b = bucket(d.get("channel"))
            b["approvals"] += 1
            at = str(d.get("at") or "")
            if at > b["latest"]:
                b["latest"] = at

    try:
        from app.services import auto_story
        for rec in auto_story.list_records():
            if (rec.get("review") or {}).get("state") == "approved":
                b = bucket(rec.get("brand"))
                b["approvals"] += 1
                at = str(rec.get("updated_at") or "")
                if at > b["latest"]:
                    b["latest"] = at
    except Exception as exc:  # noqa: BLE001
        logger.debug("studio_director.learn: auto_story records unavailable (%s)", exc)

    try:
        from app.services import audience_desk
        for ch in CHANNELS:
            latest = audience_desk.latest(ch)
            if latest and latest.get("findings"):
                top = sorted(latest["findings"], key=lambda f: f.get("score") or 0, reverse=True)[:3]
                notes = [f.get("summary") or f.get("topic") or "" for f in top if (f.get("summary") or f.get("topic"))]
                if notes:
                    bucket(ch)["audience"] = notes
    except Exception as exc:  # noqa: BLE001
        logger.debug("studio_director.learn: audience desk unavailable (%s)", exc)

    lines = ["# Studio Director -- learned rules", "", creator_section.rstrip(), "",
             conversation_section.rstrip(), "", LEARNED_SECTION_HEADING, "", f"_Updated {_now()}._", ""]
    if not by_channel:
        lines.append("(nothing learned yet -- approvals, rejections and Audience Desk findings will build this.)")
    else:
        for channel in sorted(by_channel, key=lambda c: by_channel[c]["latest"], reverse=True):
            data = by_channel[channel]
            lines.append(f"### {channel}")
            if data["approvals"]:
                lines.append(f"- Approved without changes {data['approvals']} time(s) (evidence: {data['approvals']}).")
            for reason, info in sorted(data["reasons"].items(), key=lambda kv: kv[1]["latest"], reverse=True):
                lines.append(f'- Rejected/declined for "{reason}" (evidence: {info["count"]}, last {info["latest"] or "unknown"}).')
            for note in data["audience"]:
                lines.append(f"- Viewers asked for: {note} (Audience Desk).")
            lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    os.makedirs(DIRECTOR_DIR, exist_ok=True)
    tmp = _rules_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, _rules_path())
    return text


# --- briefing: the morning markdown ----------------------------------------------------------

def briefing(date: Optional[str] = None) -> str:
    """The morning briefing markdown: what was made overnight, what failed
    and why, what needs him today (reviews, approvals, intros to record),
    today's plan, and the learned rules. Kept at
    `knowledge/director/briefings/<date>.md`."""
    day = date or today()
    snap = snapshot()
    rules = read_rules()
    plan_obj = read_plan(day)

    from app.services import director_memory, director_fix
    lines = [f"# Studio Director briefing -- {day}", ""]
    try:
        gm = re.search(r"^## Goals\s*$(.*?)(?=^##\s|\Z)", director_memory.read_mission(), re.M | re.S)
        goals = [ln for ln in (gm.group(1).splitlines() if gm else []) if ln.strip().startswith("- ")][:5]
    except Exception:  # noqa: BLE001
        goals = []
    if goals:
        lines += ["## Goals"] + goals + [""]
    lines.append("## Made overnight")
    any_made = False
    for channel, data in sorted(snap.get("channels", {}).items()):
        made = [r for r in data.get("recent", []) if r.get("state") and r.get("state") != "failed"]
        if made:
            any_made = True
            lines.append(f"- **{channel}**: " + "; ".join(
                f"{r.get('name') or r.get('project_id')} ({r.get('format') or '?'}, {r.get('state')})"
                for r in made[:5]))
    if not any_made:
        lines.append("- Nothing finished since the last briefing.")
    lines.append("")

    lines.append("## Failed, and why")
    any_failed = False
    for channel, data in sorted(snap.get("channels", {}).items()):
        for r in data.get("failed", []):
            any_failed = True
            lines.append(f"- **{channel}** {r.get('name') or r.get('project_id')}: {r.get('reason') or 'unknown error'}")
    if not any_failed:
        lines.append("- No failures.")
    lines.append("")

    lines.append("## Fixed by itself")
    try:
        fixed = [r for r in director_fix.fixes_today() if r.get("ran") and r.get("ok")]
    except Exception:  # noqa: BLE001
        fixed = []
    if fixed:
        lines.extend(f"- {r.get('action')} ({r.get('by')}): {str(r.get('result') or '')[:80]}" for r in fixed)
    else:
        lines.append("- Nothing needed fixing.")
    lines.append("")

    lines.append("## Dev tickets open")
    try:
        open_tickets = [t for t in director_fix.list_tickets() if t.get("state") == "open"]
    except Exception:  # noqa: BLE001
        open_tickets = []
    if open_tickets:
        lines.extend(f"- {t.get('title')} ({t.get('file')})" for t in open_tickets)
    else:
        lines.append("- None.")
    lines.append("")

    lines.append("## Needs you today")
    needs: List[str] = []
    for channel, data in sorted(snap.get("channels", {}).items()):
        for r in data.get("needs_review", []):
            needs.append(f"- **{channel}** review: {r.get('name') or r.get('project_id')} ({r.get('format') or '?'})")
    for row in list_approvals("pending"):
        item = row.get("item") or {}
        needs.append(f"- Approval needed: {item.get('action')} for {item.get('channel') or 'the Studio'} ({row.get('id')})")
    try:
        for p in director_memory.list_promises("open"):
            needs.append(f"- I promised: {p.get('text')}")
    except Exception:  # noqa: BLE001
        pass
    if plan_obj:
        for item in plan_obj.get("items") or []:
            if item.get("action") == NEEDS_INTRO_ACTION:
                pid = (item.get("params") or {}).get("project_id") or "?"
                needs.append(f"- Needs your on-camera intro: {item.get('channel') or '?'} ({pid})")
    if needs:
        lines.extend(needs)
    else:
        lines.append("- Nothing waiting on you.")
    lines.append("")

    lines.append("## Today's plan")
    if plan_obj and plan_obj.get("items"):
        for item in plan_obj["items"]:
            goal = f" (goal: {item.get('goal')})" if item.get("goal") else ""
            lines.append(f"- {item.get('channel') or 'Studio-wide'}: {item.get('action')} -- {item.get('why') or ''}{goal}")
    else:
        lines.append("- No plan generated yet for today (POST /api/director/plan).")
    lines.append("")

    lines.append("## Learned rules")
    lines.append(rules.strip() or "(nothing learned yet.)")

    text = "\n".join(lines).rstrip() + "\n"
    _write_text(_briefing_path(day), text)
    return text


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_briefing(date: Optional[str] = None) -> Optional[str]:
    try:
        with open(_briefing_path(date or today()), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# --- the nightly task: learn -> briefing -> tomorrow's plan ----------------------------------

def run_nightly(on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """learn -> briefing -> tomorrow's plan; acts on MAKE items only when
    `director_autoplan` (this module's `autoplan` setting) is on -- off by
    default until the creator enables it on the Dashboard."""
    say = on_event or _noop
    from app.services import master_control
    master_control.wait_if_paused("studio_director: nightly", say)
    from app.services import director_fix
    say("Self-check and safe fixes")
    try:
        result_self = director_fix.self_check(say)
    except Exception as exc:  # noqa: BLE001 - the rest of the night still runs
        result_self = {"error": str(exc)[:300]}
    say("Learning from the day's decisions")
    learn()
    say("Writing the morning briefing")
    briefing()
    result: Dict[str, Any] = {"at": _now(), "briefing_written": True, "self_check": result_self}
    plan_obj: Optional[Dict[str, Any]] = None
    say("Planning tomorrow")
    try:
        plan_obj = plan("day", on_event=say)
        result["plan_items"] = len(plan_obj.get("items") or [])
    except Exception as exc:  # noqa: BLE001 - learn/briefing already succeeded
        logger.warning("studio_director nightly: planning failed: %s", exc)
        result["plan_error"] = str(exc)[:300]
    if settings().get("autoplan") and plan_obj:
        say("Acting on tonight's MAKE items")
        result["act"] = act(plan_obj, on_event=say)
    else:
        result["act"] = {"skipped": "director_autoplan is off"}
    return result


# --- chat: ask the Director directly ----------------------------------------------------------

_RULE_RE = re.compile(r"\[RULE:\s*(.*?)\]\s*(.*?)\s*\[/RULE\]", re.I | re.S)


def ask(message: str, *, on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """A chat turn with the Director: a question is answered from today's
    snapshot; an instruction ending in `[RULE: Channel] ... [/RULE]` is kept
    under "From conversation" in the learned rules (never the "Creator's
    rules" section -- that one is his own to edit directly)."""
    say = on_event or _noop
    from app.services import strategist_runner, director_knowledge, director_memory, director_fix
    snap = snapshot()
    rules = read_rules()
    extra = director_memory.memory_section(message) + "\n" + (
        "\n\n## Snapshot\n" + json.dumps(snap, ensure_ascii=False, default=str)[:6000] +
        "\n\n## Learned rules\n" + (rules[:3000] or "(none yet)") +
        "\n\nThe creator is talking to you directly in chat, not asking for a plan -- do not write "
        "[FINAL_PLAN]. The snapshot's `right_now` is live this minute; the channel records may be older, "
        "so where they disagree `right_now` wins (a video in `production` is being made, not failed). "
        "Asked what is going on, lead with `right_now` in plain words: what is being made and how far "
        "along (its `doing` and `progress_pct`), which voices are being made, what waits on him, memory "
        "if commit is above 85% of its limit or VRAM is nearly full, open promises, recent incidents; "
        "then failures. Never mention Gmail, Calendar or other connectors -- they are not part of the "
        "Studio. Answer from the snapshot; if it lacks the answer, call a tool "
        "(read_doc with heading or grep, health_report, log_digest, llm_status, persona_roster, settings_summary, "
        "failed_records, incidents_search, tickets_list) "
        "before answering. Never guess; cite the doc path. If this is a standing instruction for "
        "future nights, end your reply with [RULE: Channel] one short sentence [/RULE] "
        "(use [RULE: General] for a Studio-wide instruction) so it is remembered.\n"
        + "\n## Docs you can read (read_doc)\n" + director_knowledge.index_text()
        + "\n\nTo fix something listed under Fixes, write [FIX: name | {json}] (max 2; safe ones run now, the "
        "rest go to his approvals). For a code bug write [TICKET: title] evidence, suspected file, suggested fix "
        "[/TICKET]; never claim to edit code. A new goal or plan of his: [GOAL: Goals|Intentions|Upcoming "
        "plans|Priorities|Constraints] one sentence [/GOAL]. Something you will do or are waiting on: "
        "[PROMISE] text [/PROMISE]; done: [DONE: id]. Never write content yourself: hand it to a persona with "
        "[INVOKE_AGENT: Name] task [/INVOKE_AGENT] (max 3 per reply) and relay the result briefly.\n" + director_fix.fix_catalogue()
    )
    say("Thinking")
    out = strategist_runner.chat(AGENT_NAME, "Studio", message, system_extra=extra,
                                 llm=_llm("director_chat"), on_event=say,
                                 history=director_memory.conversation_messages())
    reply = str(out.get("reply") or "")
    simulated = bool(out.get("simulated"))
    shown = _display_reply(reply)
    rule_added = None
    goal_added: List[Dict[str, Any]] = []
    promises_added: List[Dict[str, Any]] = []
    fixes: List[Dict[str, Any]] = []
    ticket = None
    if not simulated:
        m = _RULE_RE.search(reply)
        if m:
            rule_added = _append_conversation_rule(m.group(1).strip(), m.group(2).strip())
        tags = director_memory.parse_tags(reply)
        for section, text in tags["goals"]:
            goal_added.append(director_memory.append_goal(section, text))
        for text in tags["promises"]:
            promises_added.append(director_memory.add_promise(text))
        for pid in tags["done"]:
            director_memory.close_promise(pid)
        if tags["tickets"]:
            title, body = tags["tickets"][0]
            ticket = director_fix.write_ticket(title, body)
        fixes = director_fix.handle_reply_fixes(reply, by="chat")
        director_memory.record_turn("user", message)
        director_memory.record_turn("director", shown)
    return {"reply": shown, "simulated": simulated, "rule_added": rule_added,
            "provider": out.get("provider"), "turns": out.get("turns"),
            "goal_added": goal_added, "promises_added": promises_added, "fixes": fixes, "ticket": ticket}


_STRIP_TAGS_RE = re.compile(
    r"\[GOAL:.*?\[/GOAL\]|\[PROMISE\].*?\[/PROMISE\]|\[TICKET:.*?\[/TICKET\]|\[RULE:.*?\[/RULE\]"
    r"|\[DONE:\s*[a-f0-9]{6,12}\]|\[FIX:[^\]]*\]", re.I | re.S)


def _display_reply(reply: str) -> str:
    """The reply as he reads it: the bookkeeping tags are acted on, not shown."""
    from app.services import director_fix
    return _STRIP_TAGS_RE.sub("", director_fix.strip_fix_tags(reply)).strip()


# --- live activity: real-time updates of active processes and steps ---

def _format_elapsed(started_at_iso: Optional[str]) -> str:
    if not started_at_iso:
        return ""
    try:
        dt = datetime.fromisoformat(started_at_iso)
        seconds = max(0, int((datetime.now() - dt).total_seconds()))
        mins, secs = divmod(seconds, 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            return f"{hrs}h {mins}m {secs}s"
        if mins > 0:
            return f"{mins}m {secs}s"
        return f"{secs}s"
    except Exception:
        return ""


def _estimate_remaining(
    step_name: str,
    agent: str,
    logs: List[str],
    started_at_iso: Optional[str],
    target_minutes: Optional[float] = None,
) -> Tuple[str, int]:
    """Calculates an intelligent estimate of how much time is remaining for a task,
    using historical baseline step durations and real-time sub-step progress logs."""
    if not started_at_iso:
        return ("", 0)
    try:
        dt = datetime.fromisoformat(started_at_iso)
        elapsed_sec = max(0, int((datetime.now() - dt).total_seconds()))
    except Exception:
        return ("", 0)

    step_lower = (step_name or "").lower()
    agent_lower = (agent or "").lower()

    # Check for progress indicators in logs (e.g. "section 2/5", "Rewrite: part 3/5 done")
    import re
    part_progress = None
    for log_msg in reversed(logs or []):
        m = re.search(r'(?:section|part)\s+(\d+)\s*(?:/|of)\s*(\d+)', str(log_msg), re.IGNORECASE)
        if m:
            curr, total = int(m.group(1)), int(m.group(2))
            if total > 0 and curr <= total:
                part_progress = (curr, total)
                break

    if "strategist" in step_lower or "planning" in step_lower:
        total_sec = 90
    elif "research" in step_lower or "collection" in step_lower:
        total_sec = 240
    elif "script" in step_lower or "story" in step_lower or "writer" in agent_lower:
        if part_progress:
            curr, total = part_progress
            rem_parts = max(0, total - curr)
            total_sec = max(elapsed_sec + rem_parts * 150, 300)
        elif target_minutes and target_minutes >= 15:
            total_sec = int(target_minutes * 50)  # ~1250s for 25-min story
        else:
            total_sec = 220
    elif "short" in step_lower:
        total_sec = 120
    elif "visual" in step_lower or "prompt" in step_lower:
        total_sec = 120
    elif "sound" in step_lower or "timeline" in step_lower:
        total_sec = 65
    elif "narration" in step_lower or "editor" in agent_lower:
        if part_progress:
            curr, total = part_progress
            rem_parts = max(0, total - curr)
            total_sec = max(elapsed_sec + rem_parts * 110, 200)
        else:
            total_sec = 500
    elif "seo" in step_lower or "thumbnail" in step_lower:
        total_sec = 240
    elif "render" in step_lower:
        total_sec = 600
    elif "transcribe" in step_lower:
        total_sec = 90
    else:
        total_sec = 180

    rem_sec = total_sec - elapsed_sec
    if rem_sec <= 0 or (part_progress and part_progress[0] == part_progress[1]):
        pct = 95
        rem_str = "finishing up…"
    else:
        pct = min(94, max(5, int((elapsed_sec / total_sec) * 100)))
        mins, secs = divmod(rem_sec, 60)
        if mins > 0:
            rem_str = f"~{mins}m {secs}s remaining" if secs > 0 else f"~{mins}m remaining"
        else:
            rem_str = f"~{secs}s remaining"

    return rem_str, pct


def live_activity() -> Dict[str, Any]:
    """Real-time pulse of whatever process and step is currently running in the Studio:
    active longform runs, running project workflow steps, active adaptations,
    produce queue jobs, and narration/renders."""
    import core.paths
    active_items: List[Dict[str, Any]] = []

    # 1. Check running Projects in projects directory with a truly running step
    active_project_titles: set = set()
    try:
        root = str(core.paths.PROJECTS_DIR)
        if os.path.isdir(root):
            for pid in os.listdir(root):
                p_file = os.path.join(root, pid, "project.json")
                if not os.path.isfile(p_file):
                    continue
                try:
                    with open(p_file, encoding="utf-8") as f:
                        pdata = json.load(f)
                except Exception:
                    continue
                status = pdata.get("status")
                if status in ("completed", "archived"):
                    continue

                # Scan steps_history for an active 'running' step
                running_step = None
                for h in (pdata.get("steps_history") or []):
                    if h.get("status") == "running":
                        running_step = h
                        break

                if not running_step:
                    continue

                active_step_name = running_step.get("step_name") or pdata.get("current_step") or "Processing"
                active_agent = running_step.get("agent_name") or "Agent"
                started_at = running_step.get("started_at")
                logs = running_step.get("logs") or []
                latest_log = logs[-1] if logs else ""

                target_mins = None
                try:
                    target_mins = float(pdata.get("metadata", {}).get("target_duration_minutes", 0) or 0)
                except Exception:
                    target_mins = None

                rem_str, progress_pct = _estimate_remaining(
                    active_step_name, active_agent, logs, started_at, target_mins
                )

                item_title = pdata.get("name") or pid
                active_project_titles.add(item_title.strip().lower())

                active_items.append({
                    "type": "project_workflow",
                    "project_id": pid,
                    "channel": pdata.get("brand"),
                    "title": item_title,
                    "current_step": active_step_name,
                    "agent": active_agent,
                    "status": "running",
                    "detail": f"Workflow: {pdata.get('workflow_name', 'default')}",
                    "started_at": started_at,
                    "elapsed": _format_elapsed(started_at),
                    "estimated_remaining": rem_str,
                    "progress_pct": progress_pct,
                    "latest_log": latest_log,
                })
    except Exception as exc:
        logger.debug("live_activity: project check error: %s", exc)

    # 2. Check Longform Nightly status
    try:
        from app.services import longform_nightly
        lf_status = longform_nightly.read_status()
        if lf_status.get("state") == "running":
            for t in lf_status.get("tasks") or []:
                stage = t.get("stage")
                topic = (t.get("topic") or "").strip()
                if stage and stage not in ("queued", "completed", "done", "failed"):
                    # Avoid duplicate if this project is already listed from project scanning
                    if topic.lower() in active_project_titles:
                        continue
                    started_at = lf_status.get("started_at")
                    t_mins = None
                    try:
                        t_mins = float(t.get("minutes", 0) or 0)
                    except Exception:
                        t_mins = None

                    rem_str, progress_pct = _estimate_remaining(
                        stage, "Workflow Engine", [], started_at, t_mins
                    )

                    active_items.append({
                        "type": "longform_episode",
                        "channel": t.get("channel"),
                        "title": topic or f"{t.get('channel')} Slot {t.get('slot')}",
                        "current_step": stage,
                        "agent": "Workflow Engine",
                        "status": "running",
                        "detail": f"{t.get('minutes', '')} min episode ({t.get('detail', '')})".strip(),
                        "started_at": started_at,
                        "elapsed": _format_elapsed(started_at),
                        "estimated_remaining": rem_str,
                        "progress_pct": progress_pct,
                        "latest_log": t.get("detail") or "",
                    })
    except Exception as exc:
        logger.debug("live_activity: longform check error: %s", exc)

    # 3. Check Produce Queue
    try:
        from app.services import produce_queue
        running_q = produce_queue.running_item()
        if running_q:
            stage_name = running_q.get("checkpoint") or "rendering"
            started_at = running_q.get("started_at") or running_q.get("updated_at")
            rem_str, progress_pct = _estimate_remaining(
                stage_name, "BuzzEdit / GPU", [], started_at
            )
            active_items.append({
                "type": "produce_queue",
                "channel": running_q.get("brand"),
                "project_id": running_q.get("project_id"),
                "title": running_q.get("title") or running_q.get("project_id"),
                "current_step": f"Video Production ({stage_name})",
                "agent": "BuzzEdit / GPU",
                "status": "running",
                "detail": f"Stage: {stage_name}",
                "started_at": started_at,
                "elapsed": _format_elapsed(started_at),
                "estimated_remaining": rem_str,
                "progress_pct": progress_pct,
                "latest_log": f"Attempt {running_q.get('attempts', 1)}",
            })
    except Exception as exc:
        logger.debug("live_activity: produce_queue check error: %s", exc)

    # 4. Generate Director's Summary
    if not active_items:
        summary = "Studio is currently idle. No background processes or pipeline steps are running."
    else:
        parts = []
        for it in active_items:
            chan = f"[{it.get('channel')}] " if it.get("channel") else ""
            step = it.get("current_step") or "Processing"
            agent = f" ({it.get('agent')})" if it.get("agent") and it.get("agent") != "Agent" else ""
            elapsed_str = f" for {it.get('elapsed')}" if it.get("elapsed") else ""
            parts.append(f"{chan}'{it.get('title')}' is on step '{step}'{agent}{elapsed_str}")
        summary = f"Active right now ({len(active_items)}): {'; '.join(parts)}."

    return {
        "timestamp": _now(),
        "active_count": len(active_items),
        "summary": summary,
        "items": active_items,
    }


def suggestions() -> Dict[str, Any]:
    """Generates structured, actionable recommendations from the Director:
    what to do next, stories in progress, replanning alerts, and top viral ideas."""
    suggestions_list = []

    # 1. Check live in-progress stories
    activity = live_activity()
    active_count = activity.get("active_count", 0)
    active_items = activity.get("items", [])

    # 2. Check pending reviews / approvals
    pending_approvals = list_approvals("pending")
    if pending_approvals:
        suggestions_list.append({
            "id": "pending_director_approvals",
            "priority": "high",
            "category": "approval",
            "title": f"{len(pending_approvals)} Director action(s) awaiting your decision",
            "description": f"Actions requiring creator approval: {', '.join(a.get('item', {}).get('action', 'action') for a in pending_approvals[:3])}.",
            "action_label": "Review Approvals",
            "action_type": "scroll_to",
            "target": "approvals",
        })

    # 3. Check auto story records needing review
    try:
        from app.services import auto_story
        records = auto_story.list_records()
        needs_review = [r for r in records if (r.get("review") or {}).get("state") == "needs_review"]
        if needs_review:
            first = needs_review[0]
            suggestions_list.append({
                "id": "auto_story_review",
                "priority": "high",
                "category": "review",
                "title": f"Review ready auto-story: '{first.get('name') or first.get('project_id')}'",
                "description": f"{len(needs_review)} story/reel(s) finished and waiting for your approval before publishing.",
                "action_label": "Review on Story Desk",
                "action_type": "navigate",
                "target": "story_desk",
            })
    except Exception:
        pass

    # 4. Check active projects needing intro or paused
    try:
        from core.models.project import Project
        from core.paths import PROJECTS_DIR
        if os.path.isdir(str(PROJECTS_DIR)):
            for pid in os.listdir(str(PROJECTS_DIR))[:15]:
                try:
                    p = Project.load(pid)
                    if p.status == "active":
                        last = p.steps_history[-1] if p.steps_history else None
                        if last and last.status == "paused_for_approval":
                            suggestions_list.append({
                                "id": f"pause_{pid}",
                                "priority": "high",
                                "category": "action",
                                "title": f"Unblock workflow step on '{p.name}'",
                                "description": f"Step '{last.step_name}' paused waiting for your review.",
                                "action_label": "Open Project",
                                "action_type": "open_project",
                                "target": pid,
                            })
                            break
                except Exception:
                    continue
    except Exception:
        pass

    # 5. Check if today's plan exists or needs replanning
    plan_obj = read_plan()
    if not plan_obj or not plan_obj.get("items"):
        suggestions_list.append({
            "id": "replan_needed",
            "priority": "medium",
            "category": "replan",
            "title": "Generate today's content plan",
            "description": "No active lineup planned for today. Click Replan to schedule episodes and reels across channels.",
            "action_label": "Replan Day",
            "action_type": "replan",
            "target": "plan",
        })
    else:
        unexecuted_make = [it for it in plan_obj.get("items", []) if it.get("action") in MAKE_ALLOWLIST]
        if unexecuted_make and active_count == 0:
            suggestions_list.append({
                "id": "run_make_items",
                "priority": "medium",
                "category": "action",
                "title": f"Run today's planned content ({len(unexecuted_make)} items ready)",
                "description": f"Planned items waiting to execute: {', '.join(it.get('action') for it in unexecuted_make[:3])}.",
                "action_label": "Run MAKE items",
                "action_type": "run_make",
                "target": "act",
            })

    # 6. Check top viral ideas from Topic Vault
    try:
        from app.services import topic_store
        vault = topic_store.load_topics()
        top_topics = sorted(vault, key=lambda t: t.get("viral_potential") or 0, reverse=True)
        if top_topics:
            best = top_topics[0]
            suggestions_list.append({
                "id": "vault_idea",
                "priority": "info",
                "category": "idea",
                "title": f"Top viral opportunity: '{best.get('topic')}'",
                "description": f"Channel: {best.get('channel')} · Viral potential: {best.get('viral_potential')}/100. Ready to outline or research.",
                "action_label": "View in Topic Vault",
                "action_type": "navigate",
                "target": "topics",
            })
    except Exception:
        pass

    # Determine primary suggestion
    primary = suggestions_list[0] if suggestions_list else {
        "id": "studio_running_smooth",
        "priority": "info",
        "category": "status",
        "title": "Studio is operating smoothly",
        "description": "No urgent blocks or pending approvals. Monitor active stories or explore new topics.",
        "action_label": "Replan Schedule",
        "action_type": "replan",
        "target": "plan",
    }

    return {
        "timestamp": _now(),
        "primary": primary,
        "suggestions": suggestions_list,
        "stories_in_progress": active_items,
        "active_count": active_count,
        "plan_items": (plan_obj.get("items") or []) if plan_obj else [],
    }


