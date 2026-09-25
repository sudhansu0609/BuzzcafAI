"""
The control surface Dexter drives (roadmap v5, 3.1): state, chat, approve, events.
Runs against the test sandbox from conftest.py, so projects created here are
throwaway.
"""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import events, topic_store
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
    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        return "# Research package\n\nFindings for the step."

    def fake_chat(self, system_prompt, messages, require_json=False, **kwargs):
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
        # v9 C3: the UI's Approve button posts here, so approve must announce
        # itself on the bus exactly like execute does - one frame per run.
        assert sum(1 for kind, _ in recorded_events if kind == "step_started") == 2
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
    def boom(self, system_prompt, messages, require_json=False, **kwargs):
        raise RuntimeError("no model")

    monkeypatch.setattr(LLMService, "generate_chat", boom)
    res = client.post("/api/studio/chat", json={"message": "hi", "channel": "Beyond3Baje"})
    assert res.status_code == 502
    assert res.json()["status"] == "error"


def test_discover_returns_model_topics_when_a_provider_answers(client, monkeypatch):
    """v9 D2: the strategist writes the ideas; the seed list is only a fallback."""
    dossier = json.dumps({"topics": [
        {"topic": "Sundarban Ka Wo Jahaz Jo Kabhi Laut Ke Nahi Aaya", "category": "Maritime mystery"},
        {"topic": "Kolkata Ki Wo Suranga Jise Sabne Bhula Diya", "category": "Dark history"},
    ]})

    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        assert require_json is True
        return dossier

    monkeypatch.setattr(LLMService, "generate_text", fake_text)
    body = client.post("/api/topics/discover", json={"channel": "Beyond3Baje"}).json()
    assert body["source"] == "model"
    assert body["agent_assigned"] == "Beyond3BajeStrategist"
    assert [t["topic"] for t in body["topics"]] == [
        "Sundarban Ka Wo Jahaz Jo Kabhi Laut Ke Nahi Aaya",
        "Kolkata Ki Wo Suranga Jise Sabne Bhula Diya",
    ]
    assert all(t["channel"] == "Beyond3Baje" for t in body["topics"])


def test_discover_falls_back_to_the_labelled_seed_list(client, monkeypatch):
    """No provider answered: seed topics, tagged as seed topics."""
    def simulated(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = True
        return "Sorry, no model is available."

    monkeypatch.setattr(LLMService, "generate_text", simulated)
    body = client.post("/api/topics/discover", json={"channel": "Beyond3Baje"}).json()
    assert body["source"] == "curated_seed"
    assert body["topics"]


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


def test_allow_all_bypasses_approval_and_toggle(client, fake_llm):
    # Test 1: Project created with allow_all=True completes steps without paused_for_approval
    res = client.post(
        "/api/projects",
        json={"name": "Auto run probe", "brand": "Beyond3Baje", "workflow_name": "beyond3baje_documentary", "allow_all": True},
    )
    assert res.status_code == 200
    p_id = res.json()["id"]
    try:
        run = client.post(f"/api/projects/{p_id}/execute", json={})
        assert run.status_code == 200
        last = run.json()["steps_history"][-1]
        assert last["status"] == "completed"  # Bypassed paused_for_approval!
        assert run.json()["current_step"] != last["step_name"]  # Advanced immediately!
    finally:
        _cleanup(p_id)

    # Test 2: Project created with allow_all=False pauses, then toggle_allow_all unblocks it
    res2 = client.post(
        "/api/projects",
        json={"name": "Toggle probe", "brand": "Beyond3Baje", "workflow_name": "beyond3baje_documentary", "allow_all": False},
    )
    assert res2.status_code == 200
    p2_id = res2.json()["id"]
    try:
        run2 = client.post(f"/api/projects/{p2_id}/execute", json={})
        assert run2.status_code == 200
        assert run2.json()["steps_history"][-1]["status"] == "paused_for_approval"

        # Toggle allow all ON
        toggled = client.post(f"/api/projects/{p2_id}/toggle_allow_all").json()
        assert toggled["metadata"]["allow_all"] is True
        # Since it was waiting, toggle also immediately approved and advanced
        assert toggled["steps_history"][-1]["status"] == "completed"
    finally:
        _cleanup(p2_id)


def test_project_resilient_deserialization():
    from core.models.project import Project, StepExecution
    data = {
        "id": "test_resilient_proj",
        "name": "Resilient Proj",
        "brand": "Beyond3Baje",
        "workflow_name": "beyond3baje_documentary",
        "status": "active",
        "future_unknown_project_field": "some_value",
        "steps_history": [
            {
                "step_name": "Research",
                "agent_name": "ResearchAgent",
                "status": "completed",
                "started_at": "2026-09-16T10:00:00",
                "future_unknown_step_field": 12345,
                "simulated": False,
            }
        ],
    }
    p = Project.from_dict(data)
    assert p.id == "test_resilient_proj"
    assert len(p.steps_history) == 1
    assert p.steps_history[0].step_name == "Research"
    assert p.steps_history[0].simulated is False


def test_delete_project_api(client, recorded_events):
    res = client.post(
        "/api/projects",
        json={"name": "Delete Probe", "brand": "Beyond3Baje", "workflow_name": "beyond3baje_documentary"},
    )
    assert res.status_code == 200
    p_id = res.json()["id"]

    # Deleting nonexistent returns 404
    assert client.delete("/api/projects/nonexistent_xyz").status_code == 404

    # Deleting with invalid characters returns 400
    assert client.delete("/api/projects/bad!name").status_code == 400

    # Deleting existing project succeeds
    del_res = client.delete(f"/api/projects/{p_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"
    assert del_res.json()["id"] == p_id
    assert any(kind == "project_deleted" and payload["project_id"] == p_id for kind, payload in recorded_events)

    # Confirm it no longer exists
    assert client.get(f"/api/projects/{p_id}").status_code == 404


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setattr(topic_store, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "saved_topics.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_capabilities_lists_actions(client):
    res = client.get("/api/studio/capabilities")
    assert res.status_code == 200
    body = res.json()
    assert body["app"] == "buzzcaf"
    assert isinstance(body["actions"], list) and body["actions"]
    # /capabilities is now generated from the Dexter capability registry
    # (the single source of truth shared with POST /api/studio/invoke).
    names = {a["name"] for a in body["actions"]}
    assert {"topic_research_and_save", "studio_search", "topic_list", "topic_save"} <= names


def test_research_and_save_writes_a_dexter_row(client, vault, monkeypatch):
    import app.api.studio_api as studio_api

    canned = {"verdict": {"demand": {"reason": "trending in-region"}}}
    monkeypatch.setattr(studio_api, "topic_store", topic_store)

    def fake_validate_topic(topic, channel=None, force=False):
        return canned

    import app.services.topic_validation as topic_validation
    monkeypatch.setattr(topic_validation, "validate_topic", fake_validate_topic)

    res = client.post(
        "/api/studio/topics/research_and_save",
        json={"topic": "The Lost Signal", "channel": "Beyond3Baje"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["topic"]["added_by"] == "dexter"
    assert body["topic"]["stage"] == "researching"
    assert body["topic"]["topic"] == "The Lost Signal"

