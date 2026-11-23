"""`integrations/idle_offload.py`: unload what the Studio used once nothing
has run for `idle_offload_seconds`. Servers and BuzzEdit are faked."""
import time

import pytest

from app.api import produce_api
from app.services import produce_queue
from integrations import idle_offload
from integrations.llm import ensure_local_model_loaded as _REAL_ENSURE_LOADED


@pytest.fixture
def offloads(monkeypatch):
    seen = []
    cfg = {"idle_offload_seconds": 300}
    monkeypatch.setattr("integrations.llm.load_config", lambda: cfg)
    monkeypatch.setattr(produce_api, "_unload_lm_studio", lambda p, c: seen.append("lm_studio"))
    monkeypatch.setattr(produce_api, "_unload_ollama", lambda p, c: seen.append("ollama"))
    monkeypatch.setattr(produce_api, "_stop_llamacpp", lambda p, c: seen.append("llamacpp"))
    monkeypatch.setattr(produce_api, "buzzedit_job_active", lambda: False)
    monkeypatch.setattr(produce_api, "render_in_progress", lambda: False)
    monkeypatch.setattr(produce_queue, "running_item", lambda: None)
    monkeypatch.setattr(idle_offload, "_nightly_running", lambda: False)
    idle_offload.reset_for_tests()
    yield seen, cfg
    idle_offload.reset_for_tests()


def _later(seconds=301):
    return time.monotonic() + seconds


def test_unloads_only_what_was_used_after_the_idle_window(offloads):
    seen, _ = offloads
    with idle_offload.busy():
        idle_offload.mark_used("lm_studio")
    assert not idle_offload.check_once(_later(10))
    assert idle_offload.check_once(_later())
    assert seen == ["lm_studio"] and idle_offload.offloaded()
    assert not idle_offload.check_once(_later(1000))  # nothing left to unload


def test_never_unloads_while_work_is_in_flight(offloads):
    seen, _ = offloads
    idle_offload.mark_used("ollama")
    with idle_offload.busy():
        assert not idle_offload.check_once(_later(10_000))
    assert seen == []


def test_a_render_outside_the_studio_counts_as_busy(offloads, monkeypatch):
    seen, _ = offloads
    idle_offload.mark_used("lm_studio")
    monkeypatch.setattr(produce_api, "buzzedit_job_active", lambda: True)
    assert not idle_offload.check_once(_later())
    assert seen == []


def test_llamacpp_is_stopped_only_when_opted_in(offloads):
    seen, cfg = offloads
    idle_offload.mark_used("llamacpp")
    idle_offload.check_once(_later())
    assert seen == []
    cfg["idle_offload_llamacpp"] = True
    idle_offload.mark_used("llamacpp")
    idle_offload.check_once(_later())
    assert seen == ["llamacpp"]


# --- _buzzedit_hold: a reel or a narration holds the headless BuzzEdit too
# (STUDIO_DIRECTOR_PLAN.md enhancement 2/5, Fable review row 5) ----------------

class _FakeBuzzEditClient:
    def __init__(self, *, vibe_busy=False, narration_busy=False, jobs=None, transcribing=None):
        self._vibe_busy = vibe_busy
        self._narration_busy = narration_busy
        self._jobs = jobs if jobs is not None else []
        self._transcribing = transcribing if transcribing is not None else []

    def get_jobs(self):
        return {"jobs": self._jobs}

    def transcription_jobs(self):
        return self._transcribing

    def vibe_reel_busy(self):
        return self._vibe_busy

    def narration_busy(self):
        return self._narration_busy


@pytest.fixture
def hold_env(monkeypatch):
    monkeypatch.setattr("app.services.buzzedit_keepalive.enabled", lambda: False)
    monkeypatch.setattr(produce_api, "_studio_using_buzzedit", lambda: False)


def test_hold_when_a_reel_is_rendering(hold_env, monkeypatch):
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: _FakeBuzzEditClient(vibe_busy=True))
    assert idle_offload._buzzedit_hold() == "a reel is rendering"


