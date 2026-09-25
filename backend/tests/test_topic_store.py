"""topic_store: the single source of truth for the saved-topic vault, plus
the /api/topics/update endpoint that sits on top of it.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import topic_store


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    # topic_store re-reads its module-level KNOWLEDGE_DIR at call time, so
    # this lands every read/write (direct or via the /api/topics endpoints)
    # in a throwaway directory instead of the shared test sandbox vault.
    monkeypatch.setattr(topic_store, "KNOWLEDGE_DIR", str(tmp_path))
    # Start from an explicitly empty vault: an absent/zero-byte file triggers
    # topic_store's seed-on-empty behaviour (two starter topics), which would
    # otherwise pollute the find/count assertions below. Writing "[]" is a
    # real, non-empty vault with no rows.
    (tmp_path / "saved_topics.json").write_text("[]", encoding="utf-8")
    return tmp_path


def test_add_topic_stamps_id_stage_and_added_by(vault):
    row = topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje"})
    assert row["id"]
    assert row["stage"] == topic_store.DEFAULT_STAGE
    assert row["added_by"] == "user"
    assert row["saved_at"] and row["updated_at"]


def test_add_topic_dedupes_on_topic_and_channel(vault):
    # Same (topic, channel) twice must update the one row in place, not add
    # a second -- matching main.py's original save_topic exactly, including
    # that a re-save without an explicit "id" mints a fresh one.
    topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje", "notes": "v1"})
    second = topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje", "notes": "v2"})

    topics = topic_store.load_topics()
    matching = [t for t in topics if t.get("topic") == "A Story" and t.get("channel") == "Beyond3Baje"]
    assert len(matching) == 1
    assert matching[0]["id"] == second["id"]
    assert matching[0]["notes"] == "v2"


def test_update_topic_changes_stage_and_unknown_id_is_none(vault):
    row = topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje"})

    updated = topic_store.update_topic(row["id"], {"stage": "researching"})
    assert updated["stage"] == "researching"

    assert topic_store.update_topic("does_not_exist", {"stage": "published"}) is None


def test_find_topics_matches_by_query_and_channel(vault):
    topic_store.add_topic({"topic": "Ghost Fort Mystery", "channel": "Raat3Baje", "notes": "spooky"})
    topic_store.add_topic({"topic": "Warship Disaster", "channel": "Beyond3Baje", "notes": "engineering"})

    by_query = topic_store.find_topics("ghost")
    assert [t["topic"] for t in by_query] == ["Ghost Fort Mystery"]

    by_channel = topic_store.find_topics("", channel="beyond3baje")
    assert [t["topic"] for t in by_channel] == ["Warship Disaster"]

    by_query_and_channel = topic_store.find_topics("disaster", channel="Beyond3Baje")
    assert [t["topic"] for t in by_query_and_channel] == ["Warship Disaster"]

    assert topic_store.find_topics("nonexistent") == []


def test_update_endpoint_moves_a_stage(client, vault):
    row = topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje"})

    res = client.post("/api/topics/update", json={"id": row["id"], "stage": "in_progress"})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "success"
    assert body["topic"]["stage"] == "in_progress"


def test_update_endpoint_rejects_invalid_stage(client, vault):
    row = topic_store.add_topic({"topic": "A Story", "channel": "Beyond3Baje"})

    res = client.post("/api/topics/update", json={"id": row["id"], "stage": "not_a_real_stage"})
    assert res.status_code == 400
    assert res.json()["status"] == "error"


def test_update_endpoint_unknown_id_is_404(client, vault):
    res = client.post("/api/topics/update", json={"id": "does_not_exist", "stage": "published"})
    assert res.status_code == 404
    assert res.json()["status"] == "error"
