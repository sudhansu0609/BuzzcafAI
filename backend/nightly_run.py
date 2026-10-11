"""Buzzcaf Studio nightly run -- started by the Windows task that wakes the PC
(integrations/nightly_task.py), or by hand:

    python nightly_run.py                 # the real thing (may hibernate at the end)
    python nightly_run.py --no-hibernate  # run the tasks, never hibernate
    python nightly_run.py --check         # only print the hibernate decision
    python nightly_run.py --only shorts   # just the Shorts Desk batch (its own Windows task)
    python nightly_run.py --only longform # just the long-form batch (its own Windows task)

Steps: wait for the network (it lags a wake from hibernate), make sure LM
Studio's server is up, run the tasks (the Shorts Desk daily batch for every
channel -- it records the day, so the Studio's own in-app schedule does not
run it again -- then one long-form video per Raat3Baje / Beyond3Baje /
Life3Baje, researched and scripted, see app/services/longform_nightly.py),
offload every model (GPU policy), stop the local SearXNG, and
hibernate -- only when nothing else is using the machine:

- no BuzzEdit render, no ComfyUI job, no Studio production-queue item;
- the GPU is idle (average utilisation over ~30 s under the threshold);
- nobody is at the PC (no keyboard/mouse input for the idle minutes set for
  that scheduler: `nightly_idle_minutes` / `longform_idle_minutes`).

The Shorts and Long-form schedulers are separate Windows tasks (each passes
--only) with their own wake time, hibernate switch and idle minutes; with no
--only both batches run. Two runs never overlap: the second waits for the
first's lock, and the first does not hibernate while another run is waiting.

Everything is logged to logs/nightly.log and summarised in
knowledge/nightly/last_run.json (shorts / both) or last_run_longform.json for
the Studio UI.
"""
import argparse
import ctypes
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

LOG_DIR = BACKEND / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_DIR / "nightly.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("nightly")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GPU_BUSY_PERCENT = 15
LOCK = BACKEND / "knowledge" / "nightly" / "running.lock"
WAITING = BACKEND / "knowledge" / "nightly" / "waiting.flag"


def _cfg() -> dict:
    from integrations.llm import load_config
    return load_config()


def wait_for_network(limit_s: int = 180) -> bool:
    import requests
    deadline = time.time() + limit_s
    while time.time() < deadline:
        try:
            requests.get("https://www.google.com/generate_204", timeout=5)
            return True
        except Exception:
            time.sleep(5)
    return False


def ensure_lm_studio() -> bool:
    """The batch's agents run on the local model: start LM Studio's server if
    it is not answering (it JIT-loads the model on the first request)."""
    import requests
    url = str(_cfg().get("lm_studio_url") or "http://localhost:1234").rstrip("/").replace("/v1", "")
    def up() -> bool:
        try:
            return requests.get(f"{url}/v1/models", timeout=3).status_code == 200
        except Exception:
            return False
    if up():
        return True
    from integrations.llm import find_lms_binary
    lms = find_lms_binary()
    if not lms:
        log.warning("LM Studio server is down and the lms CLI was not found")
        return False
    log.info("Starting LM Studio's server")
    subprocess.run([lms, "server", "start"], capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW)
    for _ in range(30):
        if up():
            return True
        time.sleep(2)
    return False


# --- hibernate safety -------------------------------------------------------------

def idle_seconds() -> float:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def gpu_utilisation(samples: int = 6, gap_s: float = 5.0) -> float:
    values = []
    for i in range(samples):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW).stdout
            values.append(float(out.strip().splitlines()[0]))
        except Exception:
            pass
        if i < samples - 1:
            time.sleep(gap_s)
    return sum(values) / len(values) if values else 0.0


def comfyui_busy() -> bool:
    import requests
    try:
        from integrations import buzzcaf_ports
        rec = buzzcaf_ports.entry("comfyui") or {}
    except Exception:
        rec = {}
    for port in [rec.get("port"), 8188]:
        if not port:
            continue
        try:
            q = requests.get(f"http://127.0.0.1:{port}/queue", timeout=3).json()
            return bool(q.get("queue_running") or q.get("queue_pending"))
        except Exception:
            continue
    return False


def _fresh(path: Path, hours: float = 5) -> bool:
    return path.exists() and time.time() - path.stat().st_mtime < hours * 3600


def hibernate_decision(idle_minutes: float | None = None) -> dict:
    """Whether hibernating now would interrupt anything, with the reasons."""
    reasons = []
    cfg = _cfg()
    idle_needed = float(cfg.get("nightly_idle_minutes", 10) if idle_minutes is None else idle_minutes) * 60
    idle = idle_seconds()
    if idle < idle_needed:
        reasons.append(f"someone used the PC {idle / 60:.1f} min ago (needs {idle_needed / 60:.0f} min idle)")
    try:
        from app.api import produce_api
        if produce_api.buzzedit_job_active():
            reasons.append("BuzzEdit has a job running")
    except Exception as exc:
        log.info("BuzzEdit check skipped: %s", exc)
    try:
        from app.services import produce_queue
        if produce_queue.running_item() is not None:
            reasons.append("the Studio production queue is running")
    except Exception as exc:
        log.info("Production-queue check skipped: %s", exc)
    if _fresh(WAITING) or _fresh(LOCK, 4):
        reasons.append("another scheduled run is waiting or has just started")
    if comfyui_busy():
        reasons.append("ComfyUI has queued work")
    gpu = gpu_utilisation()
    if gpu >= GPU_BUSY_PERCENT:
        reasons.append(f"GPU is busy ({gpu:.0f}% average)")
    return {"hibernate": not reasons, "reasons": reasons, "idle_minutes": round(idle / 60, 1),
            "gpu_percent": round(gpu, 1)}


