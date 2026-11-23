"""
Health checks that report the silent failures (2026-10-22).

Why: the Studio's watchdogs fail quietly. The self-restart check threw for
2.5 hours and the Studio sat on old code; the idle offload swallowed the
same error as "busy" and every model stayed loaded; a watcher died with a
session; LM Studio reloaded Gemma at 16k and every long step came back
truncated. Each of those was one log line nobody reads. This module asks
every moving part for its real state and says, per row, ok / warn / fail
and the last error in plain words. `GET /api/health/checks` runs them (a
few seconds, every check with its own short timeout) and the Health page
shows them with a re-check button and a 60 s refresh.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

logger = logging.getLogger("buzzcaf_ai.health_checks")

OK, WARN, FAIL, OFF = "ok", "warn", "fail", "off"


def _row(cid: str, label: str, state: str, summary: str, detail: str = "", **extra: Any) -> Dict[str, Any]:
    row = {"id": cid, "label": label, "state": state, "summary": summary, "detail": detail}
    row.update(extra)
    return row


def _ago(ts: Optional[float]) -> str:
    if not ts:
        return "never"
    s = max(0, time.time() - ts)
    if s < 90:
        return f"{int(s)} s ago"
    if s < 5400:
        return f"{int(s // 60)} min ago"
    if s < 172800:
        return f"{s / 3600:.1f} h ago"
    return f"{int(s // 86400)} d ago"


def _get_json(url: str, timeout: float = 3.0) -> Optional[Any]:
    import requests

    resp = requests.get(url, timeout=timeout)
    if resp.status_code != 200:
        return None
    return resp.json()


# ───────────────────────────── the checks ─────────────────────────────

def check_code_reload() -> Dict[str, Any]:
    from app.services import code_reload

    st = code_reload.status()
    if not st.get("started"):
        return _row("code_reload", "Self-restart on changed code", OFF,
                    "Not running in this process (dev run?)", "The desktop Studio starts the watcher; a hand-started backend does not.")
    if st.get("last_error"):
        return _row("code_reload", "Self-restart on changed code", FAIL,
                    "The reload check is failing; a fix on disk will never apply",
                    f"Last error: {st['last_error']} (checked {_ago(st.get('last_check_at'))})")
    if st.get("pending"):
        reason = st.get("busy_reason")
        return _row("code_reload", "Self-restart on changed code", WARN,
                    "New code on disk; restart waits for an idle moment" + (f" ({reason})" if reason else ""),
                    f"Checked {_ago(st.get('last_check_at'))}; restarts after 120 s of idleness.")
    return _row("code_reload", "Self-restart on changed code", OK, f"Watching; checked {_ago(st.get('last_check_at'))}")


def check_idle_offload() -> Dict[str, Any]:
    from integrations import idle_offload

    st = idle_offload.status()
    if not st.get("watcher_alive"):
        return _row("idle_offload", "Idle model offload", FAIL, "The idle watcher thread is not running",
                    "Models loaded by the Studio are never unloaded until something else does it.")
    if st.get("last_error"):
        return _row("idle_offload", "Idle model offload", FAIL, "The idle check cannot decide, so nothing is ever offloaded",
                    f"Last error: {st['last_error']} (checked {_ago(st.get('last_check_at'))})")
    used = ", ".join(st.get("used") or []) or "nothing"
    detail = (f"Checked {_ago(st.get('last_check_at'))}; idle for {st.get('idle_for_s') or 0} s of "
              f"{st.get('idle_seconds_setting')} s; in flight: {st.get('in_flight')}; last offload "
              f"{_ago(st.get('last_offload_at'))}.")
    if st.get("in_flight"):
        return _row("idle_offload", "Idle model offload", OK, f"Work in flight ({st['in_flight']}); holding {used}", detail)
    return _row("idle_offload", "Idle model offload", OK,
                "Everything offloaded" if st.get("offloaded") or not st.get("used") else f"Holding {used} until idle", detail)


def check_buzzedit() -> List[Dict[str, Any]]:
    from integrations.buzzedit_client import BuzzEditClient

    rows = []
    try:
        health = BuzzEditClient().health()
    except Exception as exc:  # noqa: BLE001
        health = None
        logger.debug("buzzedit health: %s", exc)
    if not health:
        rows.append(_row("buzzedit", "BuzzEdit", WARN, "Not answering (it starts on demand for a production)",
                         "A queued production starts the headless BuzzEdit; if one is running and this stays red, see Error Logs."))
        rows.append(_row("comfyui", "ComfyUI (via BuzzEdit)", OFF, "Unknown while BuzzEdit is down"))
        return rows
    parts = [f"v{health.get('version', '?')}", f"pid {health.get('pid', '?')}", f"port {health.get('port', '?')}"]
    if health.get("reload_pending"):
        parts.append("new code waiting for idle")
    missing = [k for k in ("whisper_available", "ffmpeg_available") if health.get(k) is False]
    state = FAIL if missing else OK
    rows.append(_row("buzzedit", "BuzzEdit", state,
                     ("Missing: " + ", ".join(m.replace("_available", "") for m in missing)) if missing else "Answering",
                     ", ".join(parts)))
    cstate = str(health.get("comfyui_state") or ("running" if health.get("comfyui_connected") else "down"))
    detail = str(health.get("comfyui_detail") or "")
    if health.get("comfyui_connected"):
        rows.append(_row("comfyui", "ComfyUI (via BuzzEdit)", OK, f"Connected ({cstate})", detail))
    elif cstate in ("starting", "repairing"):
        rows.append(_row("comfyui", "ComfyUI (via BuzzEdit)", WARN, f"{cstate.capitalize()}", detail))
    else:
        rows.append(_row("comfyui", "ComfyUI (via BuzzEdit)", WARN if cstate in ("idle", "stopped", "off") else FAIL,
                         f"Not connected ({cstate})", detail or "Pictures and clips cannot be generated until it is back; BuzzEdit self-repairs the venv."))
    return rows


def check_lm_studio() -> Dict[str, Any]:
    from integrations.llm import (get_loaded_lm_studio_models, load_config, lm_studio_context_length,
                                  lm_studio_loaded_context)

    config = load_config()
    url = (config.get("lm_studio_url") or "http://localhost:1234/v1").replace("/v1", "")
    try:
        loaded = get_loaded_lm_studio_models(url)
    except Exception as exc:  # noqa: BLE001
        return _row("lm_studio", "LM Studio", FAIL, "Not answering", f"{url}: {exc}")
    wanted = lm_studio_context_length()
    if not loaded:
        return _row("lm_studio", "LM Studio", OK, "Answering, no model loaded (loaded on the next call)", f"{url}; loads at {wanted} tokens")
    small = []
    for m in loaded:
        try:
            have = lm_studio_loaded_context(m, url)
        except Exception:  # noqa: BLE001
            have = None
        if have and have < wanted:
            small.append(f"{m} at {have}")
    if small:
        return _row("lm_studio", "LM Studio", WARN, "A model is loaded with a smaller context than the Studio needs",
                    f"{', '.join(small)} (wanted {wanted}). A long step overflows and comes back truncated; the Studio reloads it at the setting on the next call.")
    return _row("lm_studio", "LM Studio", OK, f"Loaded: {', '.join(loaded)}", f"{url}; context {wanted}")


def check_ollama() -> Dict[str, Any]:
    from integrations.llm import ollama_resident_models

    try:
        models = ollama_resident_models()
    except Exception as exc:  # noqa: BLE001
        return _row("ollama", "Ollama", OFF, "Not answering", str(exc)[:200])
    if not models:
        return _row("ollama", "Ollama", OK, "Answering, nothing resident")
    names = ", ".join(str(m.get("name") or m.get("model") or "?") for m in models)
    return _row("ollama", "Ollama", OK, f"Resident: {names}", "Two models on the card at once starve ComfyUI; the Studio ejects before loading.")


def check_claude_proxy() -> Dict[str, Any]:
    from integrations.llm import CLAUDE_DEFAULT_URL, load_config

    url = str(load_config().get("claude_url") or CLAUDE_DEFAULT_URL).rstrip("/")
    try:
        import requests
        resp = requests.get(f"{url}/models", timeout=3)
        ok = resp.status_code < 500
    except Exception as exc:  # noqa: BLE001
        return _row("claude_proxy", "Claude proxy (fallback)", WARN, "Not answering; local model only", f"{url}: {str(exc)[:120]}")
    return _row("claude_proxy", "Claude proxy (fallback)", OK if ok else WARN,
                "Answering" if ok else f"HTTP {resp.status_code}", url)


def check_gemini() -> Dict[str, Any]:
    from integrations.llm import gemini_settings, is_local_gemini, load_config, probe_gemini

    cfg = load_config()
    try:
        from datetime import datetime
        from integrations import gemini_limit
        lim = gemini_limit.active()
        if lim:
            hhmm = datetime.fromisoformat(str(lim.get("until"))).astimezone().strftime("%H:%M")
            return _row("gemini", "Gemini harness", WARN,
                        f"Rate-limited until {hhmm}" + (" (estimated)" if lim.get("estimated") else ""),
                        str(lim.get("message") or "")[:160])
    except Exception:  # noqa: BLE001
        pass
    probe = probe_gemini(cfg, timeout=3)
    online = bool(probe.get("online"))
    if is_local_gemini(cfg):
        try:
            import requests as _rq
            if _rq.get(f"{gemini_settings(cfg)['url']}/health", timeout=3).status_code == 200:
                online = True
        except Exception:  # noqa: BLE001
            pass
    try:
        from app.services import studio_director
        director_p = str(studio_director.settings().get("provider") or "")
    except Exception:  # noqa: BLE001
        director_p = ""
    selected = str(cfg.get("selected_provider") or "").lower()
    if not online:
        if selected != "gemini" and director_p != "gemini":
            return _row("gemini", "Gemini harness", OFF, "Not in use and not answering", str(probe.get("message", ""))[:160])
        return _row("gemini", "Gemini harness", WARN, "Not answering", str(probe.get("message", ""))[:160])
    if not is_local_gemini(cfg):
        return _row("gemini", "Gemini harness", OK, "Cloud API configured", str(probe.get("url", "")))
    url = gemini_settings(cfg)["url"]
    try:
        import requests
        resp = requests.post(f"{url}/api/gemini", json={"model": "flash", "input": "ping",
                             "thinking_level": "low", "output_format": "text"}, timeout=(3, 8))
    except Exception as exc:  # noqa: BLE001
        return _row("gemini", "Gemini harness", WARN, "Ping failed", f"{url}: {str(exc)[:140]}")
    if resp.status_code != 200:
        return _row("gemini", "Gemini harness", WARN, f"Gemini harness returns {resp.status_code}", resp.text[:160])
    return _row("gemini", "Gemini harness", OK, "Answering", url)


def check_gpu() -> Dict[str, Any]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return _row("gpu", "GPU", OFF, "nvidia-smi not found")
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                             creationflags=_NO_WINDOW).stdout.strip()
        name, used, total, util, temp = [p.strip() for p in out.splitlines()[0].split(",")]
        used_i, total_i = int(float(used)), int(float(total))
    except Exception as exc:  # noqa: BLE001
        return _row("gpu", "GPU", WARN, "Could not read nvidia-smi", str(exc)[:160])
    pct = round(100 * used_i / max(1, total_i))
    state = OK
    from integrations import idle_offload
    try:
        idle = not idle_offload.status().get("in_flight") and not idle_offload._other_work_running()
    except Exception:  # noqa: BLE001
        idle = False
    if idle and pct >= 70:
        state = WARN
    return _row("gpu", "GPU", state,
                f"{name}: {used_i} / {total_i} MiB ({pct}%), {util}% busy, {temp} C"
                + (" while nothing is running" if state == WARN else ""),
                "Memory held with no job running means a model was not offloaded (LM Studio, Ollama or ComfyUI).",
                used_mib=used_i, total_mib=total_i, util=int(float(util)))


def check_queue() -> Dict[str, Any]:
    from app.services import produce_queue

    st = produce_queue.snapshot()
    counts: Dict[str, int] = {}
    for item in st.get("items", []):
        counts[item.get("status", "?")] = counts.get(item.get("status", "?"), 0) + 1
    summary = ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) or "empty"
    failed = [i for i in st.get("items", []) if i.get("status") == "failed"]
    state = OK
    if failed:
        state = WARN
    if st.get("paused") and counts.get("queued"):
        state = WARN
        summary = "Paused with work waiting: " + summary
    elif st.get("paused"):
        summary = "Paused: " + summary
    detail = ""
    if failed:
        last = failed[-1]
        detail = f"Last failed: {last.get('title') or last.get('project_id')}: {str(last.get('error') or '')[:200]}"
    return _row("queue", "Production queue", state, summary, detail, counts=counts, paused=bool(st.get("paused")))


def check_master_pause() -> Dict[str, Any]:
    """The master pause/resume (docs/STUDIO_DIRECTOR_PLAN.md Part 1): a row
    only worth noticing while it is actually on."""
    from app.services import master_control

    st = master_control.state()
    if not st.get("paused"):
        return _row("master_pause", "Master pause", OK, "Not paused")
    held = ", ".join(st.get("held") or []) or "nothing yet"
    summary = f"Master paused since {st.get('since') or '?'}"
    if st.get("reason"):
        summary += f" ({st['reason']})"
    return _row("master_pause", "Master pause", WARN, summary,
               f"Mode: {st.get('mode')}; held at: {held}.", mode=st.get("mode"), held=st.get("held"))


def check_nightly() -> List[Dict[str, Any]]:
    from core.paths import KNOWLEDGE_DIR
    from integrations import nightly_task

    rows = []
    for scope, label in (("shorts", "Nightly Shorts task"), ("longform", "Nightly long-form task")):
        try:
            st = nightly_task.status(scope)
        except Exception as exc:  # noqa: BLE001
            rows.append(_row(f"task_{scope}", label, WARN, "Could not query the scheduler", str(exc)[:160]))
            continue
        if not st.get("registered"):
            # No Windows wake task; the desk may still run it inside the Studio.
            in_app = None
            try:
                if scope == "shorts":
                    from app.services import shorts_desk
                    in_app = shorts_desk.daily_settings()
                else:
                    from app.services import longform_nightly
                    in_app = longform_nightly.settings()
            except Exception:  # noqa: BLE001
                in_app = None
            if in_app and in_app.get("enabled"):
                rows.append(_row(f"task_{scope}", label, OK,
                                 f"Runs inside the Studio at {in_app.get('time') or '?'}; last {in_app.get('last_run') or 'never'}",
                                 "No Windows wake task is registered, so the PC must be awake with the Studio open at that time. "
                                 "The Scheduler Desk can register the wake task."))
            else:
                rows.append(_row(f"task_{scope}", label, OFF, "Off", "Switched off on the Scheduler Desk."))
            continue
        result = str(st.get("last_result") or "")
        bad = result not in ("", "0", "0x0", "267009", "0x41301")   # 267009 = still running
        state = FAIL if bad else (WARN if not st.get("wake_timers") else OK)
        summary = f"Next {st.get('next_run_time') or '?'}; last {st.get('last_run_time') or 'never'}"
        detail = (f"Last result {result or '0'}" + ("" if not bad else " (non-zero: the run failed; see knowledge/nightly)")
                  + ("" if st.get("wake_timers") else "; wake timers are OFF, so the PC will not wake for it"))
        rows.append(_row(f"task_{scope}", label, state, summary, detail))
    # The last run's record: what it did and what failed.
    path = Path(KNOWLEDGE_DIR) / "nightly" / "last_run.json"
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows.append(_row("nightly_last", "Last nightly run", OFF, "No record yet"))
        return rows
    started = str(rec.get("started_at") or "")
    try:
        age_h = (datetime.now() - datetime.fromisoformat(started)).total_seconds() / 3600
    except ValueError:
        age_h = 1e9
    errors = [t for t in rec.get("tasks", []) if t.get("error")]
    built = sum(len(t.get("built") or []) for t in rec.get("tasks", []))
    state = FAIL if errors else (WARN if age_h > 48 else OK)
    summary = f"{started[:16].replace('T', ' ')}: {built} built" + (f", {len(errors)} task(s) failed" if errors else "")
    if age_h > 48:
        summary += f" ({age_h / 24:.0f} days ago)"
    detail = "; ".join(f"{t['task']}: {str(t['error'])[:140]}" for t in errors)
    rows.append(_row("nightly_last", "Last nightly run", state, summary, detail))
    return rows


def check_searxng() -> Dict[str, Any]:
    try:
        from integrations import searxng_service
        # start=False: a health check must never start a service.
        url = searxng_service.base_url(start=False)
        port = getattr(searxng_service, "PREFERRED_PORT", 8888)
        url = url or f"http://127.0.0.1:{port}"
        import requests
        resp = requests.get(f"{url}/healthz", timeout=2)
        ok = resp.status_code < 500
    except Exception as exc:  # noqa: BLE001
        return _row("searxng", "SearXNG (web search)", OFF, "Not running (started on demand by a search)", str(exc)[:120])
    return _row("searxng", "SearXNG (web search)", OK if ok else WARN, "Answering" if ok else "Answering with errors", url)


def check_disks() -> List[Dict[str, Any]]:
    from core.paths import BACKEND_DIR

    rows = []
    seen = set()
    for label, path in (("Studio drive", str(BACKEND_DIR)), ("System drive", os.environ.get("SystemDrive", "C:") + "\\"),
                        ("Models drive", "E:\\")):
        root = os.path.splitdrive(path)[0] + "\\"
        if root in seen or not os.path.exists(root):
            continue
        seen.add(root)
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        free_gb = usage.free / 2**30
        state = FAIL if free_gb < 10 else WARN if free_gb < 40 else OK
        rows.append(_row(f"disk_{root[0].lower()}", f"{label} ({root[:2]})", state,
                         f"{free_gb:.0f} GB free of {usage.total / 2**30:.0f} GB",
                         "A render needs tens of GB of scratch; below 10 GB productions fail." if state != OK else ""))
    return rows


def check_youtube() -> Dict[str, Any]:
    try:
        from integrations import youtube_publish
        st = youtube_publish.status()
    except Exception as exc:  # noqa: BLE001
        return _row("youtube", "YouTube publishing", OFF, "Not set up", str(exc)[:120])
    chans = st.get("channels") or []
    signed = [c for c in chans if c.get("signed_in")]
    if not st.get("has_client"):
        return _row("youtube", "YouTube publishing", OFF, "No Google OAuth client", "Bulk Editor -> YouTube channels.")
    if not signed:
        return _row("youtube", "YouTube publishing", WARN, "No channel signed in", "Uploads will fail until a channel is connected.")
    return _row("youtube", "YouTube publishing", OK,
                "Signed in: " + ", ".join(f"{c.get('title') or c.get('id')} ({c.get('brand') or '?'})" for c in signed))


def check_instagram() -> Dict[str, Any]:
    """REELS_DESK_PLAN.md R7: per named account (several channel/format
    routes can share one -- e.g. Life3Baje/mood_reel -> khayal3bajefeels),
    whether it is connected and how close its long-lived token is to expiring."""
    try:
        from integrations import instagram_publish
        accounts = instagram_publish.status().get("accounts") or {}
    except Exception as exc:  # noqa: BLE001
        return _row("instagram", "Instagram publishing", OFF, "Not set up", str(exc)[:120])
    connected = {name: s for name, s in accounts.items() if s.get("connected")}
    if not connected:
        return _row("instagram", "Instagram publishing", OFF, "No account connected",
                     "Settings -> Instagram.")
    expired = [name for name, s in connected.items() if s.get("token_expired")]
    expiring = [name for name, s in connected.items()
                if not s.get("token_expired") and s.get("token_days_left") is not None and s["token_days_left"] < 10]
    if expired:
        return _row("instagram", "Instagram publishing", FAIL,
                     f"Token expired: {', '.join(expired)}", "Paste a fresh long-lived token under Settings -> Instagram.")
    if expiring:
        detail = ", ".join(f"{name} ({connected[name]['token_days_left']:.0f}d)" for name in expiring)
        return _row("instagram", "Instagram publishing", WARN, f"Token expires soon: {detail}")
    return _row("instagram", "Instagram publishing", OK,
                "Connected: " + ", ".join(f"{name} (@{s.get('username') or '?'})" for name, s in connected.items()))


_ERR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})[,.]\d+ (ERROR|CRITICAL) (.*)$")


def check_recent_errors(hours: float = 1.0) -> Dict[str, Any]:
    from core.paths import LOGS_DIR

    path = Path(LOGS_DIR) / "studio.log"
    if not path.exists():
        path = Path(LOGS_DIR) / "app.log"
    if not path.exists():
        return _row("errors", "Errors in the last hour", OFF, "No log file")
    cutoff = time.time() - hours * 3600
    count, last = 0, ""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - 2_000_000))
            tail = f.read().decode("utf-8", errors="ignore")
    except OSError as exc:
        return _row("errors", "Errors in the last hour", WARN, "Could not read the log", str(exc)[:120])
    for line in tail.splitlines():
        m = _ERR_RE.match(line)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            count += 1
            last = m.group(3)[:220]
    if count == 0:
        return _row("errors", "Errors in the last hour", OK, "None")
    return _row("errors", "Errors in the last hour", WARN, f"{count} error line(s)", f"Last: {last}", count=count)


def check_ui_bundle() -> Dict[str, Any]:
    """Is the built UI older than the sources? (It used to pop a modal that
    blocked the whole launch; now it is a row here and an automatic rebuild.)"""
    try:
        import desktop_app
        state = desktop_app._dist_state()
    except Exception as exc:  # noqa: BLE001
        return _row("ui_bundle", "UI bundle", OFF, "Could not check", str(exc)[:120])
    if state == "fresh":
        return _row("ui_bundle", "UI bundle", OK, "Built from the current sources")
    if state == "missing":
        return _row("ui_bundle", "UI bundle", FAIL, "Not built", "Run `npm run build` in frontend/.")
    return _row("ui_bundle", "UI bundle", WARN, "Sources newer than the build; the window shows the previous build",
                "The next self-restart rebuilds it (BUZZCAF_AUTOBUILD), or run `npm run build` in frontend/.")


def check_watchers() -> Dict[str, Any]:
    """Threads the Studio relies on: the queue worker, the idle watcher, the
    reload watcher, the BuzzEdit keep-alive. Dead threads are the quiet failure."""
    import threading

    names = {t.name for t in threading.enumerate()}
    wanted = {"idle-offload": "idle offload", "studio-code-reload": "self-restart",
              "buzzedit-keepalive": "BuzzEdit keep-alive"}
    # The queue worker is started by `kick()` only while something is
    # runnable, so it is expected only when the queue holds queued work.
    try:
        from app.services import produce_queue
        snap = produce_queue.snapshot()
        if not snap.get("paused") and any(i.get("status") in ("queued", "running") for i in snap.get("items", [])):
            wanted["produce-queue"] = "production queue"
    except Exception:  # noqa: BLE001
        pass
    present = [v for k, v in wanted.items() if any(n.startswith(k) for n in names)]
    missing = [v for k, v in wanted.items() if not any(n.startswith(k) for n in names)]
    if not present:
        return _row("threads", "Background threads", OFF, "No named watcher threads (dev run?)", f"{len(names)} threads")
    return _row("threads", "Background threads", OK if not missing else WARN,
                ("Running: " + ", ".join(present)) + (("; missing: " + ", ".join(missing)) if missing else ""),
                f"{len(names)} threads in the process")


#: At most one automatic repair per sibling app per hour (in-memory: a
#: restart resets it, which is fine -- it just allows one extra early retry).
_APP_ENV_REPAIR_COOLDOWN_S = 3600.0
_last_app_env_repair: Dict[str, float] = {}


def _maybe_auto_repair_app_env(app: str) -> bool:
    """Starts `app_envs.repair(app)` off-thread, at most once an hour per
    app -- the foolproof rule: a missing environment gets fixed automatically
    instead of just being reported red. Off-thread so a GET request for the
    Health page never blocks on the repair itself, or on the
    `master_control.wait_if_paused` check `repair()` makes before it starts."""
    import threading

    from app.services import app_envs

    last = _last_app_env_repair.get(app, 0.0)
    if time.time() - last < _APP_ENV_REPAIR_COOLDOWN_S:
        return False
    _last_app_env_repair[app] = time.time()
    threading.Thread(target=app_envs.repair, args=(app,), kwargs={"wait": False}, daemon=True).start()
    return True


def check_app_envs() -> List[Dict[str, Any]]:
    """One row per sibling app (2026-10-24: BuzzEdit, BuzzAnimate, BuzzViolin,
    SmartCleaner, MastGaane, buzzBooks, VrDeep). Each carries a `health_paths`
    list in its own `installer/app.json` -- the files that must exist for it
    to run. A row with anything missing starts its own repair automatically
    (at most once an hour per app) instead of just sitting red."""
    from app.services import app_envs

    rows = []
    for app in app_envs.discover_apps():
        cid = f"app_env_{app}"
        label = f"{app} environment"
        try:
            st = app_envs.status(app)
        except Exception as exc:  # noqa: BLE001 - a broken check is itself a finding
            rows.append(_row(cid, label, WARN, "Could not check", str(exc)[:200]))
            continue
        if st["ok"]:
            rows.append(_row(cid, label, OK, "Ready", app=app))
            continue
        summary = "Missing: " + ", ".join(st["missing"])
        detail = app_envs.log_tail(app) or "No installer/logs/setup.log yet."
        if st.get("repairing"):
            summary += " (repair running)"
        elif _maybe_auto_repair_app_env(app):
            summary += " (repair started)"
        rows.append(_row(cid, label, WARN, summary, detail, app=app, missing=st["missing"]))
    return rows


CHECKS: List[Callable[[], Any]] = [
    check_master_pause, check_code_reload, check_idle_offload, check_watchers, check_ui_bundle, check_buzzedit,
    check_app_envs, check_lm_studio, check_ollama, check_claude_proxy, check_gemini, check_gpu, check_queue, check_nightly,
    check_searxng, check_disks, check_youtube, check_instagram, check_recent_errors,
]


def run_all() -> Dict[str, Any]:
    t0 = time.time()
    rows: List[Dict[str, Any]] = []
    for fn in CHECKS:
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 - a broken check is itself a finding
            logger.warning("health check %s failed: %s", fn.__name__, exc)
            out = _row(fn.__name__.replace("check_", ""), fn.__name__.replace("check_", "").replace("_", " ").capitalize(),
                       WARN, "The check itself failed", f"{type(exc).__name__}: {exc}"[:200])
        rows.extend(out if isinstance(out, list) else [out])
    now = datetime.now().isoformat(timespec="seconds")
    for r in rows:
        r.setdefault("checked_at", now)
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in (OK, WARN, FAIL, OFF)}
    overall = FAIL if counts[FAIL] else WARN if counts[WARN] else OK
    return {"at": now, "seconds": round(time.time() - t0, 2), "overall": overall, "counts": counts, "checks": rows}
