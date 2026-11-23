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
    # The idle offload stops the headless BuzzEdit the Studio started.
    from app.services import process_cleanup
    monkeypatch.setattr(process_cleanup, "stop_headless_buzzedit", lambda: [])


@pytest.fixture(autouse=True)
def _no_real_sound_designer(request, monkeypatch):
    """The render's sound-cue pass asks the real SoundDesigner model; a test
    of the production flow reached the owner's LM Studio and loaded Gemma
    beside a live render (2026-10-27). Its own tests keep the real pass."""
    from integrations import llm
    if not request.node.module.__name__.rsplit(".", 1)[-1] in (
            "test_gpu_handover", "test_local_privacy_and_research", "test_llm", "test_model_routing", "test_router",
            "test_studio_shutdown"):
        # Every other test: a local model call that slips through its own
        # stubs gets a refused connection at once, never the owner's model.
        monkeypatch.setattr(llm.LLMService, "_local_url", lambda self, provider: "http://127.0.0.1:9/v1")
    if request.node.module.__name__.endswith("test_sound_cues"):
        return
    from integrations import sound_cues
    monkeypatch.setattr(sound_cues, "plan_sound_cues",
                        lambda agent, windows, kept, beats, genre, secondary, progress_cb=None:
                        {"beats": list(beats), "added": 0, "spans": 0, "ok": 0, "failed": []})


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
    # The slot check runs `lms ps` and reloads a model held with several slots.
    monkeypatch.setattr(llm, "lm_studio_loaded_parallel", lambda model: None)


@pytest.fixture(autouse=True)
def _no_render_owns_the_gpu_in_tests(monkeypatch):
    """A real BuzzEdit job on the owner's PC moves local providers to the back
    of every provider order (`_defer_gpu_providers`); tests that want that
    patch it themselves."""
    from integrations import llm

    monkeypatch.setattr(llm, "_gpu_owned_by_render", lambda: False)
    # The real card and RAM of the owner's PC must not hold a test's call.
    monkeypatch.setattr(llm, "wait_for_local_headroom", lambda provider, model, loaded: None)


@pytest.fixture(autouse=True)
def _master_pause_is_the_tests_own(monkeypatch, tmp_path):
    """The owner's real master pause (config/master_control.json) must not
    hold a test's hold points -- tests that pause do it in their own file."""
    from app.services import master_control

    monkeypatch.setattr(master_control, "STATE_PATH", str(tmp_path / "master_control.json"))
    monkeypatch.setattr(master_control, "_state_cache", None)


@pytest.fixture(autouse=True)
def _video_slot_starts_empty(request, monkeypatch):
    """One video at a time is process-wide state: no test inherits a holder.
    Outside its own tests the queue never holds the slot: other tests fake
    `produce_queue.snapshot` for their own purposes (or would read the owner's
    real queue)."""
    from app.services import video_slot

    if not request.node.module.__name__.endswith("test_video_slot"):
        monkeypatch.setattr(video_slot, "_queue_blocker", lambda exclude: None)
    # Never the owner's real BuzzEdit render.
    monkeypatch.setattr(video_slot, "_buzzedit_blocker", lambda: None)
    video_slot.reset_for_tests()
    yield
    video_slot.reset_for_tests()


@pytest.fixture(autouse=True)
def _usage_records_go_to_tmp(monkeypatch, tmp_path):
    """Every model call is recorded (integrations/llm_usage.py); never into the
    owner's real knowledge/usage."""
    from integrations import llm_usage

    monkeypatch.setattr(llm_usage, "USAGE_DIR", str(tmp_path / "usage"))
    monkeypatch.setattr(llm_usage, "CALLS_PATH", str(tmp_path / "usage" / "llm_calls.jsonl"))


@pytest.fixture(autouse=True)
def _never_rebuild_a_style_guide_with_a_real_model(monkeypatch):
    """A writing step rebuilds a style guide that is older than the creator's
    samples (writing_style.ensure_current), which calls StyleAnalyst on a real
    model; no test may. The step then writes from his samples directly."""
    from app.services import writing_style

    def no_model(channel, llm=None):
        raise RuntimeError("no model in tests")

    monkeypatch.setattr(writing_style, "build_profile", no_model)


@pytest.fixture(autouse=True)
def _no_ollama_on_this_machine(monkeypatch):
    """Tests never read or eject what Ollama holds (integrations.llm's one-model rule)."""
    import integrations.llm as llm
    monkeypatch.setattr(llm, "ollama_resident_models", lambda *a, **k: [])


@pytest.fixture(autouse=True)
def _never_call_the_real_instagram_api(monkeypatch):
    """publish_reel's resumable upload hits graph.facebook.com and
    rupload.facebook.com; no test may reach either for real."""
    from integrations import instagram_publish as ig

    def _refuse(*a, **k):
        raise AssertionError("instagram_publish must not make a real HTTP call in tests")

    monkeypatch.setattr(ig, "_request", _refuse)


@pytest.fixture(autouse=True)
def _no_live_reel_slot_wait(monkeypatch):
    """`auto_story.wait_for_reel_slot` asks the live BuzzEdit whether a reel is rendering;
    a test must never wait on (or even reach) the real one."""
    from integrations.buzzedit_client import BuzzEditClient
    monkeypatch.setattr(BuzzEditClient, "vibe_reel_busy", lambda self: False)
