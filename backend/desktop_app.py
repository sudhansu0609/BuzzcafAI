"""
Buzzcaf Studio desktop shell: FastAPI in-process plus a native WebView2 window.

Launched by "Buzzcaf Studio.vbs" (hidden, via pythonw - no console), by
start_buzzcafai.bat (console, --dev), or by Dexter's `buzzcaf_start_studio`
tool. The Studio used to be two console windows (Vite + uvicorn --reload) that
the owner had to keep open behind a browser tab; now the only thing that
appears is the app window (roadmap v5, 2.2).

    python backend/desktop_app.py          serve backend/app/static in the window
    python backend/desktop_app.py --dev    show the Vite dev server (5173) instead

Under pythonw there is no console, so every failure ends in a message box and
everything printed goes to backend/logs/studio.log.
"""

import argparse
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from typing import Any, Dict, Optional

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)  # app.main resolves prompts/knowledge relative to core.paths, but tests/tools assume cwd=backend

HOST = "127.0.0.1"
PORT = int(os.getenv("BUZZCAF_PORT", "8000"))
HEALTH_URL = f"http://{HOST}:{PORT}/health"
DEV_URL = os.getenv("BUZZCAF_DEV_URL", "http://localhost:5173")
STATIC_DIR = os.path.join(BACKEND_DIR, "app", "static")
STATIC_INDEX = os.path.join(STATIC_DIR, "index.html")
WINDOW_FILE = os.path.join(BACKEND_DIR, "config", "window.json")

DEFAULT_WINDOW = {"width": 1280, "height": 800}
MIN_WIDTH, MIN_HEIGHT = 900, 600

MB_ERROR, MB_WARNING = 0x10, 0x30


# ───────────────────────── logging (no console under pythonw) ─────────────────────────


def _setup_logging() -> str:
    try:
        from core.paths import LOGS_DIR

        log_dir = LOGS_DIR
    except Exception:
        log_dir = os.path.join(BACKEND_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "studio.log")

    from logging.handlers import RotatingFileHandler

    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # pythonw starts with stdout/stderr set to None; anything that writes to
    # them (uvicorn's access log, a traceback) would be lost or raise.
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    return log_path


LOG_PATH = _setup_logging()
log = logging.getLogger("buzzcaf.desktop")


def _message_box(title: str, text: str, icon: int = MB_ERROR) -> None:
    log.error("%s: %s", title, text) if icon == MB_ERROR else log.warning("%s: %s", title, text)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, text, title, icon)
        except Exception:
            pass


# ───────────────────────── health / preflight ─────────────────────────


def _studio_answering(url: str = HEALTH_URL, timeout: float = 1.5) -> bool:
    """True only if *this app* answers - anything else on the port is not ours."""
    try:
        import json

        req = urllib.request.Request(url, headers={"User-Agent": "BuzzcafStudio/desktop"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            if res.status != 200:
                return False
            body = json.loads(res.read().decode("utf-8") or "{}")
            return body.get("app") == "buzzcaf"
    except Exception:
        return False


def _preflight_or_exit(dev: bool) -> None:
    try:
        import preflight
    except Exception as exc:
        log.warning("Preflight unavailable, continuing: %s", exc)
        return
    report = preflight.run_fast_checks(quiet=True, dev=dev)
    for line in report.problem_lines():
        log.warning("[Preflight] %s", line)
    if report.failed:
        _message_box(
            "Buzzcaf Studio cannot start",
            "Preflight found problems that stop the Studio from working:\n\n"
            + "\n".join(report.problem_lines())
            + "\n\nFix them and launch again (start_buzzcafai.bat shows the full report).",
        )
        sys.exit(1)

    def _slow_checks() -> None:
        try:
            for line in preflight.run_slow_checks(quiet=True).problem_lines():
                log.warning("[Preflight] %s", line)
        except Exception as exc:
            log.warning("[Preflight] slow checks skipped: %s", exc)

    threading.Thread(target=_slow_checks, name="studio-preflight-slow", daemon=True).start()


# ───────────────────────── UI bundle ─────────────────────────


def _newest_source_mtime() -> float:
    newest = 0.0
    src = os.path.join(FRONTEND_DIR, "src")
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "test", "__tests__")]
        for name in files:
            if name.endswith((".ts", ".tsx", ".css", ".html")):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(base, name)))
                except OSError:
                    pass
    for extra in ("index.html", "vite.config.ts"):
        try:
            newest = max(newest, os.path.getmtime(os.path.join(FRONTEND_DIR, extra)))
        except OSError:
            pass
    return newest


def _dist_state() -> str:
    if not os.path.exists(STATIC_INDEX):
        return "missing"
    try:
        built = os.path.getmtime(STATIC_INDEX)
    except OSError:
        return "missing"
    return "stale" if _newest_source_mtime() > built + 1 else "fresh"


def _hidden_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _rebuild_bundle() -> bool:
    npm = shutil.which("npm")
    if not npm:
        return False
    try:
        done = subprocess.run(
            [npm, "run", "build"], cwd=FRONTEND_DIR, capture_output=True, text=True,
            timeout=300, creationflags=_hidden_flags(),
        )
        if done.returncode != 0:
            log.error("npm run build failed:\n%s", (done.stdout + done.stderr)[-2000:])
        return done.returncode == 0
    except Exception as exc:
        log.error("Rebuild failed: %s", exc)
        return False


