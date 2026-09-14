"""
The Studio Assistant turn (roadmap v5, 2.4).

What these protect: the persona is the system prompt and appears once; the
strategist roster appears once; at most six memories ride along and only the
relevant ones; the chat is not forced into Hinglish; the last eight turns go
to the model as real messages; a simulated reply is labelled; a provider
failure is an HTTP 502, not a 200 with an apology inside.
"""

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import studio_chat
from core.base_agent import BaseAgent
from integrations.llm import LLMService


class Capture:
    """Stands in for LLMService.generate_chat and records what it was given."""

    def __init__(self, reply: str = "Here is my take.", simulated: bool = False):
        self.reply = reply
        self.simulated = simulated
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, service, system_prompt, messages, require_json=False, **kwargs):
        service.last_response_simulated = self.simulated
        self.calls.append({"system": system_prompt, "messages": messages})
        return self.reply


def bind(cap: Capture):
    """A plain function so monkeypatch installs it as a real method (self is passed)."""

    def fake(self, system_prompt, messages, require_json=False, **kwargs):
        return cap(self, system_prompt, messages, require_json)

    return fake


@pytest.fixture
def capture(monkeypatch):
    cap = Capture()
    monkeypatch.setattr(LLMService, "generate_chat", bind(cap))
    return cap


def test_persona_and_roster_appear_once_and_chat_is_not_forced_into_hinglish(capture):
    studio_chat.run_chat("What should the next video be about?", "Beyond3Baje")
    system = capture.calls[-1]["system"]
    assert system.count("Beyond3BajeStrategist") >= 1
    assert system.count("## Studio Workforce & Inter-Agent Operations") == 1
    assert "HINGLISH ENFORCEMENT" not in system
    assert "Brand guide for Beyond3Baje" in system
    assert "the language the creator writes in" in system


def test_workflow_steps_keep_the_hinglish_directive():
    agent = BaseAgent.__new__(BaseAgent)
    agent.agent_name = "ScriptWriter"
    assert "HINGLISH ENFORCEMENT" in agent._load_system_prompt()
    assert "HINGLISH ENFORCEMENT" not in agent._load_system_prompt(hinglish=False)


def test_history_is_passed_as_messages_and_capped(capture):
    history = []
    for i in range(10):
        history.append({"role": "user", "content": f"question {i}"})
        history.append({"role": "assistant", "content": f"answer {i}"})
    studio_chat.run_chat("final question", "Khayal3Baje", history=history)
    messages = capture.calls[-1]["messages"]
    assert messages[-1] == {"role": "user", "content": "final question"}
    assert len(messages) == studio_chat.HISTORY_TURNS + 1
    assert messages[0]["content"] == "question 6"
    assert {m["role"] for m in messages} <= {"user", "assistant"}


def test_only_relevant_memories_ride_along_and_at_most_six(capture):
    from memory.memory import memory_system

    owner = "Khayal3BajeStrategist"
    memory_system.clear(scope="agent", owner=owner)
    for i in range(10):
        memory_system.save(
            scope="agent", owner=owner, tags=["chat"],
            content={"user": f"tell me about temple {i}", "reply": f"temple {i} lore", "agent": owner, "channel": "Khayal3Baje"},
        )
    memory_system.save(
        scope="agent", owner=owner, tags=["chat"],
        content={"user": "what about the bhangarh fort guard", "reply": "the guard vanished at 3 am", "agent": owner, "channel": "Khayal3Baje"},
    )

    studio_chat.run_chat("more on the bhangarh guard story", "Khayal3Baje")
    system = capture.calls[-1]["system"]
    assert "Relevant past exchanges" in system
    assert "bhangarh" in system.lower()
    assert system.count("You were asked:") <= studio_chat.MEMORY_LIMIT
    assert "temple 0" not in system  # unrelated exchanges are not dumped in
    memory_system.clear(scope="agent", owner=owner)
    memory_system.clear(scope="session", owner="Khayal3Baje")


def test_simulated_replies_are_labelled(monkeypatch):
    cap = Capture(reply="[canned]", simulated=True)
    monkeypatch.setattr(LLMService, "generate_chat", bind(cap))
    result = studio_chat.run_chat("hello", "Life3Baje")
    assert result["simulated"] is True
    assert result["status"] == "simulated"


def test_full_exchange_is_stored(capture):
    from memory.memory import memory_system

    owner = "Life3BajeStrategist"
    memory_system.clear(scope="agent", owner=owner)
    long_reply = "x" * 1500
    capture.reply = long_reply
    studio_chat.run_chat("write me something long", "Life3Baje")
    stored = memory_system.retrieve(scope="agent", owner=owner, limit=1)
    assert stored and stored[0].content["reply"] == long_reply
    memory_system.clear(scope="agent", owner=owner)
    memory_system.clear(scope="session", owner="Life3Baje")


