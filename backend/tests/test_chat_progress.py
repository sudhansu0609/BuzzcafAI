"""Live progress of a Studio Assistant turn (2026-10-22): the page polls
/api/studio/chat_progress/{turn_id} while its chat request is open and sees
the strategist writing, each delegation, each lookup, with times."""
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app.services import chat_progress, studio_chat
from integrations.llm import LLMService


@pytest.fixture(autouse=True)
def _clean():
    chat_progress._reset_for_tests()
    yield
    chat_progress._reset_for_tests()


def test_steps_are_recorded_with_times_and_the_turn_finishes():
    assert chat_progress.start(None, "X", "Y") is None
    assert chat_progress.begin("thinking", "nothing") is None, "no turn, no cost"

    turn = chat_progress.start("t1", "Beyond3BajeStrategist", "Beyond3Baje")
    assert turn == "t1" and chat_progress.current() == "t1"
    with chat_progress.step("thinking", "writing") as s:
        s["note"] = "12 words"
    index = chat_progress.begin("delegation", "FactChecker is working on it", "check the dates")
    snap = chat_progress.snapshot("t1")
    assert snap["status"] == "running"
    assert [x["status"] for x in snap["steps"]] == ["done", "running"]
    assert snap["steps"][0]["note"] == "12 words" and snap["steps"][0]["seconds"] is not None
    assert snap["steps"][1]["seconds"] >= 0, "a running step shows its elapsed time"
    chat_progress.end(index, "done", "80 words back")
    chat_progress.note("Librarian not run", "skipped")
    chat_progress.finish("t1", "done")
    snap = chat_progress.snapshot("t1")
    assert snap["status"] == "done" and snap["elapsed"] >= 0
    assert [x["kind"] for x in snap["steps"]] == ["thinking", "delegation", "skipped"]
    assert chat_progress.current() is None
    assert chat_progress.snapshot("nope") is None


def test_a_failed_step_and_a_failed_turn_are_marked():
    chat_progress.start("t2", "A", "B")
    with pytest.raises(RuntimeError):
        with chat_progress.step("web_search", "Searching", "q"):
            raise RuntimeError("no network")
    chat_progress.begin("delegation", "still running")
    chat_progress.finish("t2", "failed", "provider down")
    snap = chat_progress.snapshot("t2")
    assert snap["status"] == "failed" and snap["note"] == "provider down"
    assert snap["steps"][0]["status"] == "failed" and snap["steps"][0]["note"] == "no network"
    assert snap["steps"][1]["status"] == "failed", "an open step is closed with the turn"


def test_run_chat_reports_the_strategist_and_each_delegation(monkeypatch):
    from app.services import events

    seen: List[Any] = []
    monkeypatch.setattr(events.bus, "publish", lambda event_type, payload=None: seen.append((event_type, payload)))
    reply = ("Plan.\n[INVOKE_AGENT: FactChecker]Verify the dates.[/INVOKE_AGENT]"
             "[INVOKE_AGENT: TitleGenerator]Three titles.[/INVOKE_AGENT]")

    def fake_chat(self, system_prompt, messages, require_json=False, **kwargs):
        self.last_response_simulated = False
        return reply

    monkeypatch.setattr(LLMService, "generate_chat", fake_chat)

    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        return "Specialist findings."

    monkeypatch.setattr(LLMService, "generate_text", fake_text)

    result = studio_chat.run_chat("plan it", "Beyond3Baje", turn_id="turn-abc")
    assert result["turn_id"] == "turn-abc"
    kinds = [s["kind"] for s in result["progress"]]
    assert kinds == ["thinking", "delegation", "delegation"]
    assert result["progress"][0]["note"].endswith("2 delegations asked for")
    assert result["progress"][1]["label"] == "FactChecker is working on it"
    assert result["progress"][1]["detail"] == "Verify the dates."
    assert all(s["status"] == "done" for s in result["progress"])
    assert chat_progress.snapshot("turn-abc")["status"] == "done", "readable after the reply"
    progress_frames = [p for kind, p in seen if kind == "chat_progress"]
    assert progress_frames and progress_frames[-1]["status"] == "done"
    invoked = [p for kind, p in seen if kind == "agent_invoked"]
    assert [p["turn_id"] for p in invoked] == ["turn-abc", "turn-abc"]

    from memory.memory import memory_system
    for owner in ("FactChecker", "TitleGenerator", "Beyond3BajeStrategist"):
        memory_system.clear(scope="agent", owner=owner)
    memory_system.clear(scope="session", owner="Beyond3Baje")


def test_the_route_serves_a_turn_and_404s_an_unknown_one():
    from app.main import app

    client = TestClient(app)
    assert client.get("/api/studio/chat_progress/none-such").status_code == 404
    chat_progress.start("t9", "A", "B")
    chat_progress.begin("thinking", "writing")
    body = client.get("/api/studio/chat_progress/t9").json()
    assert body["status"] == "running" and body["steps"][0]["label"] == "writing"
