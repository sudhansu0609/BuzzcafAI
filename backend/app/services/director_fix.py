"""Studio Director: troubleshoot and fix (docs/STUDIO_DIRECTOR_PLAN.md Part 4).

A hard allowlist of fix actions. SAFE ones run by themselves behind a guard
(not while the master pause is on, a cooldown per key, a cap per key and per
day); APPROVAL ones only run once the creator approved them. The Director
never edits code: a code bug becomes a dev ticket under
`knowledge/director/tickets/`. Every run is logged to
`knowledge/director/fixes.jsonl`.
"""
import json
import logging
import os
import re
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("buzzcaf_ai.director_fix")

COOLDOWN_S = 900
PER_KEY_DAY = 3
SAFE_PER_DAY = 12
TICKETS_PER_DAY = 5
MAX_FIXES_PER_REPLY = 2
FIXES_KEEP = 1000

_FIX_RE = re.compile(r"\[FIX:\s*([a-z_]+)\s*(?:\|\s*(\{.*?\}))?\s*\]", re.I | re.S)
_DIAG_RE = re.compile(r"\[DIAGNOSIS\](.*?)\[/DIAGNOSIS\]", re.I | re.S)


_LOCK = threading.RLock()


class _Refuse(Exception):
    """A handler declining to run (bad params, nothing to do)."""


def _sd():
    from app.services import studio_director
    return studio_director


def _dir(*parts: str) -> str:
    return os.path.join(_sd().DIRECTOR_DIR, *parts)


def _scrub(text: Any) -> str:
    from app.services import director_knowledge
    return director_knowledge._scrub(text)


# --- handlers (plain functions, local imports) ---------------------------------------------

