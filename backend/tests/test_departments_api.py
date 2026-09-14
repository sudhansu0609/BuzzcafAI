"""
Departments as a callable surface (roadmap v9, E1/E3/E4).

What these protect: every registered persona belongs to exactly one department
class, listing departments does not instantiate any agent, a task with no role
goes to the manager, an unknown department is a 404, and a workflow step may
name a department instead of a persona.
"""

import pytest
from fastapi.testclient import TestClient

from app.departments import DEPARTMENT_CLASSES, get_department, list_departments
from app.main import app
from app.services import events
from core.agent import agent_registry
from core.errors import LLMUnavailable
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.workflow import WorkflowRegistry
from integrations.llm import LLMService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def fake_llm(monkeypatch):
    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        return f"[{user_prompt[:40]}] handled."

    monkeypatch.setattr(LLMService, "generate_text", fake_text)


def test_every_persona_belongs_to_exactly_one_department():
    """v9 E4: the 12 classes plus Creative cover the whole registry, no overlap."""
    seen = {}
    duplicates = []
    for dept in list_departments():
        for role in dept.list_agents():
            key = role.lower()
            if key in seen:
                duplicates.append((role, seen[key], dept.name))
            seen[key] = dept.name
    assert duplicates == []
    assert seen.keys() == agent_registry.agents.keys()


def test_departments_list_has_thirteen_entries(client):
    body = client.get("/api/departments").json()
    assert body["count"] == len(DEPARTMENT_CLASSES) == 13
    names = [d["name"] for d in body["departments"]]
    assert "Research" in names and "Creative" in names
    research = next(d for d in body["departments"] if d["name"] == "Research")
    assert research["manager"] == "ResearchManager"
    assert "FactChecker" in research["specialists"]


def test_construction_is_lazy():
    """v9 E1: a department builds its agents on first use, not on __init__."""
    fresh = [cls() for cls in DEPARTMENT_CLASSES]
    assert all(d.manager_agent is None and d.specialists == {} for d in fresh)
    first = fresh[0]
    assert first.get_agent(first.manager_role) is not None
    assert first.manager_agent is not None


def test_execute_routes_to_the_manager_by_default(client, fake_llm):
    res = client.post("/api/departments/Research/execute", json={"task": "Find sources on the 1923 mill fire"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department"] == "Research"
    assert body["agent"] == "ResearchManager"
    assert body["simulated"] is False
    assert "handled." in body["output"]


def test_execute_can_target_a_specialist_and_publishes_an_event(client, fake_llm, monkeypatch):
    seen = []
    monkeypatch.setattr(events.bus, "publish", lambda kind, payload=None: seen.append((kind, payload)))
    res = client.post(
        "/api/departments/research/execute",
        json={"task": "Verify the 1923 dates", "role": "FactChecker"},
    )
    assert res.status_code == 200
    assert res.json()["agent"] == "FactChecker"
    assert ("department_task", {
        "department": "Research", "agent": "FactChecker",
        "task_preview": "Verify the 1923 dates", "simulated": False,
    }) in seen


def test_unknown_department_is_404(client):
    assert client.post("/api/departments/Legal/execute", json={"task": "read this"}).status_code == 404


def test_unknown_role_inside_a_department_is_404(client):
    res = client.post("/api/departments/Research/execute", json={"task": "hi", "role": "TagGenerator"})
    assert res.status_code == 404
    assert "not in the Research department" in res.json()["detail"]


def test_no_provider_is_502(client, monkeypatch):
    def unavailable(self, system_prompt, user_prompt, require_json=False, **kwargs):
        raise LLMUnavailable("No LLM provider is reachable.")

    monkeypatch.setattr(LLMService, "generate_text", unavailable)
    res = client.post("/api/departments/Support/execute", json={"task": "review this"})
    assert res.status_code == 502


def test_a_workflow_step_may_name_a_department(fake_llm):
    """v9 E3: 'Research' validates, and the step runs as the department manager."""
    registry = WorkflowRegistry()
    wf = WorkflowDefinition(
        id="test_department_step_wf",
        name="Department Step",
        description="A step addressed to a department rather than a persona",
        steps=[
            WorkflowStep(
                name="Research",
                agent_role="Research",
                description="Gather background",
                requires_approval=False,
                input_assets=[],
                output_asset_type="research_package",
            )
        ],
    )
    registry.register(wf)
    try:
        from runtime.workflow import WorkflowEngine

        agent = WorkflowEngine()._resolve_agent("Research")
        assert agent.agent_name == get_department("Research").manager_role == "ResearchManager"
    finally:
        registry.unregister("test_department_step_wf")
