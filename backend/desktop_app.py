"""
Buzzcaf Studio desktop shell: FastAPI in-process plus a native WebView2 window.

Launched by "Buzzcaf Studio.vbs" (hidden, via pythonw - no console), by
start_buzzcafai.bat (console, --dev), or by Dexter's `buzzcaf_start_studio`
tool. The Studio used to be two console windows (Vite + uvicorn --reload) that
the owner had to keep open behind a browser tab; now the only thing that
appears is the app window (roadmap v5, 2.2).

    python backend/desktop_app.py          serve backend/app/static in the window
    python backend/desktop_app.py --dev    show our Vite dev server (5173 or the next free port) instead

Under pythonw there is no console, so every failure ends in a message box and
everything printed goes to backend/logs/studio.log.
"""

import argparse
import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from typing import Any, Dict, Optional, Tuple

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
os.chdir(BACKEND_DIR)  # app.main resolves prompts/knowledge relative to core.paths, but tests/tools assume cwd=backend

# The checkout's .env is read here (without overriding a real environment) so a
# BUZZCAF_PORT set there reaches the launcher; app.main loads it again later.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT_DIR, ".env"))
except Exception:
    pass

from integrations import buzzcaf_ports  # byte-identical copy of dexter/backend/buzzcaf_ports.py

HOST = "127.0.0.1"
#: This app's name in the shared port ledger and in every /health body.
APP_ID = "buzzcaf"
# 8099, not 8000: every other local app defaults to 8000 (CaliberAI did, and
# the Studio window ended up beside a stranger). If even 8099 is busy the
# launcher steps forward and records where it landed in RUNTIME_FILE.
PORT = int(os.getenv("BUZZCAF_PORT", "8099"))
PORT_SCAN_RANGE = buzzcaf_ports.SPAN  # how far past the preferred port to step, from the one shared constant
HEALTH_URL = f"http://{HOST}:{PORT}/health"
RUNTIME_FILE = os.path.join(BACKEND_DIR, "config", "studio.runtime.json")
# --dev only. 5173 is Vite's universal default, so another project's dev server
# (CaliberAI's was) is often already there; the launcher picks a free port and
# pins Vite to it (--strictPort) rather than let Vite drift and the window open
# a stranger's page.
DEV_PORT = int(os.getenv("BUZZCAF_DEV_PORT", "5173"))
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


def _read_runtime() -> Dict[str, Any]:
    """The record a running Studio left behind (see _write_runtime), or {}."""
    import json

    try:
        with open(RUNTIME_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_runtime(port: int) -> None:
    """Tell the neighbours where the Studio actually landed.

    Dexter reads this file (through BUZZCAF_DIR) before probing, so a Studio
    that had to step off its usual port is still found instead of reported
    offline - and nothing else on 8099 gets mistaken for us, because readers
    still check that /health says app:"buzzcaf".
    """
    import json

    try:
        os.makedirs(os.path.dirname(RUNTIME_FILE), exist_ok=True)
        tmp = RUNTIME_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({
                "port": port, "pid": os.getpid(), "started_at": time.time(),
                "health_url": f"http://{HOST}:{port}/health",
            }, handle)
        os.replace(tmp, RUNTIME_FILE)
    except Exception as exc:
        log.warning("Could not write %s: %s", RUNTIME_FILE, exc)


def _clear_runtime() -> None:
    """Remove the runtime record and our ledger entry, if this process wrote them."""
    if _read_runtime().get("pid") == os.getpid():
        try:
            os.remove(RUNTIME_FILE)
        except OSError:
            pass
    try:
        buzzcaf_ports.withdraw(APP_ID)
    except Exception as exc:  # a ledger problem must never stop a shutdown
        log.warning("Could not withdraw from the port ledger: %s", exc)


def _publish(port: int, extra: Optional[Dict[str, Any]] = None) -> None:
    """Announce where we landed: our own runtime file *and* the shared ledger.

    The runtime file stays because Dexter and the Studio's own tooling read it
    through BUZZCAF_DIR; the ledger is what every *other* app in the ecosystem
    reads (GUARDIAN_PLAN section 11 rule 3). Both are written only after
    /health has answered as us.
    """
    _write_runtime(port)
    try:
        buzzcaf_ports.publish(APP_ID, port, f"http://{HOST}:{port}/health", extra=extra)
    except Exception as exc:
        log.warning("Could not publish to the port ledger: %s", exc)


def _resolve_port(preferred: int) -> Tuple[int, bool]:
    """Decide which port the backend will use.

    Returns (port, ours_already_answering):
      - If a Studio is already up anywhere discovery can reach it (an explicit
        BUZZCAF_URL, the shared ledger, or a scan of preferred…preferred+span
        that checks /health says app:"buzzcaf"), attach to it - a window just
        opens on it rather than a second backend starting.
      - Else take the preferred port, or step forward past whatever unrelated
        process holds it. Never evict: `pick_port` only ever binds what is free.
    """
    from urllib.parse import urlparse

    # ttl=0: a launcher must not act on a three-second-old answer.
    running = buzzcaf_ports.discover(APP_ID, preferred, span=PORT_SCAN_RANGE, host=HOST, ttl=0)
    if running:
        port = urlparse(running).port or preferred
        if port != preferred:
            log.info("A running Studio answers on %d (discovered); attaching.", port)
        return port, True
    # The runtime file can point outside the scan window (an OS-assigned port
    # from a launch when everything was busy), so it is still worth a look.
    recorded = _read_runtime().get("port")
    if isinstance(recorded, int) and _studio_answering(f"http://{HOST}:{recorded}/health"):
        log.info("A running Studio answers on %d (from %s); attaching.", recorded, RUNTIME_FILE)
        return recorded, True

    port = buzzcaf_ports.pick_port(preferred, PORT_SCAN_RANGE, HOST)
    if port != preferred:
        log.warning("Port %d is in use by another process; using %d instead.", preferred, port)
    return port, False


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


def _resolve_dev_port(preferred: int) -> int:
    """A free port for our Vite: the preferred one, else the next free one."""
    port = buzzcaf_ports.pick_port(preferred, PORT_SCAN_RANGE, HOST)
    if port != preferred:
        log.warning("Dev port %d is in use by another process; Vite will use %d.", preferred, port)
    return port


def _start_vite_dev(port: int, dev_port: int) -> Optional[subprocess.Popen]:
    """`npm run dev`, hidden, for --dev. Returns the process so it dies with us.

    The real backend port travels in the child's environment: vite.config.ts
    points its proxy at BUZZCAF_PORT, and app.main re-reads .env with override
    on, so os.environ alone cannot be trusted by the time Vite starts. The dev
    port is pinned with --strictPort so Vite fails loudly instead of moving.
    """
    npm = shutil.which("npm")
    if not npm:
        _message_box("npm not found", "Developer mode needs Node.js (npm) on PATH to run the Vite dev server.")
        return None
    try:
        return subprocess.Popen(
            [npm, "run", "dev", "--", "--port", str(dev_port), "--strictPort"], cwd=FRONTEND_DIR,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_hidden_flags(),
            env={**os.environ, "BUZZCAF_PORT": str(port), "BUZZCAF_DEV_PORT": str(dev_port)},
        )
    except Exception as exc:
        _message_box("Could not start the Vite dev server", str(exc))
        return None


def _stop_process_tree(proc: subprocess.Popen, port: Optional[int] = None) -> None:
    """End a child and everything it spawned, and free the port it was given.

    `npm run dev` is cmd.exe (the npm shim) over node over another shell over
    node (Vite); terminate() kills only the shim, and even taskkill /T misses
    a level once a shim has exited, leaving Vite holding its port for the
    next launch to trip over. So: the whole tree via psutil when available,
    then whatever still listens on our port - we chose a free one, so any
    listener there is ours - then taskkill as the last resort.
    """
    try:
        import psutil

        procs = []
        try:
            root = psutil.Process(proc.pid)
            procs = root.children(recursive=True) + [root]
        except psutil.Error:
            pass
        if port is not None:
            try:
                for conn in psutil.net_connections(kind="tcp"):
                    if conn.status == psutil.CONN_LISTEN and conn.laddr.port == port and conn.pid:
                        procs.append(psutil.Process(conn.pid))
            except psutil.Error:
                pass
        for item in procs:
            try:
                item.kill()
            except psutil.Error:
                pass
        if procs:
            psutil.wait_procs(procs, timeout=3)
            return
    except ImportError:
        pass
    except Exception as exc:
        log.warning("Process tree cleanup fell back to taskkill: %s", exc)
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_hidden_flags())
        else:
            proc.terminate()
    except Exception:
        pass


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


