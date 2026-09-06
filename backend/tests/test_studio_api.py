"""
The control surface Dexter drives (roadmap v5, 3.1): state, chat, approve, events.
Runs against the test sandbox from conftest.py, so projects created here are
throwaway.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import events
from integrations.llm import LLMService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def recorded_events(monkeypatch):
    seen = []
    monkeypatch.setattr(events.bus, "publish", lambda event_type, payload=None: seen.append((event_type, payload)))
    return seen


@pytest.fixture
def fake_llm(monkeypatch):
    def fake_text(self, system_prompt, user_prompt, require_json=False):
        self.last_response_simulated = False
        return "# Research package\n\nFindings for the step."

    def fake_chat(self, system_prompt, messages, require_json=False):
        self.last_response_simulated = False
        return "Strategist reply."

    monkeypatch.setattr(LLMService, "generate_text", fake_text)
    monkeypatch.setattr(LLMService, "generate_chat", fake_chat)


def _cleanup(project_id: str):
    from core.models.project import Project

    try:
        shutil.rmtree(Project.load(project_id).get_project_dir(), ignore_errors=True)
    except Exception:
        pass


def test_state_has_the_shape_dexter_reads(client):
    res = client.get("/api/studio/state")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "buzzcaf"
    assert set(body["projects"]) == {"total", "in_progress", "paused_for_approval", "done"}
    assert isinstance(body["pending_approvals"], list)
    assert isinstance(body["brands"], list) and "Beyond3Baje" in body["brands"]
    assert "saved_topics_count" in body and "buzzbrain" in body


def test_health_identifies_the_studio(client):
    body = client.get("/health").json()
    assert body["app"] == "buzzcaf"
    assert body["version"]


def test_create_publishes_and_approve_advances_a_paused_step(client, recorded_events, fake_llm):
    res = client.post(
        "/api/projects",
        json={"name": "Control API probe", "brand": "Beyond3Baje", "workflow_name": "beyond3baje_documentary"},
    )
    assert res.status_code == 200, res.text
    project_id = res.json()["id"]
    try:
        assert any(kind == "project_created" and payload["project_id"] == project_id for kind, payload in recorded_events)

        # Nothing is waiting yet: approve must refuse rather than silently run a step.
        assert client.post(f"/api/projects/{project_id}/approve").status_code == 409

        run = client.post(f"/api/projects/{project_id}/execute", json={})
        assert run.status_code == 200, run.text
        last = run.json()["steps_history"][-1]
        assert last["status"] == "paused_for_approval"
        assert any(kind == "approval_needed" for kind, _ in recorded_events)

        state = client.get("/api/studio/state").json()
        assert any(p["project_id"] == project_id for p in state["pending_approvals"])

        approved = client.post(f"/api/projects/{project_id}/approve").json()
        assert approved["steps_history"][-1]["status"] == "completed"
        assert approved["current_step"] != last["step_name"]
        assert any(kind == "step_completed" for kind, _ in recorded_events)
    finally:
        _cleanup(project_id)


def test_approve_unknown_project_is_404(client):
    assert client.post("/api/projects/does_not_exist/approve").status_code == 404


def test_studio_chat_uses_the_channel_strategist(client, fake_llm):
    res = client.post("/api/studio/chat", json={"message": "hook ideas", "channel": "Khayal3Baje"})
    assert res.status_code == 200
    body = res.json()
    assert body["agent_name"] == "Khayal3BajeStrategist"
    assert body["reply"] == "Strategist reply."


def test_studio_chat_failure_is_502(client, monkeypatch):
    def boom(self, system_prompt, messages, require_json=False):
        raise RuntimeError("no model")

    monkeypatch.setattr(LLMService, "generate_chat", boom)
    res = client.post("/api/studio/chat", json={"message": "hi", "channel": "Beyond3Baje"})
    assert res.status_code == 502
    assert res.json()["status"] == "error"


def test_event_frames_are_well_formed():
    frame = events.frame("approval_needed", {"project_id": "p1"}, 1.0)
    assert frame.startswith("event: approval_needed\ndata: ")
    assert '"project_id": "p1"' in frame
    assert frame.endswith("\n\n")


def test_bus_delivers_to_subscribers_and_remembers_the_last_event():
    bus = events.EventBus()
    queue = bus.subscribe()
    bus.publish("approval_needed", {"project_id": "p1"})
    message = queue.get_nowait()
    assert message["type"] == "approval_needed" and message["payload"]["project_id"] == "p1"
    assert bus.last["approval_needed"]["payload"]["project_id"] == "p1"
    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0