def test_hold_when_a_narration_is_running(hold_env, monkeypatch):
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: _FakeBuzzEditClient(narration_busy=True))
    assert idle_offload._buzzedit_hold() == "a narration is running"


def test_no_hold_when_buzzedit_is_idle(hold_env, monkeypatch):
    monkeypatch.setattr(produce_api, "BuzzEditClient", lambda: _FakeBuzzEditClient())
    assert idle_offload._buzzedit_hold() is None


def test_zero_turns_it_off(offloads):
    seen, cfg = offloads
    cfg["idle_offload_seconds"] = 0
    idle_offload.mark_used("lm_studio")
    assert not idle_offload.check_once(_later(10_000))


def test_new_work_clears_the_offloaded_flag(offloads):
    idle_offload.mark_used("lm_studio")
    idle_offload.check_once(_later())
    assert idle_offload.offloaded()
    with idle_offload.busy():
        pass
    assert not idle_offload.offloaded()


def test_offload_now_unloads_every_model_when_a_task_ends(offloads, monkeypatch):
    seen, _ = offloads
    monkeypatch.setattr(produce_api.BuzzEditClient, "clear_vram", lambda self: seen.append("comfyui"))
    assert idle_offload.offload_now("test task")
    # Nothing was marked used: the end-of-task policy unloads them all anyway.
    assert sorted(seen) == ["comfyui", "lm_studio", "ollama"]
    assert idle_offload.offloaded()


def test_offload_now_waits_for_other_work(offloads):
    seen, _ = offloads
    with idle_offload.busy():
        assert not idle_offload.offload_now("test task")
    assert seen == []


def test_offload_now_stops_llamacpp_only_when_opted_in(offloads, monkeypatch):
    seen, cfg = offloads
    monkeypatch.setattr(produce_api.BuzzEditClient, "clear_vram", lambda self: seen.append("comfyui"))
    idle_offload.offload_now("off")
    assert "llamacpp" not in seen
    seen.clear()
    cfg["idle_offload_llamacpp"] = True
    idle_offload.offload_now("on")
    assert "llamacpp" in seen


@pytest.fixture
def buzzedit(offloads, monkeypatch):
    """A headless BuzzEdit the Studio started, idle, its queue empty."""
    from app.services import buzzedit_keepalive, process_cleanup

    seen, cfg = offloads
    state = {"jobs": [], "keep_alive": False, "nightly": False}
    monkeypatch.setattr(process_cleanup, "stop_headless_buzzedit", lambda: seen.append("stop_buzzedit") or [50, 51])
    monkeypatch.setattr(produce_api.BuzzEditClient, "clear_vram", lambda self: seen.append("comfyui"))
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs", lambda self: {"jobs": state["jobs"]})
    monkeypatch.setattr(produce_api.BuzzEditClient, "transcription_jobs", lambda self: state.get("transcribing") or [])
    # Never the real BuzzEdit: one narrating an Auto Story failed four of these tests (2026-10-26).
    monkeypatch.setattr(produce_api.BuzzEditClient, "narration_busy", lambda self: state.get("narrating", False))
    monkeypatch.setattr(produce_api.BuzzEditClient, "vibe_reel_busy", lambda self: state.get("reel", False))
    monkeypatch.setattr(produce_api, "_studio_using_buzzedit", lambda: state.get("producing", False))
    monkeypatch.setattr(buzzedit_keepalive, "enabled", lambda: state["keep_alive"])
    monkeypatch.setattr(idle_offload, "_nightly_running", lambda: state["nightly"])
    return seen, state


def test_the_headless_buzzedit_is_stopped_after_the_idle_window(buzzedit):
    seen, _ = buzzedit
    idle_offload.mark_used("buzzedit")
    idle_offload.mark_used("comfyui")
    assert not idle_offload.check_once(_later(10))
    assert idle_offload.check_once(_later())
    # Stopping it frees Whisper and ComfyUI too; LM Studio goes with BuzzEdit work.
    assert sorted(seen) == ["lm_studio", "stop_buzzedit"]


