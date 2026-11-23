"""Start the two local model proxies with the Studio and keep them up.

- Claude proxy: `../claudeAPI` (node, `start-server.bat start`, hidden launcher,
  /health on its port, default 8787).
- Gemini harness: `../geminiApi/gemini_harness_route.py` (FastAPI over the
  Antigravity CLI, /openapi.json on its port, default 8001).

Both are already running when the creator started them by hand or at login;
only a proxy that does not answer is started. A watcher re-checks every few
minutes and starts one that died. Nothing here stops them: they outlive the
Studio on purpose (other apps use the Claude proxy too).
"""
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger("buzzcaf_ai.llm_proxies")

ROOT = Path(__file__).resolve().parents[3]              # .../Buzzcaf_Media
CLAUDE_DIR = ROOT / "claudeAPI"
GEMINI_DIR = ROOT / "geminiApi"
CHECK_EVERY_S = 180
START_WAIT_S = 45

_lock = threading.Lock()
_started = False


def _port(url: Optional[str], default: int) -> int:
    try:
        return urlparse(url or "").port or default
    except ValueError:
        return default


def _up(url: str) -> bool:
    try:
        return requests.get(url, timeout=3).status_code < 500
    except requests.RequestException:
        return False


def _wait(url: str) -> bool:
    deadline = time.time() + START_WAIT_S
    while time.time() < deadline:
        if _up(url):
            return True
        time.sleep(1)
    return False


def _free_port(port: int) -> None:
    """A proxy that hung while still listening (2026-10-26: Claude's node held
    8787, every connect stuck in SYN_SENT) keeps a fresh start from binding.
    Kill whatever listens on the port before starting a new one."""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                             timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            logger.warning("Proxy on port %s does not answer; killing pid %s before restarting it", port, parts[4])
            subprocess.run(["taskkill", "/F", "/T", "/PID", parts[4]], capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            time.sleep(2)


def _config() -> Dict:
    try:
        from integrations.llm import load_config
        return load_config()
    except Exception:  # noqa: BLE001
        return {}


def ensure_claude() -> str:
    cfg = _config()
    port = _port(cfg.get('claude_url'), 8787)
    url = f"http://127.0.0.1:{port}/health"
    if _up(url) or (time.sleep(10) or _up(url)):  # one slow answer is not a hang
        return "running"
    vbs = CLAUDE_DIR / "scripts" / "start-hidden.vbs"
    if not vbs.exists():
        return "not installed"
    _free_port(port)
    subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(CLAUDE_DIR))
    return "started" if _wait(url) else "did not answer"


def ensure_gemini() -> str:
    cfg = _config()
    port = _port(cfg.get("gemini_url"), 8001)
    url = f"http://127.0.0.1:{port}/health"
    if _up(url) or (time.sleep(10) or _up(url)):
        return "running"
    script = GEMINI_DIR / "gemini_harness_route.py"
    if not script.exists():
        return "not installed"
    vbs = GEMINI_DIR / "scripts" / "start-hidden.vbs"
    if vbs.exists():
        subprocess.Popen(["wscript.exe", str(vbs)], cwd=str(GEMINI_DIR))
        return "started" if _wait(url) else "did not answer"
    # The harness runs on the Antigravity CLI's Google login; an API key in the
    # environment would make `agy` use it instead.
    env = {k: v for k, v in os.environ.items() if k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = str(pythonw if pythonw.exists() else python)
    log = open(GEMINI_DIR / "harness.log", "a", encoding="utf-8")
    subprocess.Popen([exe, str(script)], cwd=str(GEMINI_DIR), env=env, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return "started" if _wait(url) else "did not answer"


def ensure_all() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for name, fn in (("claude", ensure_claude), ("gemini", ensure_gemini)):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001 - a missing proxy must never block the Studio
            out[name] = f"failed: {exc}"
    return out


def _watch() -> None:
    first = True
    while True:
        result = ensure_all()
        if first or any(v not in ("running",) for v in result.values()):
            logger.info("Model proxies: %s", result)
        first = False
        time.sleep(CHECK_EVERY_S)


def start() -> None:
    """Start the proxies and the watcher, once, in the background."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_watch, name="llm-proxies", daemon=True).start()
