"""Estimates for the nightly run, checks before it, and a live view while it
runs (2026-10-26). The creator: "I can't keep waiting the whole night to find
that videos failed in the morning."

- `forecast()`: per long-form slot, how long each step will take (the median
  of the same step in recent projects; script and rewrite steps scaled to the
  target minutes), when each video should be ready, which ones would finish
  after Windows' time limit kills the run, and how many Claude tokens the
  night will use (measured per step from `integrations.llm_usage` once there
  are records, a fixed table until then).
- `preflight()`: what made past nights fail, checked now: every model the
  routes use answers, Gemma loaded with one slot, the master pause, the
  nightly tasks and their time limit, a production stuck for hours, disk.
- `live()`: the running batch against the forecast: the step each slot is on
  and how far over its estimate, failed slots with the reason, and a run whose
  process died (killed by Windows, a crash) instead of "running" forever.
"""
import glob
import json
import logging
import os
import shutil
import statistics
import subprocess
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.paths import KNOWLEDGE_DIR, PROJECTS_DIR

logger = logging.getLogger("buzzcaf_ai.run_forecast")

# Minutes when a step has no history yet; script/rewrite are per target minute.
DEFAULT_STEP_MIN = {"research": 25.0, "shorts": 5.0, "seo": 15.0, "planning": 8.0, None: 5.0}
DEFAULT_PER_TARGET_MIN = {"script": 2.0, "rewrite": 0.8}
STRATEGIST_MIN = 8.0
AFTER_BLOCK_DEFAULT_MIN = 45.0
# Claude tokens (in, out) per step when nothing is measured yet: the estimate
# given to the creator on 2026-10-26. script/rewrite are for a 25-minute video.
STATIC_TOKENS = {"research": (220_000, 12_000), "script": (275_000, 20_000), "rewrite": (60_000, 15_000),
                 "shorts": (40_000, 3_000), "seo": (90_000, 6_000), "planning": (40_000, 8_000),
                 "strategist": (60_000, 5_000)}
SAMPLES = 6
MAX_STEP_S = 4 * 3600   # longer = an approval wait, not work

_cache: Dict[str, Tuple[float, Any]] = {}
_cache_lock = threading.Lock()