def test_a_kept_alive_buzzedit_only_has_its_models_cleared(buzzedit):
    seen, state = buzzedit
    state["keep_alive"] = True
    idle_offload.mark_used("buzzedit")
    assert idle_offload.check_once(_later())
    assert sorted(seen) == ["comfyui", "lm_studio"]
    assert not idle_offload.check_once(_later(10_000))  # not asked again


def test_a_buzzedit_with_a_queued_job_is_asked_again_a_window_later(buzzedit):
    seen, state = buzzedit
    state["jobs"] = [{"id": "job_1", "status": "pending"}]
    idle_offload.mark_used("buzzedit")
    assert idle_offload.check_once(_later())
    assert "stop_buzzedit" not in seen and "comfyui" in seen
    state["jobs"] = []
    seen.clear()
    assert not idle_offload.check_once(_later(10))
    assert idle_offload.check_once(_later(2 * 301))
    assert "stop_buzzedit" in seen


def test_nothing_is_unloaded_during_a_nightly_run(buzzedit):
    seen, state = buzzedit
    state["nightly"] = True
    idle_offload.mark_used("buzzedit")
    idle_offload.mark_used("lm_studio")
    assert not idle_offload.check_once(_later(10_000))
    assert seen == []
    state["nightly"] = False
    assert idle_offload.check_once(_later())
    assert sorted(seen) == ["lm_studio", "stop_buzzedit"]


def test_offload_now_leaves_the_buzzedit_for_the_watcher(buzzedit):
    seen, _ = buzzedit
    idle_offload.mark_used("buzzedit")
    assert idle_offload.offload_now("test task")
    assert "stop_buzzedit" not in seen  # the next queued item may need it
    seen.clear()
    assert idle_offload.check_once(_later())
    assert "stop_buzzedit" in seen


def test_a_skipped_offload_now_is_finished_by_the_watcher(buzzedit, monkeypatch):
    seen, _ = buzzedit
    monkeypatch.setattr(produce_api, "buzzedit_job_active", lambda: True)
    assert not idle_offload.offload_now("test task")
    assert seen == []
    monkeypatch.setattr(produce_api, "buzzedit_job_active", lambda: False)
    assert idle_offload.check_once(_later())
    assert sorted(seen) == ["comfyui", "lm_studio", "ollama"]


def test_an_explicit_model_load_is_unloaded_when_idle(offloads, monkeypatch):
    from integrations import llm

    seen, _ = offloads
    monkeypatch.setattr(llm, "get_loaded_lm_studio_models", lambda base: ["gemma"])
    monkeypatch.setattr(llm.requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    _REAL_ENSURE_LOADED("lm_studio", "gemma")  # conftest stubs the module attribute
    assert idle_offload.check_once(_later())
    assert seen == ["lm_studio"]


def test_a_busy_or_transcribing_buzzedit_is_held_not_stopped(buzzedit, monkeypatch):
    """2026-10-20: a BuzzEdit slow to answer (a read timeout) was taken for a
    hung one and stopped under a transcription. Slow means busy; so does a
    running transcription, or a production of the Studio's own."""
    from integrations.buzzedit_client import BuzzEditTimeout

    seen, state = buzzedit
    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs",
                        lambda self: (_ for _ in ()).throw(BuzzEditTimeout("slow")))
    idle_offload.mark_used("buzzedit")
    assert idle_offload.check_once(_later())
    assert "stop_buzzedit" not in seen

    monkeypatch.setattr(produce_api.BuzzEditClient, "get_jobs", lambda self: {"jobs": []})
    state["transcribing"] = [{"id": "trans_p1", "status": "running"}]
    seen.clear()
    idle_offload.mark_used("buzzedit")
    assert idle_offload.check_once(_later(2 * 301))
    assert "stop_buzzedit" not in seen

    state["transcribing"] = []
    state["producing"] = True
    seen.clear()
    idle_offload.mark_used("buzzedit")
    assert idle_offload.check_once(_later(4 * 301))
    assert "stop_buzzedit" not in seen
