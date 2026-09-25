"""Dexter control gateway: the capability registry, the /api/studio/invoke
entry point, and the /api/studio/capabilities manifest."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import topic_store, dexter_registry


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    # Land every vault read/write in a throwaway dir; "[]" is an explicitly
    # empty (non-seeded) vault -- same trick as tests/test_topic_store.py.
    monkeypatch.setattr(topic_store, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "saved_topics.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_unknown_action_is_a_404_error():
    res = dexter_registry.invoke("does_not_exist")
    assert res["status"] == "error"
    assert res["code"] == 404


def test_invoke_unknown_over_http_maps_the_code(client):
    res = client.post("/api/studio/invoke", json={"action": "does_not_exist"})
    assert res.status_code == 404
    assert res.json()["status"] == "error"


def test_read_action_runs(client):
    res = client.post("/api/studio/invoke", json={"action": "project_list"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["kind"] == "read"


def test_write_action_tags_dexter(client, vault):
    res = client.post(
        "/api/studio/invoke",
        json={"action": "topic_save", "params": {"topic": "Gtest Topic", "channel": "Beyond3Baje"}},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"
    rows = topic_store.find_topics("Gtest Topic")
    assert rows and rows[0]["added_by"] == "dexter"


def test_dangerous_action_is_gated(client, vault):
    # Seed a row to delete.
    topic_store.add_topic({"topic": "Gtest Topic", "channel": "Beyond3Baje"})

    refused = client.post("/api/studio/invoke", json={"action": "topic_delete", "params": {"topic": "Gtest Topic"}})
    assert refused.status_code == 403

    allowed = client.post(
        "/api/studio/invoke",
        json={"action": "topic_delete", "params": {"topic": "Gtest Topic"}, "allow_dangerous": True},
    )
    assert allowed.status_code == 200
    assert allowed.json()["status"] == "success"
    assert topic_store.find_topics("Gtest Topic") == []


def test_capabilities_manifest(client):
    body = client.get("/api/studio/capabilities").json()
    assert body["app"] == "buzzcaf"
    names = [a["name"] for a in body["actions"]]
    assert "project_create" in names
    assert "topic_update" in names  # the "move kanban stage" action
    assert len(names) == len(set(names))  # every action name is unique


def test_every_domain_is_covered(client):
    """The gateway spans the whole app, not just topics/projects."""
    actions = client.get("/api/studio/capabilities").json()["actions"]
    domains = {a["domain"] for a in actions}
    assert {"projects", "topics", "produce", "catalog", "research",
            "studio", "agents", "departments", "buzzbrain", "video_intel", "system"} <= domains
    # A representative action from each headline ask exists.
    names = {a["name"] for a in actions}
    for expected in ("project_create", "topic_update", "topic_discover",
                     "topic_research_and_save", "department_execute",
                     "buzzbrain_snapshot", "settings_set", "video_analyze"):
        assert expected in names


def test_extra_domain_read_runs(client):
    res = client.post("/api/studio/invoke", json={"action": "brands"})
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_every_handler_is_callable():
    """No entry ships without a callable handler."""
    from app.services import dexter_registry
    assert dexter_registry.CAPABILITIES
    assert all(callable(c["handler"]) for c in dexter_registry.CAPABILITIES)