def _fix_restart_claude_proxy(params: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import llm_proxies
    return {"claude_proxy": llm_proxies.ensure_claude()}


def _fix_restart_gemini_harness(params: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import llm_proxies
    return {"gemini_harness": llm_proxies.ensure_gemini()}


def _fix_start_searxng(params: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import searxng_service
    url = searxng_service.base_url(start=True)
    if not url:
        raise RuntimeError("SearXNG did not start")
    return {"url": url}


def _fix_start_buzzedit(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import health_checks
    for row in health_checks.check_buzzedit():
        if row.get("id") == "buzzedit" and row.get("state") == health_checks.OK:
            raise _Refuse("BuzzEdit is already answering")
    from app.api import produce_api
    health = produce_api.ensure_buzzedit_running(timeout=75)
    return {"buzzedit": "answering", "port": (health or {}).get("port")}


def _fix_repair_app_env(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import app_envs
    app = str(params.get("app") or "")
    if app not in app_envs.discover_apps():
        raise _Refuse(f"unknown app '{app}'")
    if (app_envs.status(app) or {}).get("ok"):
        raise _Refuse("environment is healthy; nothing to repair")
    res = app_envs.repair(app, wait=False)
    return {"app": app, "status": (res or {}).get("status")}


def _fix_offload_models(params: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import idle_offload
    return {"offloaded": bool(idle_offload.offload_now("studio director fix"))}


def _fix_kick_queue(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import produce_queue
    produce_queue.kick()
    return {"kicked": True}


def _fix_set_config(params: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import llm as llm_mod
    from app.services import director_knowledge
    key = str(params.get("key") or "")
    if not key:
        raise _Refuse("no key")
    if director_knowledge._SENSITIVE_KEY.search(key):
        raise _Refuse(f"'{key}' is a sensitive key")
    lowered = key.lower()
    if lowered.endswith(("_url", "_host", "_endpoint", "_uri")) or lowered in ("claude_url", "gemini_url"):
        raise _Refuse("URL/endpoint settings are changed by hand in Settings")
    cfg = llm_mod.load_config()
    if key not in cfg:
        raise _Refuse(f"'{key}' is not an existing config key")
    previous = cfg[key]
    value = params.get("value")
    if type(value) is not type(previous):
        raise _Refuse(f"'{key}' is a {type(previous).__name__}; got a {type(value).__name__}")
    cfg[key] = value
    llm_mod.save_config(cfg)
    return {"key": key, "previous": previous, "value": value,
            "rollback": {"action": "fix_set_config", "params": {"key": key, "value": previous}}}


def _fix_set_director_provider(params: Dict[str, Any]) -> Dict[str, Any]:
    sd = _sd()
    provider = params.get("provider")
    if provider not in sd.PROVIDERS:
        raise _Refuse(f"provider must be one of {list(sd.PROVIDERS)}")
    previous = sd.settings().get("provider")
    sd.set_settings({"provider": provider})
    return {"provider": provider, "previous": previous}


def _fix_restart_record(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import produce_queue
    item_id = str(params.get("item_id") or "")
    if not item_id:
        raise _Refuse("no item_id")
    produce_queue.restart(item_id)
    return {"restarted": item_id}


def _fix_master_resume(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import master_control
    master_control.resume()
    return {"resumed": True}


_SAFE: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "fix_restart_claude_proxy": _fix_restart_claude_proxy,
    "fix_restart_gemini_harness": _fix_restart_gemini_harness,
    "fix_start_searxng": _fix_start_searxng,
    "fix_start_buzzedit": _fix_start_buzzedit,
    "fix_repair_app_env": _fix_repair_app_env,
    "fix_offload_models": _fix_offload_models,
    "fix_kick_queue": _fix_kick_queue,
}
_APPROVAL: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "fix_set_config": _fix_set_config,
    "fix_set_director_provider": _fix_set_director_provider,
    "fix_restart_record": _fix_restart_record,
    "fix_master_resume": _fix_master_resume,
}
SAFE_FIXES = tuple(_SAFE)
APPROVAL_FIXES = tuple(_APPROVAL)
ALL_FIXES = tuple(sorted(SAFE_FIXES + APPROVAL_FIXES))

#: health check id -> the safe fix self_check runs when that check is not ok.
AUTO_FIX_FOR_CHECK = {"claude_proxy": "fix_restart_claude_proxy", "gemini": "fix_restart_gemini_harness",
                      "searxng": "fix_start_searxng", "queue": "fix_kick_queue"}

_DESCRIPTIONS = {
    "fix_restart_claude_proxy": "start the local Claude proxy if it is down",
    "fix_restart_gemini_harness": "start the Gemini harness if it is down",
    "fix_start_searxng": "start the local SearXNG web search",
    "fix_start_buzzedit": "start BuzzEdit when it is not answering (never restarts a running one)",
    "fix_repair_app_env": 'repair an app\'s environment, params {"app": "BuzzEdit"}',
    "fix_offload_models": "unload every local model (LM Studio, Ollama, ComfyUI)",
    "fix_kick_queue": "wake the production queue worker",
    "fix_set_config": 'change one existing config value, params {"key": "...", "value": ...} (same type; never keys)',
    "fix_set_director_provider": 'set the Director\'s own model, params {"provider": "claude|gemini|lm_studio|"}',
    "fix_restart_record": 'restart a queue item from scratch, params {"item_id": "..."}',
    "fix_master_resume": "release the master pause",
}


def fix_catalogue() -> str:
    lines = ["\n## Fixes (write [FIX: name | {json}] -- at most %d per reply)" % MAX_FIXES_PER_REPLY,
             "Safe (run now, guarded):"]
    lines += [f"  - {n}: {_DESCRIPTIONS.get(n, '')}" for n in SAFE_FIXES]
    lines.append("Needs his approval (queued, run when he approves):")
    lines += [f"  - {n}: {_DESCRIPTIONS.get(n, '')}" for n in APPROVAL_FIXES]
    return "\n".join(lines) + "\n"


# --- the log and the guard -----------------------------------------------------------------

def _key(action: str, params: Dict[str, Any]) -> str:
    params = params or {}
    if action == "fix_repair_app_env":
        return action + ":" + str(params.get("app") or "")
    if action in _APPROVAL:
        return action + ":" + str(params.get("item_id") or params.get("key") or "")
    return action + ":"


def _log_path() -> str:
    return _dir("fixes.jsonl")


def _log(row: Dict[str, Any]) -> None:
    sd = _sd()
    with _LOCK:
        rows = sd._read_jsonl(_log_path())
        rows.append(row)
        sd._write_jsonl(_log_path(), rows[-FIXES_KEEP:])


def fixes_today() -> List[Dict[str, Any]]:
    day = _sd().today()
    return [r for r in _sd()._read_jsonl(_log_path()) if str(r.get("at") or "").startswith(day)]


def guard(action: str, params: Dict[str, Any]) -> Optional[str]:
    """Why a safe fix must not run now, or None."""
    from app.services import master_control
    if master_control.is_paused():
        return "master pause is on"
    key = _key(action, params)
    ran = [r for r in fixes_today() if r.get("ran")]
    if len(ran) >= SAFE_PER_DAY:
        return f"daily cap of {SAFE_PER_DAY} safe fixes reached"
    same = [r for r in ran if r.get("key") == key]
    if len(same) >= PER_KEY_DAY:
        write_ticket(f"Fix not holding: {key}",
                     f"{key} ran {len(same)} times today and the problem came back. Fixes so far: "
                     + "; ".join(f"{r.get('at')} ok={r.get('ok')}" for r in same),
                     suggested_fix="Find the root cause; restarting does not hold.", once_per_day=True)
        return f"'{key}' ran {PER_KEY_DAY} times today and is not holding (ticket written)"
    if same:
        last = max(str(r.get("at") or "") for r in same)
        try:
            age = (datetime.now() - datetime.fromisoformat(last)).total_seconds()
        except ValueError:
            age = COOLDOWN_S + 1
        if age < COOLDOWN_S:
            return f"cooldown: '{key}' ran {int(age)}s ago"
    return None


def run_fix(action: str, params: Optional[Dict[str, Any]] = None, by: str = "chat",
            approved: bool = False) -> Dict[str, Any]:
    params = dict(params or {})
    sd = _sd()
    key = _key(action, params)
    row: Dict[str, Any] = {"at": sd._now(), "action": action, "key": key, "params": _scrub_params(params),
                           "by": by, "ran": False}
    if action not in ALL_FIXES:
        row["refused"] = f"unknown fix '{action}'"
        _log(row)
        return {"refused": row["refused"]}
    if action in _APPROVAL:
        if not approved:
            raise ValueError("needs approval")
        handler = _APPROVAL[action]
    else:
        with _LOCK:
            why = guard(action, params)
            if why:
                row["refused"] = why
                _log(row)
                return {"refused": why}
            handler = _SAFE[action]
            row["ran"] = True
    row["ran"] = True
    try:
        res = handler(params)
    except _Refuse as exc:
        row["ran"] = False
        row["refused"] = str(exc)[:300]
        _log(row)
        return {"refused": row["refused"]}
    except Exception as exc:  # noqa: BLE001 - a failed fix is a finding, not a crash
        logger.warning("director fix %s failed: %s", action, exc)
        row["ok"] = False
        row["error"] = _scrub(str(exc))[:300]
        _log(row)
        return {"ran": True, "ok": False, "error": row["error"]}
    row["ok"] = True
    row["result"] = _scrub(json.dumps(res, ensure_ascii=False, default=str))[:300]
    _log(row)
    out = dict(res) if isinstance(res, dict) else {"result": res}
    out.update({"ran": True, "ok": True})
    return out


def _scrub_params(params: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import director_knowledge
    pat = director_knowledge._SENSITIVE_KEY
    hide_value = bool(pat.search(str(params.get("key") or "")))
    out: Dict[str, Any] = {}
    for k, v in params.items():
        if pat.search(str(k)) or (k == "value" and hide_value):
            out[k] = "[REDACTED]"
        elif isinstance(v, str):
            out[k] = director_knowledge._scrub(v)
        else:
            out[k] = v
    return out


def _sensitive_config(action: str, params: Dict[str, Any]) -> bool:
    from app.services import director_knowledge
    return action == "fix_set_config" and bool(director_knowledge._SENSITIVE_KEY.search(str(params.get("key") or "")))


def handle_reply_fixes(reply: str, by: str = "chat") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in list(_FIX_RE.finditer(reply or ""))[:MAX_FIXES_PER_REPLY]:
        action = m.group(1).lower()
        try:
            params = json.loads(m.group(2)) if m.group(2) else {}
        except ValueError:
            params = {}
        if not isinstance(params, dict):
            params = {}
        if action in _SAFE:
            out.append({"action": action, "params": params, "result": run_fix(action, params, by=by)})
        elif action in _APPROVAL:
            if _sensitive_config(action, params):
                out.append({"action": action, "params": _scrub_params(params), "result": {"refused": "sensitive key"}})
                continue
            row = _sd().add_approval({"action": action, "params": params, "channel": None,
                                      "why": "from chat", "source": "director_fix"})
            out.append({"action": action, "params": params, "approval_id": row["id"]})
        else:
            out.append({"action": action, "params": params, "result": {"refused": f"unknown fix '{action}'"}})
    return out


def strip_fix_tags(reply: str) -> str:
    return _FIX_RE.sub("", reply or "")


# --- dev tickets ---------------------------------------------------------------------------

def _tickets_dir() -> str:
    return _dir("tickets")


def write_ticket(title: str, evidence: str, suspected_file: str = "", suggested_fix: str = "",
                 incident: Optional[str] = None, once_per_day: bool = False) -> Dict[str, Any]:
    sd = _sd()
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")[:50] or "ticket"
    directory = _tickets_dir()
    os.makedirs(directory, exist_ok=True)
    for name in sorted(os.listdir(directory)):
        path = os.path.join(directory, name)
        if name.endswith(".md") and name[11:] == f"{slug}.md":
            with open(path, encoding="utf-8") as f:
                text = f.read()
            if re.search(r"^state:\s*open\s*$", text, re.M):
                if once_per_day and f"Seen again {sd.today()}" in text:
                    return {"file": name, "state": "open", "seen_again": True}
                with open(path, "a", encoding="utf-8") as f:
                    f.write(f"\nSeen again {sd._now()}\n")
                return {"file": name, "state": "open", "seen_again": True}
    today = sd.today()
    new_today = [n for n in os.listdir(directory) if n.startswith(today)]
    if len(new_today) >= TICKETS_PER_DAY:
        return {"file": None, "state": "limit", "refused": f"{TICKETS_PER_DAY} tickets already written today"}
    name = f"{today}-{slug}.md"
    body = (
        "---\n"
        f"title: {_scrub(title)[:200]}\nstate: open\nat: {sd._now()}\nincident: {incident or ''}\n"
        "---\n\n"
        "## Evidence\n" + _scrub(evidence)[:3000] + "\n\n"
        "## Suspected file\n" + (_scrub(suspected_file)[:300] or "(unknown)") + "\n\n"
        "## Suggested fix\n" + (_scrub(suggested_fix)[:1500] or "(none)") + "\n"
    )
    sd._write_text(os.path.join(directory, name), body)
    return {"file": name, "state": "open"}


def list_tickets() -> List[Dict[str, Any]]:
    directory = _tickets_dir()
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory), reverse=True):
        if not name.endswith(".md"):
            continue
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as f:
                head = f.read(800)
        except OSError:
            continue

        def field(k: str) -> str:
            m = re.search(rf"^{k}:\s*(.*)$", head, re.M)
            return m.group(1).strip() if m else ""
        out.append({"file": name, "title": field("title"), "state": field("state"), "at": field("at")})
    return out


def close_ticket(file: str) -> Dict[str, Any]:
    if not file or file != os.path.basename(file) or "/" in file or "\\" in file or not file.endswith(".md"):
        raise ValueError("bad ticket name")
    path = os.path.join(_tickets_dir(), file)
    if not os.path.isfile(path):
        raise ValueError("no such ticket")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r"^state:\s*\w+\s*$", "state: closed", text, count=1, flags=re.M)
    _sd()._write_text(path, text)
    return {"file": file, "state": "closed"}


# --- reading the Studio's failures ---------------------------------------------------------

def failed_records() -> Dict[str, Any]:
    out: Dict[str, Any] = {"queue": [], "channels": {}}
    try:
        from app.services import produce_queue
        items = produce_queue.snapshot().get("items") or []
        out["queue"] = [{"item_id": i.get("id"), "project_id": i.get("project_id"), "brand": i.get("brand"),
                         "title": i.get("title"), "error": _scrub(str(i.get("error") or ""))[:300],
                         "checkpoint": i.get("checkpoint"), "attempts": i.get("attempts")}
                        for i in items if i.get("status") == "failed"][:15]
    except Exception as exc:  # noqa: BLE001
        out["queue_error"] = str(exc)[:200]
    try:
        view = _sd()._auto_story_channel_view().get("channels") or {}
        out["channels"] = {ch: b["failed"][:5] for ch, b in view.items() if b.get("failed")}
    except Exception as exc:  # noqa: BLE001
        out["channels_error"] = str(exc)[:200]
    return out


# --- self check (no model) and diagnose (model) --------------------------------------------

def _health_rows() -> List[Dict[str, Any]]:
    from app.services import director_knowledge
    return director_knowledge.health_report()


def self_check(say: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    from app.services import director_memory
    say = say or (lambda m: None)
    rows = _health_rows()
    queued = False
    try:
        from app.services import produce_queue
        queued = any(i.get("status") == "queued" for i in produce_queue.snapshot().get("items") or [])
    except Exception:  # noqa: BLE001
        pass
    out: Dict[str, Any] = {"fixed": [], "still_down": [], "refused": []}
    for row in rows:
        cid = row.get("id")
        if row.get("state") not in ("fail", "warn"):
            continue
        action = AUTO_FIX_FOR_CHECK.get(cid)
        if cid == "buzzedit" and queued:
            action = "fix_start_buzzedit"
        if not action:
            continue
        say(f"Fixing {cid}: {action}")
        res = run_fix(action, {}, by="self_check")
        if res.get("refused"):
            out["refused"].append({"check": cid, "action": action, "why": res["refused"]})
            continue
        now = next((r for r in _health_rows() if r.get("id") == cid), {})
        ok = now.get("state") == "ok"
        director_memory.add_incident(f"{cid} not ok: {row.get('summary')}", [row.get("summary")],
                                     "found by the nightly self-check", action, ok, resolved=[cid] if ok else [])
        (out["fixed"] if ok else out["still_down"]).append({"check": cid, "action": action})
    return out


def diagnose(problem: str, on_event: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    from app.services import director_memory, master_control, strategist_runner
    sd = _sd()
    say = on_event or (lambda m: None)
    master_control.wait_if_paused("studio_director: diagnose", say)
    from app.services import director_knowledge
    before = [r for r in _health_rows() if r.get("state") not in ("ok", "off")]
    past = director_memory.search_incidents(problem, 3)
    evidence = {
        "problem": problem,
        "health_not_ok": before,
        "log_digest": director_knowledge.log_digest(6)[:10],
        "failed_records": failed_records(),
        "past_incidents": past,
        "fixes_today": [{k: r.get(k) for k in ("at", "action", "by", "ran", "ok", "refused")}
                        for r in fixes_today()][-15:],
    }
    extra = (
        "\n\n" + director_memory.memory_section(problem) +
        "\n## Evidence\n" + strategist_runner.neutralise_tags(
            json.dumps(evidence, ensure_ascii=False, default=str)[:7000]) + "\n" +
        fix_catalogue() +
        "\nDiagnose the problem from the evidence only. Finish your reply with:\n"
        '[DIAGNOSIS]{"hypotheses": [{"cause": "", "evidence": "", "confidence": "high|medium|low"}], '
        '"fixes": [{"action": "fix_name", "params": {}, "why": ""}], '
        '"ticket": {"title": "", "suspected_file": "", "suggested_fix": ""} or null}[/DIAGNOSIS]\n'
        "Never claim to edit code; a code bug is a ticket."
    )
    say("Diagnosing")
    out = strategist_runner.chat(sd.AGENT_NAME, "Studio", problem, system_extra=extra,
                                 llm=sd._llm("director_chat"), max_turns=4, on_event=say)
    reply = str(out.get("reply") or "")
    result: Dict[str, Any] = {"hypotheses": [], "ran": [], "approvals": [], "ticket": None,
                              "incident_id": None, "resolved": [], "reply": _DIAG_RE.sub("", reply).strip()}
    if out.get("simulated"):
        return result
    diag: Dict[str, Any] = {}
    m = _DIAG_RE.search(reply)
    if m:
        try:
            diag = json.loads(m.group(1))
        except ValueError:
            diag = {}
    if not isinstance(diag, dict):
        diag = {}
    result["hypotheses"] = [h for h in (diag.get("hypotheses") or []) if isinstance(h, dict)][:5]
    worked_text = " ".join(str(r.get("fix") or "") for r in past if r.get("worked"))
    fixes = [f for f in (diag.get("fixes") or []) if isinstance(f, dict)]
    fixes.sort(key=lambda f: 0 if str(f.get("action")) in worked_text else 1)
    safe_run = 0
    for f in fixes:
        action = str(f.get("action") or "")
        params = f.get("params") if isinstance(f.get("params"), dict) else {}
        if action in _SAFE:
            if safe_run >= 3:
                continue
            safe_run += 1
            result["ran"].append({"action": action, "params": params, "result": run_fix(action, params, by="diagnose")})
        elif action in _APPROVAL and len(result["approvals"]) < 3:
            if _sensitive_config(action, params):
                result["ran"].append({"action": action, "params": _scrub_params(params),
                                      "result": {"refused": "sensitive key"}})
                continue
            row = sd.add_approval({"action": action, "params": params, "channel": None,
                                   "why": str(f.get("why") or "")[:300], "source": "diagnose"})
            result["approvals"].append({"action": action, "params": params, "approval_id": row["id"]})
    ticket = diag.get("ticket")
    if isinstance(ticket, dict) and ticket.get("title"):
        result["ticket"] = write_ticket(str(ticket["title"]), json.dumps(evidence, ensure_ascii=False, default=str),
                                        str(ticket.get("suspected_file") or ""),
                                        str(ticket.get("suggested_fix") or ""))
    ran_any = any(r["result"].get("ran") for r in result["ran"])
    if ran_any:
        after_ok = {r.get("id") for r in _health_rows() if r.get("state") == "ok"}
        result["resolved"] = [r.get("id") for r in before if r.get("id") in after_ok]
    cause = (result["hypotheses"][0].get("cause") if result["hypotheses"] else "") or ""
    fix_names = ", ".join(r["action"] for r in result["ran"] + result["approvals"])
    inc = director_memory.add_incident(
        problem, [r.get("summary") for r in before][:5], cause, fix_names,
        bool(result["resolved"]) if ran_any else None, resolved=result["resolved"],
        ticket=(result["ticket"] or {}).get("file"))
    result["incident_id"] = inc["id"]
    return result