def start_backend(port: int = PORT) -> None:
    import uvicorn
    from app.main import app, set_bound_port

    # /health reports the port we actually took, not the one we wished for.
    set_bound_port(port)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


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

    # Pick the real port before anything binds to it: reuse ours if it is already
    # up, otherwise take the preferred port, otherwise step past whatever
    # unrelated process is holding it. Export it so the Vite dev proxy (and any
    # child) targets the port the backend actually landed on.
    port, already_running = _resolve_port(PORT)
    health_url = f"http://{HOST}:{port}/health"
    os.environ["BUZZCAF_PORT"] = str(port)
    if port != PORT:
        log.warning("Studio is on port %d, not the preferred %d.", port, PORT)

    import webview  # checked by preflight; imported late so its absence has a dialog

    vite_proc: Optional[subprocess.Popen] = None
    vite_port: Optional[int] = None
    if already_running:
        # Dexter (or an earlier launch) already has the backend up; just open a window to it.
        log.info("Studio backend already answering on %s; opening a window only.", health_url)
    else:
        threading.Thread(target=lambda: start_backend(port), name="studio-uvicorn", daemon=True).start()
        if not wait_for(health_url):
            _message_box(
                "Buzzcaf Studio backend did not start",
                f"Nothing answered at {health_url} within 25 seconds.\n\nSee {LOG_PATH} for the error.",
            )
            sys.exit(1)
        _publish(port)
        atexit.register(_clear_runtime)

    if dev:
        dev_port = vite_port = _resolve_dev_port(DEV_PORT)
        dev_url = f"http://{HOST}:{dev_port}"
        vite_proc = _start_vite_dev(port, dev_port)
        # Through Vite's /health proxy, so this passes only for a Vite that is
        # ours and forwards to our backend - never for another project's dev
        # server that happened to be on the port.
        if vite_proc is None or not wait_for(f"{dev_url}/health", timeout=60):
            _message_box("Vite dev server did not start",
                         f"{dev_url} did not answer as the Studio within 60 seconds.\n\nSee {LOG_PATH}.")
            if vite_proc is not None:
                _stop_process_tree(vite_proc, dev_port)
            sys.exit(1)
        if not already_running:
            _publish(port, extra={"vite": dev_port})
        target_url = f"{dev_url}/"
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
        target_url = f"http://{HOST}:{port}/"

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
            _stop_process_tree(vite_proc, vite_port)

    window.events.closing += on_closing
    log.info("Window opening after %.1fs (%s).", time.perf_counter() - started, target_url)
    print(f"READY port={port}", flush=True)  # rule 6: whoever launched us opens what we report
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
