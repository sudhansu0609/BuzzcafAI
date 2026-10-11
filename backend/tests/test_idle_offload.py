"""`integrations/idle_offload.py`: unload what the Studio used once nothing
has run for `idle_offload_seconds`. Servers and BuzzEdit are faked."""
import time

import pytest

from app.api import produce_api
from app.services import produce_queue
from integrations import idle_offload


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