def _start_vite_dev() -> Optional[subprocess.Popen]:
    """`npm run dev`, hidden, for --dev. Returns the process so it dies with us."""
    npm = shutil.which("npm")
    if not npm:
        _message_box("npm not found", "Developer mode needs Node.js (npm) on PATH to run the Vite dev server.")
        return None
    try:
        return subprocess.Popen(
            [npm, "run", "dev"], cwd=FRONTEND_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_hidden_flags(),
        )
    except Exception as exc:
        _message_box("Could not start the Vite dev server", str(exc))
        return None


# ───────────────────────── window geometry ─────────────────────────


def _load_window() -> Dict[str, Any]:
    import json

    geometry = dict(DEFAULT_WINDOW)
    try:
        with open(WINDOW_FILE, "r", encoding="utf-8") as handle:
            saved = json.load(handle) or {}
    except Exception:
        saved = {}
    for key in ("width", "height", "x", "y"):
        value = saved.get(key)
        if isinstance(value, (int, float)):
            geometry[key] = int(value)
    geometry["width"] = max(MIN_WIDTH, geometry["width"])
    geometry["height"] = max(MIN_HEIGHT, geometry["height"])
    return geometry


def _save_window(window: Any) -> None:
    import json

    try:
        os.makedirs(os.path.dirname(WINDOW_FILE), exist_ok=True)
        tmp = WINDOW_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({
                "width": int(window.width), "height": int(window.height),
                "x": int(window.x), "y": int(window.y),
            }, handle)
        os.replace(tmp, WINDOW_FILE)
    except Exception as exc:
        log.warning("Could not remember window size: %s", exc)


# ───────────────────────── backend ─────────────────────────


def start_backend() -> None:
    import uvicorn
    from app.main import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


def wait_for(url: str, timeout: float = 25.0, require_buzzcaf: bool = True) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if require_buzzcaf:
            if _studio_answering(url):
                return True
        else:
            try:
                with urllib.request.urlopen(url, timeout=2) as res:
                    if res.status == 200:
                        return True
            except Exception:
                pass
        time.sleep(0.3)
    return False


# ───────────────────────── entry ─────────────────────────


def launch_desktop(dev: bool = False) -> None:
    started = time.perf_counter()
    _preflight_or_exit(dev)

    import webview  # checked by preflight; imported late so its absence has a dialog

    vite_proc: Optional[subprocess.Popen] = None
    already_running = _studio_answering()
    if already_running:
        # Dexter (or an earlier launch) already has the backend up; just open a window to it.
        log.info("Studio backend already answering on %s; opening a window only.", HEALTH_URL)
    else:
        threading.Thread(target=start_backend, name="studio-uvicorn", daemon=True).start()
        if not wait_for(HEALTH_URL):
            _message_box(
                "Buzzcaf Studio backend did not start",
                f"Nothing answered at {HEALTH_URL} within 25 seconds.\n\nSee {LOG_PATH} for the error.",
            )
            sys.exit(1)

    if dev:
        vite_proc = _start_vite_dev()
        if not wait_for(DEV_URL, timeout=60, require_buzzcaf=False):
            _message_box("Vite dev server did not start", f"{DEV_URL} did not answer within 60 seconds.")
            sys.exit(1)
        target_url = DEV_URL
    else:
        state = _dist_state()
        if state == "missing":
            _message_box(
                "Buzzcaf Studio UI is not built",
                "backend/app/static/index.html is missing.\n\nRun `npm run build` in frontend/, "
                "or launch start_buzzcafai.bat for developer mode.",
            )
            sys.exit(1)
        if state == "stale":
            if os.getenv("BUZZCAF_AUTOBUILD", "0") == "1" and _rebuild_bundle():
                log.info("UI bundle was stale; rebuilt.")
            else:
                _message_box(
                    "Buzzcaf Studio UI bundle is out of date",
                    "Files under frontend/src are newer than the built bundle. The window will "
                    "show the previous build.\n\nRun `npm run build` in frontend/ (or set "
                    "BUZZCAF_AUTOBUILD=1) to pick up the changes.",
                    MB_WARNING,
                )
        target_url = f"http://{HOST}:{PORT}/"

    geometry = _load_window()
    window = webview.create_window(
        title="Buzzcaf Studio",
        url=target_url,
        width=geometry["width"],
        height=geometry["height"],
        x=geometry.get("x"),
        y=geometry.get("y"),
        min_size=(MIN_WIDTH, MIN_HEIGHT),
        resizable=True,
        background_color="#0d0e12",
    )

    def on_closing() -> None:
        _save_window(window)
        if vite_proc is not None:
            try:
                vite_proc.terminate()
            except Exception:
                pass

    window.events.closing += on_closing
    log.info("Window opening after %.1fs (%s).", time.perf_counter() - started, target_url)
    webview.start(debug=dev)


def main() -> int:
    parser = argparse.ArgumentParser(description="Buzzcaf Studio desktop app")
    parser.add_argument("--dev", action="store_true", help="show the Vite dev server instead of the built bundle")
    args = parser.parse_args()
    try:
        launch_desktop(dev=args.dev)
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        text = traceback.format_exc()
        log.error(text)
        _message_box("Buzzcaf Studio crashed on startup", text[-1500:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