def _cached(key: str, ttl: float, fn):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (time.time(), value)
    return value


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _parse(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def _fmt(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


# --- history ------------------------------------------------------------------------

def _step_samples() -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """(workflow, step) -> newest-first [{s, target, nightly}] of completed steps."""
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for path in glob.glob(os.path.join(str(PROJECTS_DIR), "*", "project.json")):
        try:
            with open(path, encoding="utf-8") as f:
                p = json.load(f)
        except (OSError, ValueError):
            continue
        meta = p.get("metadata") or {}
        nightly = bool(meta.get("nightly_longform") or meta.get("allow_all"))
        try:
            target = float(meta.get("target_duration_minutes") or 0) or None
        except (TypeError, ValueError):
            target = None
        for h in p.get("steps_history") or []:
            if h.get("status") != "completed":
                continue
            a, b = _parse(h.get("started_at")), _parse(h.get("completed_at"))
            if not a or not b:
                continue
            s = (b - a).total_seconds()
            if s < 5 or s > MAX_STEP_S:
                continue
            out[(p.get("workflow_name") or "", h.get("step_name") or "")].append(
                {"s": s, "target": target, "nightly": nightly, "at": b.isoformat()})
    for key in out:
        out[key].sort(key=lambda r: r["at"], reverse=True)
    return out


def _samples() -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    return _cached("samples", 120, _step_samples)


def _p75(values: List[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, -(-3 * len(ordered) // 4) - 1)]


def _step_minutes(workflow: str, step: str, job: Optional[str], minutes: float) -> Tuple[float, float, str]:
    """(typical minutes, worst case, how it was worked out) for one step.

    The same step took 3 min one night and 32 the next (a model that timed out
    first, 2026-10-24..26), so the typical figure is the upper quartile of the
    recent runs, not the median, and the slowest recent run is the worst case."""
    rows = _samples().get((workflow, step), [])
    nightly = [r for r in rows if r["nightly"]]
    rows = (nightly if len(nightly) >= 2 else rows)[:SAMPLES]
    if job in DEFAULT_PER_TARGET_MIN:
        rates = [r["s"] / 60 / r["target"] for r in rows if r["target"]]
        if rates:
            return (_p75(rates) * minutes, max(rates) * minutes,
                    f"{len(rates)} recent runs, scaled to {minutes:g} min")
        d = DEFAULT_PER_TARGET_MIN[job] * minutes
        return d, d * 2, "no history yet (default)"
    if rows:
        mins = [r["s"] / 60 for r in rows]
        return _p75(mins), max(mins), f"{len(mins)} recent runs"
    d = DEFAULT_STEP_MIN.get(job, DEFAULT_STEP_MIN[None])
    return d, d * 2, "no history yet (default)"


def _strategist_minutes() -> float:
    """Planning time per slot, from the last run's log when it has one."""
    try:
        from app.services import longform_nightly
        log = longform_nightly.read_status().get("log") or []
    except Exception:  # noqa: BLE001
        return STRATEGIST_MIN
    starts: Dict[str, datetime] = {}
    spans: List[float] = []
    for entry in log:
        try:
            t = datetime.strptime(entry.get("at", ""), "%H:%M:%S")
        except ValueError:
            continue
        text, ch = entry.get("text", ""), entry.get("channel", "")
        if "thinking (turn 1)" in text:
            starts[ch] = t
        elif text.startswith("plan:") and ch in starts:
            spans.append((t - starts.pop(ch)).total_seconds() / 60)
    spans = [s for s in spans if 0 < s < 120]
    return statistics.median(spans) if spans else STRATEGIST_MIN


def _measured_minutes() -> Dict[Tuple[str, str, str], List[float]]:
    """(workflow, step, provider) -> model minutes per run of that step, for
    runs where that provider answered most of the calls (the usage records).
    A step that moved to another model (Gemma at night) is timed on it, not on
    the history it built with the old one."""
    from integrations import llm_usage
    runs: Dict[Tuple[str, str, str], Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in llm_usage.calls(days=21):
        if r.get("step", "").count("/") < 2 or not r.get("ok"):
            continue
        wf, step, project = r["step"].split("/", 2)
        runs[(wf, step, project)][r.get("provider") or ""] += float(r.get("s") or 0)
    out: Dict[Tuple[str, str, str], List[float]] = defaultdict(list)
    for (wf, step, _), per_provider in runs.items():
        main = max(per_provider, key=per_provider.get)
        if per_provider[main] >= 0.7 * sum(per_provider.values()):
            out[(wf, step, main)].append(sum(per_provider.values()) / 60)
    return out


def _step_tokens() -> Dict[Tuple[str, str], Tuple[int, int, int]]:
    """(workflow, step) -> median Claude (in, out) per run of that step, and runs seen."""
    from integrations import llm_usage
    per_run: Dict[Tuple[str, str, str], List[int]] = defaultdict(lambda: [0, 0])
    for r in llm_usage.calls(days=21):
        if r.get("provider") != "claude" or r.get("step", "").count("/") < 2:
            continue
        wf, step, project = r["step"].split("/", 2)
        acc = per_run[(wf, step, project)]
        acc[0] += r.get("in", 0)
        acc[1] += r.get("out", 0)
    grouped: Dict[Tuple[str, str], List[List[int]]] = defaultdict(list)
    for (wf, step, _), acc in per_run.items():
        grouped[(wf, step)].append(acc)
    return {k: (int(statistics.median(a[0] for a in v)), int(statistics.median(a[1] for a in v)), len(v))
            for k, v in grouped.items()}


# --- who answers ----------------------------------------------------------------------

def _usable(provider: str, cfg: Dict[str, Any]) -> bool:
    """Would the provider even be tried? (A cloud one without a key is skipped.)"""
    from integrations import llm
    if provider == "openai":
        return bool(cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY")) and not cfg.get("local_only")
    if provider == "gemini":
        return llm.is_local_gemini(cfg) or bool(cfg.get("gemini_api_key") and not cfg.get("local_only"))
    if provider == "claude":
        return llm.claude_configured(cfg)
    return True


def _answering(job: Optional[str], agent: str) -> Dict[str, str]:
    """The provider and model the nightly run will ask first for this job and
    persona (the Night routes: the run's own process always uses them)."""
    def work():
        from core.agent import agent_registry
        from integrations.llm import LLMService, llm_job, route_profile_as
        definition = agent_registry.get(agent) if agent else None
        tier = definition.model_tier if definition else "strong"
        svc = LLMService()
        # The forecast is for 03:00, not this minute: a render holding the GPU
        # now (which moves local models behind the others) is a pre-flight
        # warning of its own, not tonight's routing.
        svc.ignore_render = True
        with route_profile_as("night"), llm_job(job):
            order = [p for p in svc._provider_order(tier) if _usable(p, svc.config)]
            first = order[0] if order else ""
            return {"provider": first, "model": svc._model_for(first, tier) if first else "",
                    "then": order[1] if len(order) > 1 else ""}
    try:
        return _cached(f"answer:{job}:{agent}", 60, work)
    except Exception as exc:  # noqa: BLE001
        logger.debug("could not work out the provider for %s/%s: %s", job, agent, exc)
        return {"provider": "", "model": "", "then": ""}


# --- forecast -------------------------------------------------------------------------

def _start_time() -> datetime:
    from integrations.llm import load_config
    cfg = load_config()
    hhmm = str(cfg.get("longform_time") or cfg.get("nightly_time") or "03:00")
    try:
        hh, mm = (int(x) for x in hhmm.split(":")[:2])
    except ValueError:
        hh, mm = 3, 0
    now = datetime.now()
    start = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return start if start > now else start + timedelta(days=1)


def _after_block_minutes() -> float:
    """The Shorts task (Shorts batch, Auto Story, Director) shares the run lock."""
    try:
        with open(os.path.join(str(KNOWLEDGE_DIR), "nightly", "last_run.json"), encoding="utf-8") as f:
            tasks = json.load(f).get("tasks") or []
        secs = sum(float(t.get("seconds") or 0) for t in tasks if t.get("task") != "longform")
        return secs / 60 if secs > 0 else AFTER_BLOCK_DEFAULT_MIN
    except (OSError, ValueError):
        return AFTER_BLOCK_DEFAULT_MIN


def plan_steps(workflow: str) -> List[Any]:
    """The steps the nightly run carries a project through (up to the first one
    that needs the creator himself)."""
    from app.services import longform_nightly
    from runtime.workflow import WorkflowEngine
    wf = WorkflowEngine().get_workflow(workflow)
    steps = []
    for step in (wf.steps if wf else []):
        if longform_nightly._needs_creator(step.name) or len(steps) >= longform_nightly.MAX_STEPS:
            break
        steps.append(step)
    return steps


def slot_estimate(channel: str, minutes: float) -> Dict[str, Any]:
    from app.services import longform_nightly
    from integrations.llm import job_for_asset
    workflow = longform_nightly.WORKFLOWS.get(channel, "")
    tokens = _cached("tokens", 300, _step_tokens)
    strat = _answering("strategist", longform_nightly.strategist_for(channel))
    claude_in = claude_out = 0
    if strat["provider"] == "claude":
        claude_in, claude_out = STATIC_TOKENS["strategist"]
    plan_min = _strategist_minutes()
    steps = [{"name": "Strategist planning", "job": "strategist", **strat,
              "est_min": round(plan_min, 1), "worst_min": round(plan_min * 2, 1), "basis": "last run's planning time"}]
    measured_all = _cached("measured", 300, _measured_minutes)
    for step in plan_steps(workflow):
        job = job_for_asset(step.output_asset_type)
        est, worst, basis = _step_minutes(workflow, step.name, job, minutes)
        who = _answering(job, step.agent_role)
        measured = measured_all.get((workflow, step.name, who["provider"]), [])[:SAMPLES]
        if measured:
            est, worst = _p75(measured), max(measured)
            basis = f"measured on {who['provider']}, {len(measured)} run(s)"
        elif who["provider"] == "lm_studio" and job in DEFAULT_PER_TARGET_MIN:
            # Gemma 4 12B on this PC: ~35 tok/s writing, ~1,600 tok/s reading
            # (2026-10-26): ~0.55 min of script per target minute, ~0.3 rewrite.
            est = (0.55 if job == "script" else 0.3) * minutes
            worst = est * 2
            basis = "Gemma speed measured 2026-10-26 (no Gemma runs of this step yet)"
        if who["provider"] == "claude":
            measured = tokens.get((workflow, step.name))
            if measured:
                t_in, t_out = measured[0], measured[1]
            else:
                base = STATIC_TOKENS.get(job or "", (30_000, 4_000))
                scale = minutes / 25.0 if job in DEFAULT_PER_TARGET_MIN else 1.0
                t_in, t_out = int(base[0] * scale), int(base[1] * scale)
            claude_in += t_in
            claude_out += t_out
        steps.append({"name": step.name, "job": job or "other", **who, "est_min": round(est, 1),
                      "worst_min": round(worst, 1), "basis": basis})
    return {"channel": channel, "workflow": workflow, "minutes": minutes, "steps": steps,
            "est_min": round(sum(s["est_min"] for s in steps), 1),
            "worst_min": round(sum(s["worst_min"] for s in steps), 1),
            "claude_in": claude_in, "claude_out": claude_out}


def forecast() -> Dict[str, Any]:
    return _cached("forecast", 60, _forecast)


def _forecast() -> Dict[str, Any]:
    from app.services import longform_nightly
    from integrations import nightly_task
    s = longform_nightly.settings()
    limit_h = nightly_task.time_limit_hours()
    start = _start_time()
    deadline = start + timedelta(hours=limit_h)
    slots, t, worst_t = [], start, start
    per_channel: Dict[str, Dict[str, Any]] = {}
    for channel in s["channels"]:
        minutes = float(s["minutes"].get(channel, longform_nightly.DEFAULT_MINUTES))
        est = per_channel.setdefault(channel, slot_estimate(channel, minutes))
        for slot in range(1, s["per_channel"] + 1):
            end = t + timedelta(minutes=est["est_min"])
            worst_t += timedelta(minutes=est["worst_min"])
            slots.append({**est, "slot": slot, "start": t.isoformat(timespec="minutes"),
                          "end": end.isoformat(timespec="minutes"), "worst_end": worst_t.isoformat(timespec="minutes"),
                          "fits": end <= deadline, "at_risk": end <= deadline < worst_t})
            t = end
    after_min = _after_block_minutes()
    after_end = t + timedelta(minutes=after_min)
    fits = sum(1 for x in slots if x["fits"])
    at_risk = sum(1 for x in slots if x["at_risk"])
    total_min = sum(x["est_min"] for x in slots)
    worst_total = sum(x["worst_min"] for x in slots)
    claude_in = sum(x["claude_in"] for x in slots)
    claude_out = sum(x["claude_out"] for x in slots)
    if not s["enabled"]:
        verdict = "The long-form nightly run is off."
    elif not slots:
        verdict = "No channels are picked for the long-form nightly run."
    else:
        verdict = (f"{len(slots)} video(s) ≈ {_fmt(total_min)} (up to {_fmt(worst_total)} on a slow night); "
                   + (f"all finish by {datetime.fromisoformat(slots[-1]['end']):%H:%M}"
                      if fits == len(slots) else
                      f"only {fits} finish before {deadline:%H:%M} ({limit_h} h limit)")
                   + (f"; {at_risk} at risk on a slow night" if at_risk else ""))
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "enabled": s["enabled"], "start": start.isoformat(timespec="minutes"),
        "deadline": deadline.isoformat(timespec="minutes"), "time_limit_hours": limit_h,
        "slots": slots, "total_slots": len(slots), "fits_count": fits, "at_risk_count": at_risk,
        "longform_min": round(total_min, 1), "longform_worst_min": round(worst_total, 1),
        "after": {"label": "Shorts batch, Auto Story and Director (same run lock)", "est_min": round(after_min, 1),
                  "start": t.isoformat(timespec="minutes"), "end": after_end.isoformat(timespec="minutes"),
                  "fits": after_end <= deadline},
        "end": after_end.isoformat(timespec="minutes"),
        "claude": {"in": claude_in, "out": claude_out},
        "verdict": verdict,
    }


# --- preflight ------------------------------------------------------------------------

def _check(cid: str, label: str, state: str, summary: str, detail: str = "", fix: str = "") -> Dict[str, Any]:
    return {"id": cid, "label": label, "state": state, "summary": summary, "detail": detail, "fix": fix}


def _providers_tonight(fc: Dict[str, Any]) -> Dict[str, List[str]]:
    """provider -> the jobs that will ask it (first or as their fallback)."""
    from integrations.llm import job_routes
    used: Dict[str, set] = defaultdict(set)
    for slot in fc.get("slots", []):
        for step in slot["steps"]:
            for p in (step.get("provider"), step.get("then")):
                if p:
                    used[p].add(step["job"])
    for job, route in job_routes(profile="night").items():
        if route.get("fallback") and job in {s["job"] for sl in fc.get("slots", []) for s in sl["steps"]}:
            used[route["fallback"]].add(job)
    return {p: sorted(j) for p, j in used.items()}


def _task_limit_hours(scope: str) -> Optional[int]:
    from integrations import nightly_task
    try:
        proc = subprocess.run(["schtasks", "/query", "/tn", nightly_task.TASK_NAMES[scope], "/xml"],
                              capture_output=True, text=True, timeout=15,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            return None
        import re
        m = re.search(r"<ExecutionTimeLimit>PT(\d+)H</ExecutionTimeLimit>", proc.stdout)
        return int(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def preflight(fresh: bool = False) -> Dict[str, Any]:
    if fresh:
        clear_cache()
    return _cached("preflight", 300, _preflight)


def _preflight() -> Dict[str, Any]:
    from integrations import llm, nightly_task
    cfg = llm.load_config()
    fc = forecast()
    checks: List[Dict[str, Any]] = []

    try:
        from app.services import master_control
        st = master_control.state()
        checks.append(_check("master_pause", "Master pause", "fail" if st.get("paused") else "ok",
                             f"Paused since {st.get('since')} -- nothing runs tonight" if st.get("paused")
                             else "Not paused"))
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("master_pause", "Master pause", "warn", "Could not read it", str(exc)[:200]))

    used = _providers_tonight(fc)
    for provider, jobs in sorted(used.items()):
        checks.append(_provider_check(provider, jobs, cfg))

    if fc["total_slots"]:
        need_h = (datetime.fromisoformat(fc["end"]) - datetime.fromisoformat(fc["start"])).total_seconds() / 3600
        if fc["fits_count"] == fc["total_slots"] and fc["after"]["fits"]:
            checks.append(_check("time_fit", "Fits the night", "warn" if fc["at_risk_count"] else "ok", fc["verdict"],
                                 "On a slow night (models timing out before they fall back) the last videos would "
                                 "run past the limit." if fc["at_risk_count"] else ""))
        else:
            checks.append(_check(
                "time_fit", "Fits the night", "fail" if fc["fits_count"] == 0 else "warn", fc["verdict"],
                f"Everything together needs ~{need_h:.1f} h from {fc['start'][-5:]}; Windows stops the run after "
                f"{fc['time_limit_hours']} h. Fewer videos per channel or fewer channels (Scheduler Desk -> Long "
                "form), faster models for the slow steps (Model Routing), or a longer limit."))

    for scope in ("shorts", "longform"):
        status = nightly_task.status(scope)
        name = "Nightly Shorts task" if scope == "shorts" else "Nightly long-form task"
        if not status.get("registered"):
            checks.append(_check(f"task_{scope}", name, "warn", "Not registered", "Turn it on in the Scheduler Desk."))
            continue
        limit = _task_limit_hours(scope)
        want = nightly_task.time_limit_hours()
        if limit is not None and limit < want:
            checks.append(_check(f"task_{scope}", name, "fail", f"Windows stops it after {limit} h",
                                 f"The setting is {want} h; re-register the task to apply it.", fix="reregister_tasks"))
        else:
            checks.append(_check(f"task_{scope}", name, "ok",
                                 f"Next {status.get('next_run_time', '?')}; limit {limit or want} h"))

    try:
        from app.services import produce_queue
        item = produce_queue.running_item()
        if item:
            stage = (item.get("stage_times") or [{}])[-1]
            since = _parse(stage.get("started_at"))
            hours = (datetime.now() - since).total_seconds() / 3600 if since else 0
            state = "warn" if hours >= 2 else "ok"
            checks.append(_check("production", "Production queue", state,
                                 f"'{item.get('title')}' at {stage.get('stage', '?')} for {hours:.1f} h",
                                 (str(item.get("message") or "")[:300] + " While BuzzEdit holds the GPU, steps "
                                  "routed to Gemma go to their fallback (Claude).").strip()))
    except Exception as exc:  # noqa: BLE001
        logger.debug("queue check skipped: %s", exc)

    try:
        from app.services import app_envs
        for app in app_envs.discover_apps():
            st = app_envs.status(app)
            if app != "BuzzEdit" and st["ok"]:
                continue
            last = st.get("self_test") or {}
            when = str(last.get("at") or "")[:16].replace("T", " ")
            checks.append(_check(
                f"app_{app}", f"{app} environment", "ok" if st["ok"] else "fail",
                (f"Works (self-test passed {when})" if last else "Files present") if st["ok"]
                else "Broken: " + "; ".join(st["missing"])[:200],
                "" if st["ok"] else "The nightly run repairs it first; Fix repairs it now.",
                fix="" if st["ok"] else f"repair_app:{app}"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("app env check skipped: %s", exc)

    try:
        free_gb = shutil.disk_usage(str(PROJECTS_DIR)).free / 1024 ** 3
        checks.append(_check("disk", "Disk space", "ok" if free_gb >= 20 else "warn",
                             f"{free_gb:.0f} GB free on the projects drive"))
    except OSError:
        pass

    order = {"fail": 0, "warn": 1, "off": 2, "ok": 3}
    overall = min((c["state"] for c in checks), key=lambda s: order.get(s, 3)) if checks else "ok"
    return {"at": datetime.now().isoformat(timespec="seconds"), "overall": overall, "checks": checks,
            "forecast": {k: fc[k] for k in ("verdict", "start", "deadline", "fits_count", "total_slots", "claude")}}


def _provider_check(provider: str, jobs: List[str], cfg: Dict[str, Any]) -> Dict[str, Any]:
    from integrations import llm
    label = {"claude": "Claude proxy", "lm_studio": "Gemma (LM Studio)", "ollama": "Ollama",
             "gemini": "Gemini harness", "llamacpp": "llama.cpp", "openai": "OpenAI"}.get(provider, provider)
    for_jobs = "for " + ", ".join(llm.LLM_JOBS.get(j, j) for j in jobs)
    cid = f"provider_{provider}"
    try:
        if provider == "claude":
            if not llm.claude_configured(cfg):
                return _check(cid, label, "fail", "No API key (Settings -> Claude API)", for_jobs)
            base = llm.claude_settings(cfg)["url"].rsplit("/v1", 1)[0]
            h = requests.get(f"{base}/health", timeout=6).json()
            ready = [b for b in h.get("backends", []) if b.get("pool_ready")]
            cooling = [b.get("cooling_until") for b in h.get("backends", []) if b.get("cooling_until")]
            if not h.get("ok") or not ready:
                return _check(cid, label, "fail", "Answers, but no worker is ready", for_jobs)
            return _check(cid, label, "warn" if cooling else "ok",
                          f"Ready (usage limit cooling until {cooling[0]})" if cooling else "Ready", for_jobs)
        if provider == "lm_studio":
            model = str(cfg.get("lm_studio_model") or "")
            r = requests.get("http://localhost:1234/api/v0/models", timeout=4)
            entry = next((m for m in r.json().get("data", []) if m.get("id") == model), None)
            if not entry:
                return _check(cid, label, "fail", f"'{model}' is not in LM Studio", for_jobs)
            if entry.get("state") != "loaded":
                return _check(cid, label, "ok", f"{model}: not loaded; loaded with one slot at the first call", for_jobs)
            slots = llm.lm_studio_loaded_parallel(model)
            ctx = entry.get("loaded_context_length") or 0
            if slots and slots > 1:
                return _check(cid, label, "warn", f"{model}: {slots} slots x {ctx // slots} tokens",
                              "Reloaded with one slot before its first call tonight; Fix does it now.",
                              fix="reload_gemma")
            return _check(cid, label, "ok", f"{model}: loaded, 1 slot, {ctx} tokens", for_jobs)
        if provider == "gemini":
            url = str(cfg.get("gemini_url") or llm.GEMINI_DEFAULT_URL).rstrip("/")
            t0 = time.time()
            ok = requests.get(f"{url}/health", timeout=8).json().get("ok")
            return _check(cid, label, "ok" if ok else "fail",
                          f"Answers ({time.time() - t0:.1f} s ping); long prompts may still time out after "
                          f"{llm.GEMINI_TIMEOUT_SECONDS} s" if ok else "Not answering", for_jobs)
        if provider == "ollama":
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=4)
            names = [m.get("name") for m in r.json().get("models", [])]
            return _check(cid, label, "ok" if names else "warn", f"{len(names)} model(s) installed", for_jobs)
        return _check(cid, label, "ok", "Configured", for_jobs)
    except Exception as exc:  # noqa: BLE001
        return _check(cid, label, "fail", "Not answering", f"{for_jobs}: {str(exc)[:200]}")


def fix(fix_id: str) -> Dict[str, Any]:
    """The one-click fixes preflight offers."""
    from integrations import llm, nightly_task
    if fix_id == "reregister_tasks":
        cfg = llm.load_config()
        done = []
        for scope in ("shorts", "longform"):
            if nightly_task.status(scope).get("registered"):
                hhmm = str(cfg.get("longform_time") or cfg.get("nightly_time") or "03:00") if scope == "longform" \
                    else str(cfg.get("nightly_time") or "03:00")
                nightly_task.register(hhmm, scope)
                done.append(scope)
        clear_cache()
        return {"ok": True, "message": f"Re-registered {', '.join(done) or 'nothing'} with a "
                                       f"{nightly_task.time_limit_hours()} h limit"}
    if fix_id.startswith("repair_app:"):
        from app.services import app_envs
        app = fix_id.split(":", 1)[1]
        if app not in app_envs.discover_apps():
            raise ValueError(f"unknown app: {app}")
        out = app_envs.ensure_working(app)
        clear_cache()
        return {"ok": out["ok"], "message": f"{app}: " + ("works again" if out["ok"] else "still broken, see its logs\\setup.log")}
    if fix_id == "reload_gemma":
        model = str(llm.load_config().get("lm_studio_model") or "")
        ctx = llm.lm_studio_loaded_context(model) or llm.lm_studio_context_length()
        ok = llm.reload_lm_studio_model(model, ctx)
        clear_cache()
        return {"ok": ok, "message": f"{model} reloaded with one slot, {ctx} tokens" if ok else "Reload failed"}
    raise ValueError(f"unknown fix: {fix_id}")


# --- live -----------------------------------------------------------------------------

def _run_process_alive() -> Optional[bool]:
    """Is the nightly process holding the run lock alive? None when no lock."""
    lock = os.path.join(str(KNOWLEDGE_DIR), "nightly", "running.lock")
    try:
        with open(lock, encoding="utf-8") as f:
            pid = int(f.read().strip() or 0)
    except (OSError, ValueError):
        return None
    try:
        import psutil
        return psutil.pid_exists(pid) and "python" in psutil.Process(pid).name().lower()
    except Exception:  # noqa: BLE001
        return None


def live() -> Dict[str, Any]:
    from app.services import longform_nightly
    st = longform_nightly.read_status()
    state = st.get("state", "idle")
    started = _parse(st.get("started_at"))
    now = datetime.now()
    if state == "running":
        # The status file says running; is anybody? A killed process leaves
        # its lock file behind, so the lock's pid is what counts.
        thread = getattr(longform_nightly, "_thread", None)
        if not (thread is not None and thread.is_alive()) and _run_process_alive() is not True:
            state = "died"
    estimates: Dict[str, Dict[str, Any]] = {}
    for task in st.get("tasks") or []:
        ch = task["channel"]
        if ch not in estimates:
            estimates[ch] = _cached(f"slot:{ch}:{task.get('minutes')}", 300,
                                    lambda c=ch, m=task.get("minutes"): slot_estimate(
                                        c, float(m or longform_nightly.settings()["minutes"].get(c, 8.0))))
    step_started: Dict[str, datetime] = {}
    for entry in st.get("log") or []:
        text = entry.get("text", "")
        if text.startswith("step: ") or "thinking (turn 1)" in text:
            try:
                t = datetime.strptime(entry["at"], "%H:%M:%S").time()
            except (KeyError, ValueError):
                continue
            base = started.date() if started else now.date()
            when = datetime.combine(base, t)
            if started and when < started - timedelta(minutes=1):
                when += timedelta(days=1)
            step_started[entry.get("channel", "")] = when
    tasks, remaining_min, problems = [], 0.0, []
    for task in st.get("tasks") or []:
        est = estimates.get(task["channel"]) or {"steps": [], "est_min": 0}
        stage = task.get("stage") or "queued"
        row = {**{k: task.get(k) for k in ("channel", "slot", "stage", "topic", "project_id", "detail")},
               "est_min": est["est_min"], "flag": ""}
        names = [s["name"] for s in est["steps"]]
        if stage in ("done", "skipped"):
            pass
        elif stage == "failed":
            row["flag"] = "failed"
            problems.append(f"{task['channel']} slot {task['slot']} failed: {task.get('detail') or 'see the log'}")
        elif stage == "queued":
            remaining_min += est["est_min"]
        else:
            idx = names.index(stage) if stage in names else (0 if stage == "strategist planning" else -1)
            step_est = est["steps"][idx]["est_min"] if idx >= 0 else 0
            since = step_started.get(task["channel"])
            elapsed = (now - since).total_seconds() / 60 if since else 0
            row.update(step_est_min=step_est, step_elapsed_min=round(elapsed, 1))
            left_here = sum(s["est_min"] for s in est["steps"][idx + 1:]) if idx >= 0 else 0
            remaining_min += max(0.0, step_est - elapsed) + left_here
            if state == "running" and step_est and elapsed > max(2 * step_est, step_est + 15):
                row["flag"] = "slow"
                problems.append(f"{task['channel']} slot {task['slot']}: '{stage}' has run {_fmt(elapsed)} "
                                f"(estimate {_fmt(step_est)})")
        tasks.append(row)
    if state == "died":
        problems.insert(0, f"The run stopped at {str(st.get('updated_at', ''))[11:16]} without finishing "
                           "(the process is gone -- killed by Windows' time limit, a crash or a restart).")
    eta = (now + timedelta(minutes=remaining_min)).isoformat(timespec="minutes") if state == "running" else None
    return {"state": state, "started_at": st.get("started_at"), "updated_at": st.get("updated_at"),
            "finished_at": st.get("finished_at"), "error": st.get("error"), "tasks": tasks,
            "remaining_min": round(remaining_min, 1) if state == "running" else 0, "eta": eta,
            "problems": problems}
