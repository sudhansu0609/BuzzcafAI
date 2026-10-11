"""Buzzcaf's local SearXNG: keyless metasearch (Google, Bing, DuckDuckGo,
Brave, Wikipedia...) for the Shorts Desk, Research and agents.

It lives next to the Studio (`../searxng` code, `../searxng-config` settings
+ launcher) and is started on demand -- the first search that needs it pays
a few seconds, later ones reuse it. Port per the ecosystem contract
(buzzcaf_ports): wish for SEARXNG_PORT (default 8888), step forward past a
busy one (on this machine a Windows service holds 8080, which is why the old
`searxng_url` never answered), publish the real port in the shared ledger
once /healthz answers, and withdraw + stop it when the Studio exits.

`base_url()` never raises: None means "no SearXNG", and search_web falls
back to its other providers.
"""
import atexit
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("buzzcaf_ai.searxng")

APP = "searxng"
PREFERRED_PORT = int(os.environ.get("SEARXNG_PORT", "8888"))
ROOT = Path(__file__).resolve().parents[3]              # .../Buzzcaf_Media
CODE_DIR = ROOT / "searxng"
CONFIG_DIR = ROOT / "searxng-config"
PYTHON = CODE_DIR / ".venv" / "Scripts" / "python.exe"
LAUNCHER = CONFIG_DIR / "run_searxng.py"
START_TIMEOUT_S = 60

_lock = threading.Lock()
_proc: Optional[subprocess.Popen] = None
_failed_at = 0.0


def installed() -> bool:
    return PYTHON.exists() and LAUNCHER.exists()


def _healthy(url: str) -> bool:
    try:
        return requests.get(f"{url}/healthz", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def _from_ledger() -> Optional[str]:
    try:
        from integrations import buzzcaf_ports
        rec = buzzcaf_ports.entry(APP)
    except Exception:
        return None
    if rec and rec.get("port"):
        url = f"http://127.0.0.1:{int(rec['port'])}"
        if _healthy(url):
            return url
    return None


def _remember(url: str) -> None:
    """Keep the Studio's `searxng_url` setting pointed at the live instance."""
    try:
        from integrations.llm import load_config, save_config
        cfg = load_config()
        if cfg.get("searxng_url") != url:
            cfg["searxng_url"] = url
            save_config(cfg)
    except Exception as exc:
        logger.debug("could not save searxng_url: %s", exc)


def _start() -> Optional[str]:
    global _proc
    from integrations import buzzcaf_ports
    port = buzzcaf_ports.pick_port(PREFERRED_PORT)
    env = {**os.environ, "SEARXNG_PORT": str(port), "SEARXNG_BIND_ADDRESS": "127.0.0.1",
           "PYTHONIOENCODING": "utf-8"}
    log = open(CONFIG_DIR / "searxng.log", "a", encoding="utf-8")
    _proc = subprocess.Popen([str(PYTHON), str(LAUNCHER)], cwd=str(CONFIG_DIR), env=env,
                             stdout=log, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        if _proc.poll() is not None:
            logger.warning("SearXNG exited with code %s while starting (see %s)",
                           _proc.returncode, CONFIG_DIR / "searxng.log")
            _proc = None
            return None
        if _healthy(url):
            buzzcaf_ports.publish(APP, port, f"{url}/healthz", extra={"pid": _proc.pid})
            logger.info("SearXNG up at %s", url)
            return url
        time.sleep(1)
    logger.warning("SearXNG did not answer within %ss", START_TIMEOUT_S)
    stop()
    return None


def base_url(start: bool = True) -> Optional[str]:
    """The live SearXNG URL, starting it when `start` and it is installed."""
    global _failed_at
    url = _from_ledger()
    if url:
        return url
    if not start or not installed():
        return None
    with _lock:
        url = _from_ledger()
        if url:
            return url
        if _proc is not None and _proc.poll() is None:
            return None                      # still starting in another thread
        if time.time() - _failed_at < 300:
            return None                      # failed recently: don't retry every search
        url = _start()
        if url:
            _remember(url)
        else:
            _failed_at = time.time()
        return url


def stop() -> None:
    """Stop the instance this Studio started (never someone else's)."""
    global _proc
    proc, _proc = _proc, None
    if proc is None:
        return
    try:
        from integrations import buzzcaf_ports
        buzzcaf_ports.withdraw(APP)
    except Exception:
        pass
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


atexit.register(stop)
