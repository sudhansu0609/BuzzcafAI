"""
Check that the Buzzcaf Studio can actually run before opening its window.

    python backend/preflight.py           full report, exit 1 on a fatal problem
    python backend/preflight.py --quiet   only print problems

desktop_app.py calls run_checks() itself and shows the failures in a dialog,
because under pythonw there is no console for a report to land in.

FAIL rows stop the Studio from working at all; WARN rows describe a degraded
capability (no LLM provider reachable, a missing persona) and never block.
"""

import argparse
import importlib.util
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_SYMBOL = {OK: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}

_REQUIRED = [
    ("fastapi", "the API server"),
    ("uvicorn", "the API server"),
    ("pydantic", "request schemas"),
    ("requests", "talking to the model providers"),
    ("dotenv", "reading .env"),
]

EXPECTED_PERSONAS = 105


class Report:
    def __init__(self, quiet: bool = False) -> None:
        self.rows = []
        self.quiet = quiet

    def add(self, status: str, title: str, detail: str = "", action: str = "") -> None:
        self.rows.append((status, title, detail, action))
        if self.quiet and status == OK:
            return
        line = f"{_SYMBOL[status]} {title}"
        if detail:
            line += f" - {detail}"
        print(line)
        if action and status != OK:
            print(f"       -> {action}")

    @property
    def failed(self) -> bool:
        return any(row[0] == FAIL for row in self.rows)

    def problem_lines(self):
        lines = []
        for status, title, detail, action in self.rows:
            if status == OK:
                continue
            line = f"{_SYMBOL[status]} {title}"
            if detail:
                line += f" - {detail}"
            if action:
                line += f"  -> {action}"
            lines.append(line)
        return lines

    def summary(self) -> str:
        counts = {OK: 0, WARN: 0, FAIL: 0}
        for status, *_ in self.rows:
            counts[status] += 1
        return f"{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)"


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


def check_python_deps(report: Report) -> None:
    missing = [(m, why) for m, why in _REQUIRED if not _installed(m)]
    if missing:
        report.add(FAIL, "Python dependencies", "missing " + ", ".join(m for m, _ in missing),
                   "pip install -r requirements.txt")
    else:
        report.add(OK, "Python dependencies", "core packages present")


def check_desktop_shell(report: Report) -> None:
    if _installed("webview"):
        report.add(OK, "Desktop shell", "pywebview present")
    else:
        report.add(FAIL, "Desktop shell", "pywebview missing - the window cannot open",
                   "pip install pywebview")


def check_ui_bundle(report: Report, dev: bool) -> None:
    index = os.path.join(BACKEND_DIR, "app", "static", "index.html")
    if dev:
        report.add(OK, "UI bundle", "developer mode uses the Vite dev server")
        return
    if os.path.exists(index):
        report.add(OK, "UI bundle", "app/static/index.html present")
    else:
        report.add(FAIL, "UI bundle", "app/static/index.html missing",
                   "cd frontend && npm install && npm run build")


def check_paths(report: Report) -> None:
    try:
        from core import paths

        problems = [
            name for name, value in (
                ("prompts", paths.PROMPTS_DIR), ("knowledge", paths.KNOWLEDGE_DIR),
                ("projects", paths.PROJECTS_DIR),
            ) if not os.path.isdir(value)
        ]
        if problems:
            report.add(WARN, "Data directories", "missing: " + ", ".join(problems),
                       "They are created on first use; check PROJECTS_PATH/KNOWLEDGE_PATH in .env if unexpected")
        else:
            report.add(OK, "Data directories", "prompts, knowledge and projects found")
    except Exception as exc:
        report.add(FAIL, "Data directories", f"core.paths failed to import: {exc}")


def check_personas(report: Report) -> None:
    try:
        from core.paths import AGENTS_DIR

        count = len([f for f in os.listdir(AGENTS_DIR) if f.endswith(".md")])
    except Exception as exc:
        report.add(WARN, "Agent personas", f"could not count: {exc}")
        return
    if count == 0:
        report.add(FAIL, "Agent personas", "no persona files found in prompts/agents")
    elif count != EXPECTED_PERSONAS:
        report.add(WARN, "Agent personas", f"{count} found, expected {EXPECTED_PERSONAS}")
    else:
        report.add(OK, "Agent personas", f"{count} personas registered")


def check_port(report: Report) -> None:
    """Report on the preferred port. Never fatal: if an unrelated process holds
    it, the Studio steps to the next free port at launch (desktop_app._resolve_port)."""
    import json
    import socket
    import urllib.request

    port = int(os.getenv("BUZZCAF_PORT", "8099"))
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        with urllib.request.urlopen(req, timeout=1.5) as res:
            body = json.loads(res.read().decode("utf-8") or "{}")
        if body.get("app") == "buzzcaf":
            report.add(OK, "Port", f"{port} already served by a running Studio (window will attach)")
        else:
            report.add(WARN, "Port", f"{port} is taken by something that is not the Studio",
                       "the Studio will start on the next free port")
        return
    except Exception:
        pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            report.add(OK, "Port", f"{port} is free")
        except OSError:
            report.add(WARN, "Port", f"{port} is in use but does not answer /health",
                       "the Studio will start on the next free port")


def check_llm(report: Report) -> None:
    """At least one provider should be reachable; the Studio still boots without."""
    try:
        import requests
        from integrations.llm import load_config

        cfg = load_config()
    except Exception as exc:
        report.add(WARN, "LLM providers", f"could not read config: {exc}")
        return

    reachable = []
    lm_url = (cfg.get("lm_studio_url") or "http://localhost:1234/v1").rstrip("/")
    try:
        if requests.get(f"{lm_url}/models", timeout=1.5).status_code == 200:
            reachable.append("LM Studio")
    except Exception:
        pass
    try:
        if requests.get("http://127.0.0.1:11434/v1/models", timeout=1.5).status_code == 200:
            reachable.append("Ollama")
    except Exception:
        pass
    if cfg.get("gemini_api_key"):
        reachable.append("Gemini (key set)")
    if cfg.get("openai_api_key"):
        reachable.append("OpenAI (key set)")
    if reachable:
        report.add(OK, "LLM providers", ", ".join(reachable))
    else:
        report.add(WARN, "LLM providers", "none reachable; replies will be labelled SIMULATED",
                   "Start LM Studio or Ollama, or add a key in Settings")


def run_fast_checks(quiet: bool = True, dev: bool = False) -> Report:
    """The checks that can FAIL and answer in milliseconds; they gate the window."""
    report = Report(quiet=quiet)
    check_python_deps(report)
    check_desktop_shell(report)
    check_ui_bundle(report, dev)
    check_paths(report)
    check_personas(report)
    check_port(report)
    return report


def run_slow_checks(quiet: bool = True) -> Report:
    """Network probes that only ever WARN; the desktop shell runs them after the window opens."""
    report = Report(quiet=quiet)
    check_llm(report)
    return report


def run_checks(quiet: bool = True, dev: bool = False) -> Report:
    report = run_fast_checks(quiet=quiet, dev=dev)
    for row in run_slow_checks(quiet=True).rows:
        report.add(*row)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the Buzzcaf Studio can run.")
    parser.add_argument("--quiet", action="store_true", help="only print problems")
    parser.add_argument("--dev", action="store_true", help="developer mode (Vite dev server)")
    args = parser.parse_args()
    if not args.quiet:
        print("=== Buzzcaf Studio preflight ===")
    report = run_checks(quiet=args.quiet, dev=args.dev)
    print(f"--- {report.summary()} ---")
    if report.failed:
        print("The Studio will not start correctly until the failures above are fixed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
