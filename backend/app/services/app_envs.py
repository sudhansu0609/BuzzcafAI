"""
Sibling-app environment discovery and self-repair (2026-10-24).

Why: each sibling app next to the Studio (BuzzEdit, BuzzAnimate, BuzzViolin,
SmartCleaner, MastGaane, buzzBooks, VrDeep) keeps its own Python venv / node
modules / build output, and any of those can go missing -- a disk cleaner
pass, an interrupted install, a half-finished update. Every app's own
`installer\\app.json` carries a `health_paths` list: the files that must
exist for the app to run. `status()` reads that list straight off disk;
`repair()` runs the app's own idempotent `installer\\setup_env.ps1` (the
foolproof auto-repair rule: every failure gets an automatic fix and retry,
never a silent degraded result) in a hidden window, single-flight per app via
a lock file holding the runner's PID, and reports the outcome. The Health
page's app-env rows, the nightly preflight and the BuzzEdit-launch repair are
all built on this module.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.paths import PROJECT_ROOT

logger = logging.getLogger("buzzcaf_ai.app_envs")

#: Siblings live next to the Studio itself (...\Buzzcaf_Media\<App>), the same
#: place `produce_api.get_buzzedit_dir()` looks for BuzzEdit.
SIBLINGS_ROOT = Path(PROJECT_ROOT).parent

#: How long `repair(wait=True)` waits for `setup_env.ps1` before giving up
#: (a fully missing BuzzEdit environment takes ~15 min; a no-op run ~30 s).
DEFAULT_REPAIR_TIMEOUT_S = 20 * 60


def discover_apps() -> List[str]:
    """Every sibling folder with an `installer\\app.json` next to the Studio."""
    apps = []
    try:
        for child in sorted(SIBLINGS_ROOT.iterdir()):
            if (child / "installer" / "app.json").is_file():
                apps.append(child.name)
    except OSError:
        return []
    return apps


def _app_dir(app: str) -> Path:
    return SIBLINGS_ROOT / app


def _app_json(app: str) -> Dict[str, Any]:
    try:
        return json.loads((_app_dir(app) / "installer" / "app.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _lock_path(app: str) -> Path:
    return _app_dir(app) / "installer" / "setup.running"


def _log_path(app: str) -> Path:
    return _app_dir(app) / "logs" / "setup.log"


def log_tail(app: str, lines: int = 20) -> str:
    """The last lines of the app's own `logs\\setup.log`, for a Health row's
    detail and a `repair()` result."""
    try:
        text = _log_path(app).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _lock_info(app: str) -> Optional[Dict[str, Any]]:
    """The lock's contents while the PID inside it is still alive; a dead PID
    is stale and is cleared so a crashed repair never wedges every later one."""
    from integrations.buzzcaf_ports import _pid_alive

    path = _lock_path(app)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if _pid_alive(data.get("pid")):
        return data
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def status(app: str) -> Dict[str, Any]:
    """`{app, installed, missing, ok, repairing, self_test}` straight off
    `installer\\app.json`'s `health_paths`, `installer\\installed.json` and the
    app's last self-test result (`self_test.result`), which counts as missing
    when it failed: files that exist but do not work (2026-10-26, Whisper and
    cuBLAS) are a broken environment too."""
    info = _app_json(app)
    health_paths = info.get("health_paths") or []
    root = _app_dir(app)
    missing = [p for p in health_paths if not (root / p).exists()]
    installed = (root / "installer" / "installed.json").is_file()
    last = last_self_test(app)
    if last is not None and not last.get("ok"):
        failed = [c["name"] for c in last.get("checks", []) if c.get("required") and not c.get("ok")]
        missing.append("self-test: " + (", ".join(failed) or "failed"))
    return {"app": app, "installed": installed, "missing": missing, "ok": not missing,
            "repairing": _lock_info(app) is not None, "self_test": last}


def last_self_test(app: str) -> Optional[Dict[str, Any]]:
    """The app's last self-test result, or None when it has none."""
    spec = _app_json(app).get("self_test") or {}
    if not spec.get("result"):
        return None
    try:
        return json.loads((_app_dir(app) / spec["result"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_self_test(app: str) -> Optional[Dict[str, Any]]:
    """Run the app's own self-test now (`installer\\app.json` -> `self_test`)
    and return its result; None when the app declares none."""
    spec = _app_json(app).get("self_test") or {}
    if not spec.get("script"):
        return None
    import shutil
    root = _app_dir(app)
    # `python` is a path inside the app (its venv) or a command on PATH ("python", "node").
    runner = spec.get("python") or "python"
    exe = root / runner if (root / runner).is_file() else (shutil.which(runner) and Path(shutil.which(runner)))
    script = root / spec["script"]
    if not exe:
        return {"ok": False, "checks": [{"name": "runtime", "ok": False, "required": True,
                                         "detail": f"{runner} is missing"}]}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    try:
        subprocess.run([str(exe), str(script)], cwd=str(root), capture_output=True, text=True,
                       timeout=float(spec.get("timeout_s") or 240), creationflags=creationflags)
    except subprocess.TimeoutExpired:
        return {"ok": False, "checks": [{"name": "self-test", "ok": False, "required": True, "detail": "timed out"}]}
    return last_self_test(app)


def ensure_working(app: str, status_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Self-test the app; repair it and test again when it fails. The
    foolproof rule: the next job never starts on an environment that only
    looks complete."""
    result = run_self_test(app)
    if result is None or result.get("ok"):
        return {"app": app, "ok": True, "repaired": False, "self_test": result}
    logger.warning("app_envs.ensure_working(%s): self-test failed; repairing", app)
    rep = repair(app, wait=True, status_callback=status_callback)
    result = run_self_test(app)
    return {"app": app, "ok": bool(result and result.get("ok")), "repaired": True, "repair": rep,
            "self_test": result}


def _await_lock_clear(app: str, timeout: float) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline and _lock_info(app) is not None:
        time.sleep(2.0)
    done = _lock_info(app) is None
    return {"status": "done" if done else "timeout", "log_tail": log_tail(app)}


def repair(app: str, wait: bool = False, timeout: float = DEFAULT_REPAIR_TIMEOUT_S,
           status_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Run the app's own `installer\\setup_env.ps1` in a hidden window.

    Single-flight per app: a `installer\\setup.running` lock holds the
    runner's PID, and a second call while that PID is alive is reported as
    `already_running` instead of starting another install in parallel; a
    dead PID in the lock is stale and is cleared.

    Blocks on `master_control.wait_if_paused` before starting anything -- the
    master pause holds every automated job, this one included.

    Returns `{app, status: started|already_running|done|timeout|error,
    exit_code, log_tail}`.
    """
    from app.services import master_control

    master_control.wait_if_paused(f"app_envs.repair:{app}", status_callback)

    root = _app_dir(app)
    script = root / "installer" / "setup_env.ps1"
    if not script.is_file():
        return {"app": app, "status": "error", "exit_code": None, "log_tail": "",
                "error": f"No installer/setup_env.ps1 for {app}"}

    existing = _lock_info(app)
    if existing is not None:
        logger.info("app_envs.repair(%s): a repair is already running (pid %s)", app, existing.get("pid"))
        out = {"app": app, "status": "already_running", "exit_code": None, "log_tail": log_tail(app)}
        if wait:
            out.update(_await_lock_clear(app, timeout))
        return out

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    try:
        proc = subprocess.Popen(cmd, cwd=str(root), creationflags=creationflags,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:  # noqa: BLE001 - PowerShell missing, permissions, etc.
        logger.warning("app_envs.repair(%s): could not start setup_env.ps1 (%s)", app, exc)
        return {"app": app, "status": "error", "exit_code": None, "log_tail": "", "error": str(exc)[:300]}

    lock = _lock_path(app)
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps({"pid": proc.pid, "started": time.time()}), encoding="utf-8")
    except OSError as exc:
        logger.warning("app_envs.repair(%s): could not write the lock file (%s)", app, exc)

    logger.info("app_envs.repair(%s): started setup_env.ps1 (pid %d)", app, proc.pid)
    if status_callback:
        try:
            status_callback(f"Repairing {app}'s environment...")
        except Exception:  # noqa: BLE001 - a progress callback must never break a repair
            logger.debug("app_envs.repair(%s): status callback failed", app, exc_info=True)

    if not wait:
        return {"app": app, "status": "started", "exit_code": None, "log_tail": ""}

    deadline = time.time() + timeout
    exit_code: Optional[int] = None
    while time.time() < deadline:
        exit_code = proc.poll()
        if exit_code is not None:
            break
        time.sleep(2.0)
    lock.unlink(missing_ok=True)

    if exit_code is None:
        logger.warning("app_envs.repair(%s): setup_env.ps1 did not finish within %.0fs", app, timeout)
        return {"app": app, "status": "timeout", "exit_code": None, "log_tail": log_tail(app)}
    logger.info("app_envs.repair(%s): setup_env.ps1 exited %s", app, exit_code)
    return {"app": app, "status": "done", "exit_code": exit_code, "log_tail": log_tail(app)}