# --- the run ------------------------------------------------------------------------

def refresh_writing_styles() -> list:
    """Rebuild every channel's style profile that has new samples (a production
    keeps the creator's recording as one), before tonight's writing uses it."""
    from app.services import writing_style
    done = []
    for channel in writing_style.CHANNELS:
        view = writing_style.overview(channel)
        if not view["samples"] or not view["stale"]:
            continue
        t0 = time.time()
        try:
            writing_style.build_profile(channel)
            done.append({"channel": channel, "seconds": round(time.time() - t0)})
        except Exception as exc:  # noqa: BLE001 - the old profile stays in use
            log.warning("Writing style for %s not rebuilt: %s", channel, exc)
            done.append({"channel": channel, "error": str(exc)[:200]})
    return done


def run_tasks(scope: str = "all") -> list:
    results = []
    today = datetime.now().date().isoformat()
    try:
        rebuilt = refresh_writing_styles()
        if rebuilt:
            results.append({"task": "writing_style", "rebuilt": rebuilt})
    except Exception as exc:  # noqa: BLE001
        log.warning("Writing style refresh skipped: %s", exc)
    if scope in ("all", "shorts"):
        from app.services import shorts_desk
        if shorts_desk.daily_settings().get("last_run") == today:
            results.append({"task": "shorts_daily", "skipped": "already ran today"})
        else:
            t0 = time.time()
            try:
                record = shorts_desk.run_daily(progress=lambda m: log.info("shorts: %s", m))
                results.append({"task": "shorts_daily", "seconds": round(time.time() - t0),
                                "built": record.get("built", []), "skipped": record.get("skipped", [])})
            except Exception as exc:  # noqa: BLE001
                log.exception("Shorts daily batch failed")
                results.append({"task": "shorts_daily", "error": str(exc)[:300]})

    if scope in ("all", "longform"):
        from app.services import longform_nightly
        lf = longform_nightly.settings()
        if not lf["enabled"]:
            results.append({"task": "longform", "skipped": "long-form nightly is off"})
        elif lf["last_run"] == today:
            results.append({"task": "longform", "skipped": "already ran today"})
        else:
            t0 = time.time()
            try:
                record = longform_nightly.run(progress=lambda m: log.info("longform: %s", m))
                results.append({"task": "longform", "seconds": round(time.time() - t0),
                                "built": record.get("built", []), "skipped": record.get("skipped", [])})
            except Exception as exc:  # noqa: BLE001
                log.exception("Long-form nightly batch failed")
                results.append({"task": "longform", "error": str(exc)[:300]})
    return results


def acquire_lock(limit_h: float = 5) -> bool:
    """Take the run lock, waiting (up to `limit_h`) while another scheduled run
    holds it. The waiting flag keeps that run from hibernating the PC."""
    deadline = time.time() + limit_h * 3600
    waited = False
    while _fresh(LOCK, 4):
        if time.time() > deadline:
            WAITING.unlink(missing_ok=True)
            return False
        if not waited:
            log.info("Another scheduled run is in progress; waiting for it to finish")
            waited = True
        WAITING.write_text(str(os.getpid()))
        time.sleep(30)
    WAITING.unlink(missing_ok=True)
    LOCK.write_text(str(os.getpid()))
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-hibernate", action="store_true")
    ap.add_argument("--check", action="store_true", help="only print the hibernate decision")
    ap.add_argument("--only", choices=["shorts", "longform"], help="run just one scheduler (default: both)")
    args = ap.parse_args()
    scope = args.only or "all"
    # Each scheduler has its own hibernate switch and idle minutes.
    prefix = "longform" if scope == "longform" else "nightly"
    idle_minutes = float(_cfg().get(f"{prefix}_idle_minutes", 10))

    if args.check:
        print(json.dumps(hibernate_decision(idle_minutes), indent=2))
        return 0

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if not acquire_lock():
        log.info("Another scheduled run never finished; giving up")
        return 0
    summary = {"started_at": datetime.now().isoformat(timespec="seconds"), "scope": scope, "tasks": []}
    try:
        log.info("=== Nightly run started (%s) ===", scope)
        summary["network"] = wait_for_network()
        summary["lm_studio"] = ensure_lm_studio()
        summary["tasks"] = run_tasks(scope)
    finally:
        try:
            from integrations import idle_offload
            idle_offload.offload_now("nightly run finished")
        except Exception as exc:
            log.warning("Offload failed: %s", exc)
        try:
            from integrations import searxng_service
            searxng_service.stop()
        except Exception:
            pass
        LOCK.unlink(missing_ok=True)

    want = bool(_cfg().get(f"{prefix}_hibernate", True)) and not args.no_hibernate
    decision = (hibernate_decision(idle_minutes) if want
                else {"hibernate": False, "reasons": ["hibernate after the run is off"]})
    summary.update(finished_at=datetime.now().isoformat(timespec="seconds"), hibernate=decision)
    name = "last_run_longform.json" if scope == "longform" else "last_run.json"
    (BACKEND / "knowledge" / "nightly" / name).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                                          encoding="utf-8")
    log.info("Summary: %s", json.dumps(summary, ensure_ascii=False)[:1500])
    if decision["hibernate"]:
        log.info("Nothing else is using the machine: hibernating")
        subprocess.run(["shutdown", "/h"], creationflags=_NO_WINDOW)
    else:
        log.info("Not hibernating: %s", "; ".join(decision["reasons"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
