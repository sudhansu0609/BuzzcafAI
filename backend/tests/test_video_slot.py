"""One video at a time, the local-model room check and the voice text cleaner (2026-10-26)."""
import threading
import time

import pytest

from app.services import auto_story, produce_queue, video_slot
from integrations import llm


def _queue(monkeypatch, items, paused=False):
    monkeypatch.setattr(produce_queue, "snapshot", lambda: {"paused": paused, "items": items})
    monkeypatch.setattr(produce_queue, "kick", lambda: None)


@pytest.fixture(autouse=True)
def _no_master_pause(monkeypatch):
    # The owner's PC may really be paused; waiting in line must not hang a test on it.
    from app.services import master_control
    monkeypatch.setattr(master_control, "wait_if_paused", lambda *a, **k: None)


def test_nothing_running_means_free(monkeypatch):
    _queue(monkeypatch, [])
    assert video_slot.active() is None


def test_running_and_queued_items_hold_the_slot_paused_ones_do_not(monkeypatch):
    running = {"id": "q1", "project_id": "p1", "title": "One", "status": "running", "checkpoint": "render",
               "progress": 0.5, "message": "Rendering"}
    _queue(monkeypatch, [running])
    info = video_slot.active()
    assert info["title"] == "One" and info["progress_pct"] == 50 and info["can_pause"] is False
    assert video_slot.active(exclude="p1") is None
    _queue(monkeypatch, [{**running, "status": "paused"}])
    assert video_slot.active() is None
    _queue(monkeypatch, [{**running, "status": "queued"}], paused=True)
    assert video_slot.active() is None


def test_second_video_waits_for_the_first(monkeypatch):
    _queue(monkeypatch, [])
    monkeypatch.setattr(video_slot, "POLL_S", 0.05)
    order = []
    first_in = threading.Event()
    release = threading.Event()

    def first():
        with video_slot.turn("a", title="A"):
            order.append("a-start")
            first_in.set()
            release.wait(5)
            order.append("a-end")

    def second():
        first_in.wait(5)
        with video_slot.turn("b", title="B"):
            order.append("b-start")

    t1, t2 = threading.Thread(target=first), threading.Thread(target=second)
    t1.start(); t2.start()
    first_in.wait(5)
    time.sleep(0.3)
    assert order == ["a-start"]
    assert video_slot.active(exclude="b")["title"] == "A"
    release.set()
    t1.join(5); t2.join(5)
    assert order == ["a-start", "a-end", "b-start"]


def test_a_render_buzzedit_runs_by_itself_holds_the_slot(monkeypatch):
    _queue(monkeypatch, [], paused=True)
    monkeypatch.setattr(video_slot, "_buzzedit_blocker",
                        lambda: {"project_id": "p9", "title": "Harrison Okene", "can_pause": False})
    assert video_slot.active()["title"] == "Harrison Okene"
    assert video_slot.active(exclude="p9") is None


def test_queue_worker_holds_off_while_another_voice_is_made(monkeypatch):
    video_slot._holders["other"] = {"project_id": "other", "title": "Other"}
    assert video_slot.other_holder("mine")["title"] == "Other"
    assert video_slot.other_holder("other") is None


def test_run_endpoint_answers_video_running(monkeypatch):
    from fastapi import HTTPException
    from app.api import auto_story_api
    monkeypatch.setattr(video_slot, "active", lambda exclude=None: {"title": "Harrison Okene", "progress_pct": 86,
                                                                     "doing": "Applying the moods"})
    with pytest.raises(HTTPException) as err:
        auto_story_api._refuse_if_busy(False, exclude="p2")
    assert err.value.status_code == 409
    assert err.value.detail["code"] == "video_running"
    assert "Harrison Okene" in err.value.detail["message"]
    auto_story_api._refuse_if_busy(True, exclude="p2")  # "start mine after it" goes through


def test_room_check(monkeypatch):
    monkeypatch.setattr(llm, "free_memory_mib", lambda: (9000, 20000))
    assert llm.local_headroom_problem(8704, loaded=False) is not None   # 8704 + 1536 > 9000
    assert llm.local_headroom_problem(6000, loaded=False) is None
    monkeypatch.setattr(llm, "free_memory_mib", lambda: (500, 20000))
    assert llm.local_headroom_problem(8704, loaded=True) is None        # already loaded: no new VRAM
    monkeypatch.setattr(llm, "free_memory_mib", lambda: (12000, 3000))
    assert "RAM" in llm.local_headroom_problem(4000, loaded=True)


def test_voice_text_is_cleaned():
    text = ("Pehla camera sirf ek distraction tha.\n\nPurana ant. **Bag** uthaya.\n\n"
            "(The text continues from: \"Pehla kamera sirf ek distraction tha.\")\n\n"
            "Naya ant. [VIS1: a dark hall] *THUD.* [pause] [FADE TO BLACK.] COACH: [number].")
    out = auto_story.clean_for_voice(text)
    assert "Purana ant" not in out and "continues from" not in out
    assert "Naya ant." in out and "THUD." in out and "(pause)" in out
    assert "[" not in out and "*" not in out