def test_provider_failure_is_a_502(monkeypatch):
    def boom(service, system_prompt, messages, require_json=False, **kwargs):
        raise RuntimeError("model server down")

    monkeypatch.setattr(LLMService, "generate_chat", boom)
    client = TestClient(app)
    res = client.post(
        "/api/topics/agent_chat",
        json={"agent_name": "Beyond3BajeStrategist", "channel": "Beyond3Baje", "message": "hi"},
    )
    assert res.status_code == 502
    body = res.json()
    assert body["status"] == "error"
    assert "model server down" in body["detail"]


def test_route_returns_the_reply_shape(capture):
    client = TestClient(app)
    res = client.post(
        "/api/topics/agent_chat",
        json={"agent_name": "", "channel": "Raat3Baje", "message": "give me a hook"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["agent_name"] == "AfterDarkStrategist"
    assert body["reply"] == "Here is my take."
    assert body["simulated"] is False


def _tag(agent: str, task: str) -> str:
    return f"[INVOKE_AGENT: {agent}]{task}[/INVOKE_AGENT]"


@pytest.fixture
def delegation(monkeypatch):
    """A strategist reply full of tags, a stub specialist, and a recording bus."""
    from app.services import events

    seen: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        events.bus, "publish",
        lambda event_type, payload=None: seen.append((event_type, payload)),
    )

    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        return "Specialist findings."

    monkeypatch.setattr(LLMService, "generate_text", fake_text)
    return seen


def test_two_invocations_produce_two_records_and_two_frames(monkeypatch, delegation):
    reply = "Here is the plan.\n" + _tag("FactChecker", "Verify the 1923 dates.") + _tag("TitleGenerator", "Three titles.")
    monkeypatch.setattr(LLMService, "generate_chat", bind(Capture(reply=reply)))

    result = studio_chat.run_chat("plan the video", "Beyond3Baje")
    records = result["invocations"]
    assert [r["agent"] for r in records] == ["FactChecker", "TitleGenerator"]
    assert all(r["output"] == "Specialist findings." for r in records)
    assert all(r["simulated"] is False for r in records)
    assert "[INVOKE_AGENT" not in result["reply"]
    assert result["reply"].count("Delegated to") == 2

    frames = [payload for kind, payload in delegation if kind == "agent_invoked"]
    assert [f["agent"] for f in frames] == ["FactChecker", "TitleGenerator"]
    assert frames[0]["task_preview"] == "Verify the 1923 dates."

    from memory.memory import memory_system
    stored = memory_system.retrieve(scope="agent", owner="FactChecker", limit=1)
    assert stored and "delegated" in stored[0].tags
    for owner in ("FactChecker", "TitleGenerator", "Beyond3BajeStrategist"):
        memory_system.clear(scope="agent", owner=owner)
    memory_system.clear(scope="session", owner="Beyond3Baje")


def test_a_fourth_invocation_is_skipped_not_run(monkeypatch, delegation):
    reply = "".join(_tag(name, f"do {name}") for name in ["FactChecker", "TitleGenerator", "TagGenerator", "Librarian"])
    monkeypatch.setattr(LLMService, "generate_chat", bind(Capture(reply=reply)))

    result = studio_chat.run_chat("delegate everything", "Beyond3Baje")
    records = result["invocations"]
    assert len(records) == 4
    assert sum(1 for r in records if r.get("skipped")) == 1
    assert records[-1]["agent"] == "Librarian" and records[-1]["skipped"] is True
    assert "Librarian` was not run" in result["reply"]
    assert len([p for kind, p in delegation if kind == "agent_invoked"]) == studio_chat.MAX_INVOCATIONS

    from memory.memory import memory_system
    for owner in ("FactChecker", "TitleGenerator", "TagGenerator", "Librarian", "Beyond3BajeStrategist"):
        memory_system.clear(scope="agent", owner=owner)
    memory_system.clear(scope="session", owner="Beyond3Baje")


def test_query_aware_memory_retrieval_falls_back_to_recency():
    from memory.memory import memory_system

    owner = "RetrievalProbe"
    memory_system.clear(scope="agent", owner=owner)
    memory_system.save(scope="agent", owner=owner, tags=[], content="first note about coffee")
    memory_system.save(scope="agent", owner=owner, tags=[], content="second note about trains")
    by_query = memory_system.retrieve(scope="agent", owner=owner, query="tell me about trains")
    assert by_query and "trains" in str(by_query[0].content)
    by_recency = memory_system.retrieve(scope="agent", owner=owner, query="nothing matches here zzz")
    assert len(by_recency) == 2
    memory_system.clear(scope="agent", owner=owner)
