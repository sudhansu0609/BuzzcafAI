"""Point every data directory at a throwaway copy before the app is imported.

`core.paths` reads PROJECTS_PATH / KNOWLEDGE_PATH / LOGS_PATH from the
environment at import time and honours an override only if the directory
already exists. Without this file the suite ran against the real
`backend/knowledge` and `backend/projects`, and `test_memory_system`'s
`memory_system.clear(scope="session")` deleted every real session memory file
on every run. Seed data (channel guides, seed topics, existing projects) is
copied in so tests see the same shape as production, minus agent memory.
"""
import os
import shutil
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
_SANDBOX = Path(tempfile.mkdtemp(prefix="buzzcaf-tests-"))


def _copy(src: Path, dst: Path, ignore=None) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)
    else:
        dst.mkdir(parents=True, exist_ok=True)


_copy(
    _BACKEND / "knowledge",
    _SANDBOX / "knowledge",
    ignore=shutil.ignore_patterns("*_memory.json", "produce_queue.json", "__pycache__", "*.pyc"),
)
_copy(_BACKEND / "projects", _SANDBOX / "projects", ignore=shutil.ignore_patterns("voice_profiles"))
(_SANDBOX / "logs").mkdir(parents=True, exist_ok=True)

os.environ["KNOWLEDGE_PATH"] = str(_SANDBOX / "knowledge")
os.environ["PROJECTS_PATH"] = str(_SANDBOX / "projects")
os.environ["LOGS_PATH"] = str(_SANDBOX / "logs")

# Guard against a stale override in .env: core.config loads the repo .env with
# override=True, which would silently redirect the suite back to real data.
os.environ.setdefault("BUZZCAF_TEST_SANDBOX", str(_SANDBOX))
os.environ["SENTINEL_PIPE"] = r"\\.\pipe\BuzzcafTestSentinelAbsent"
os.environ.setdefault("APP_ENV", "test")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    shutil.rmtree(_SANDBOX, ignore_errors=True)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _never_touch_real_gpu_tenants(monkeypatch):
    """The render hand-over really runs `lms unload --all` and `buzzcode
    engine stop`; no test may do that to the owner's live servers."""
    from app.api import produce_api

    for step in ("_unload_lm_studio", "_stop_llamacpp", "_unload_ollama"):
        monkeypatch.setattr(produce_api, step, lambda project_id, cfg: None)
    monkeypatch.setattr(produce_api.BuzzEditClient, "clear_vram", lambda self: {"comfyui_freed": False})


@pytest.fixture(autouse=True)
def _never_start_searxng_or_metasearch(monkeypatch):
    """search_web starts the local SearXNG on demand and falls back to live
    `ddgs` metasearch; no test may spawn that process or hit those engines."""
    from integrations import searxng_service
    from app.services import web_research

    monkeypatch.setattr(searxng_service, "base_url", lambda start=True: None)
    monkeypatch.setattr(web_research, "search_ddgs", lambda query, max_results=5, news=False: [])


@pytest.fixture(autouse=True)
def _never_touch_the_windows_scheduler(monkeypatch):
    """The nightly run registers a real wake-the-PC task; no test may."""
    from integrations import nightly_task

    monkeypatch.setattr(nightly_task, "register", lambda hhmm, scope="shorts": {"registered": True, "wake_timers": True})
    monkeypatch.setattr(nightly_task, "unregister", lambda scope="shorts": {"registered": False, "wake_timers": True})
    monkeypatch.setattr(nightly_task, "run_now", lambda scope="shorts": True)
    monkeypatch.setattr(nightly_task, "enable_wake_timers", lambda: True)
    monkeypatch.setattr(nightly_task, "status", lambda scope="shorts": {"registered": False, "wake_timers": True})


@pytest.fixture(autouse=True)
def _never_load_a_real_lm_studio_model(monkeypatch):
    """Before an LM Studio call the service loads the model itself when it is
    not in memory, and reloads it with a larger context after an overflow;
    both run the real `lms` CLI. No test may load a model onto the owner's GPU."""
    from integrations import llm

    monkeypatch.setattr(llm, "ensure_local_model_loaded",
                        lambda provider="lm_studio", model_name=None: {"loaded": False, "message": "tests"})
    monkeypatch.setattr(llm, "reload_lm_studio_model", lambda model, context: False)


@pytest.fixture(autouse=True)
def _never_rebuild_a_style_guide_with_a_real_model(monkeypatch):
    """A writing step rebuilds a style guide that is older than the creator's
    samples (writing_style.ensure_current), which calls StyleAnalyst on a real
    model; no test may. The step then writes from his samples directly."""
    from app.services import writing_style

    def no_model(channel, llm=None):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(writing_style, "build_profile", no_model)
