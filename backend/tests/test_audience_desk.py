"""The Audience Desk (2026-10-22): comments under the niche's videos ->
findings with evidence -> vault rows. yt-dlp and the model are stubbed."""
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app.services import audience_desk as A


@pytest.fixture
def desk(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "AUDIENCE_DIR", tmp_path / "audience")
    from app.services import topic_store
    monkeypatch.setattr(topic_store, "_saved_topics_file", lambda: str(tmp_path / "topics.json"))
    monkeypatch.setattr(A, "_own_channel_ids", lambda brand: ["UCown"])

    videos = {
        "UCown": [{"id": "own1", "title": "Neelkamal Haveli", "channel": "Raat3Baje", "channel_id": "UCown", "views": 42, "duration": 900}],
        "https://www.youtube.com/@khoonimonday": [
            {"id": "km1", "title": "Munjya Real Story", "channel": "Khooni Monday", "channel_id": "UCkm", "views": 10_000_000, "duration": 677}],
    }
    monkeypatch.setattr(A, "channel_uploads", lambda ch, limit: list(videos.get(ch, [])))
    monkeypatch.setattr(A, "search_videos", lambda q, limit: [
        {"id": "sp1", "title": "Kadambari Horror Story", "channel": "Scary Pumpkin", "channel_id": "UCsp", "views": 1_400_000, "duration": 998},
        {"id": "short", "title": "a short", "channel": "x", "channel_id": "UCx", "views": 9_000_000, "duration": 40},
        {"id": "own1", "title": "dupe of own", "channel": "Raat3Baje", "channel_id": "UCown", "views": 1, "duration": 900},
    ])
    comments = {
        "km1": [{"text": "Bhangarh fort ki kahani banao please", "likes": 120}, {"text": "part 2 kab aayega?", "likes": 40},
                {"text": "Bhangarh fort pe video chahiye", "likes": 15}, {"text": "nice", "likes": 3}],
        "sp1": [{"text": "Bhangarh fort ka raaz batao", "likes": 60}, {"text": "mere gaon mein ek kuan hai jahan raat ko awaaz aati hai", "likes": 200},
                {"text": "audio bahut low hai", "likes": 9}],
        "own1": [{"text": "Woowwwww", "likes": 0}],
    }
    monkeypatch.setattr(A, "video_comments", lambda vid, limit: {
        "video_id": vid, "title": "", "channel": "", "views": 0, "comment_count": len(comments.get(vid, [])),
        "comments": [{**c, "reply": False} for c in comments.get(vid, []) if len(c["text"]) >= A.MIN_CHARS or "?" in c["text"]],
    })

    calls: List[Dict[str, Any]] = []

    def fake_agent_json(agent: str, task: Dict[str, Any]):
        calls.append(task)
        if "findings" in task.get("answer_format", {}):
            rows = task["comments"]
            by_text = {r["text"]: r["i"] for r in rows}
            bhangarh = [i for t, i in by_text.items() if "bhangarh" in t.lower()]
            out = []
            if bhangarh:
                out.append({"topic": "Bhangarh fort haunted story", "kind": "story_request", "why": "they want the fort",
                            "comment_ids": bhangarh, "quotes": ["Bhangarh fort ki kahani banao"]})
            kuan = [i for t, i in by_text.items() if "kuan" in t]
            if kuan:
                out.append({"topic": "Village well where voices come at night", "kind": "own_encounter",
                            "why": "a viewer's own encounter", "comment_ids": kuan, "quotes": []})
            audio = [i for t, i in by_text.items() if "audio" in t]
            if audio:
                out.append({"topic": "Audio too low", "kind": "complaint", "why": "", "comment_ids": audio, "quotes": []})
            out.append({"topic": "ghost", "kind": "story_request", "why": "", "comment_ids": [], "quotes": []})  # no evidence
            return {"findings": out}
        return {"groups": []}

    import app.services.shorts_desk as sd
    monkeypatch.setattr(sd, "_agent_json", fake_agent_json)
    return {"calls": calls}


def _mined(topic_store):
    """The rows the desk made (an empty store is seeded with sample topics)."""
    return [t for t in topic_store.load_topics() if t.get("source_type") == "viewer_requests"]


def test_sources_have_defaults_and_can_be_edited(desk):
    src = A.sources("Raat3Baje")
    assert src["own"] == ["UCown"] and src["queries"] == A.DEFAULT_QUERIES["Raat3Baje"]
    src = A.set_sources("Raat3Baje", {"queries": ["sacchi bhootiya kahani"], "competitors": ["@khoonimonday", {"url": "UCabc", "name": "X"}]})
    assert src["queries"] == ["sacchi bhootiya kahani"]
    assert src["competitors"][0]["url"] == "https://www.youtube.com/@khoonimonday"
    assert src["competitors"][1]["url"] == "https://www.youtube.com/channel/UCabc" and src["competitors"][1]["name"] == "X"


def test_a_run_reads_the_niche_and_ranks_what_viewers_ask_for(desk):
    A.set_sources("Raat3Baje", {"competitors": ["@khoonimonday"]})
    said: List[str] = []
    rec = A.run("Raat3Baje", max_videos=5, per_video=50, progress=said.append)
    ids = [v["id"] for v in rec["videos"]]
    assert ids == ["own1", "km1", "sp1"], "own first, competitors next, search by views; no Shorts, no duplicates"
    assert rec["comments_read"] == 6, "'nice' and 'Woowwwww' are not comments worth reading"
    topics = [(f["topic"], f["kind"], f["mentions"]) for f in rec["findings"]]
    assert topics[0] == ("Bhangarh fort haunted story", "story_request", 3)
    top = rec["findings"][0]
    assert top["likes"] == 195 and sorted(v["id"] for v in top["videos"]) == ["km1", "sp1"]
    assert top["videos"][0]["channel"] in ("Khooni Monday", "Scary Pumpkin")
    assert all(f["mentions"] > 0 for f in rec["findings"]), "a finding without a comment is dropped"
    assert any(f["kind"] == "own_encounter" and f["quotes"] for f in rec["findings"]), "quotes fall back to the comments"
    assert A.latest("Raat3Baje")["ran_at"] == rec["ran_at"]
    assert A.history("Raat3Baje")[0]["findings"] == len(rec["findings"])
    assert any("Searching YouTube" in s for s in said) and said[-1].startswith("Done:")


def test_a_finding_becomes_a_vault_row_with_its_evidence(desk):
    from app.services import topic_store
    A.set_sources("Raat3Baje", {"competitors": ["@khoonimonday"]})
    rec = A.run("Raat3Baje", max_videos=5, per_video=50)
    row = A.save_to_vault("Raat3Baje", rec["findings"][0], added_by="user")
    assert row["source_type"] == "viewer_requests" and row["channel"] == "Raat3Baje"
    assert row["evidence"]["mentions"] == 3 and len(row["evidence"]["videos"]) == 2
    assert "Asked by 3 viewers" in row["notes"] and "Khooni Monday" in row["notes"]
    assert row["sources_used"][0].startswith("https://www.youtube.com/watch?v=")
    assert 1 <= row["viral_potential"] <= 10
    assert A.latest("Raat3Baje")["findings"][0]["saved_topic_id"] == row["id"]
    assert topic_store.find_topics("Bhangarh")[0]["id"] == row["id"]
    # Saving it again updates the same row.
    again = A.save_to_vault("Raat3Baje", rec["findings"][0])
    assert again["id"] == row["id"] and len(_mined(topic_store)) == 1


def test_the_nightly_pass_saves_the_top_requests_only(desk):
    from app.services import topic_store
    A.set_settings({"auto_save_top": 2})
    A.set_sources("Raat3Baje", {"competitors": ["@khoonimonday"]})
    rec = A.run_all(brands=["Raat3Baje"])
    assert rec["done"][0]["brand"] == "Raat3Baje" and not rec["failed"]
    saved = [s["topic"] for s in rec["saved"]]
    assert saved == ["Bhangarh fort haunted story"], "one mention and complaints never reach the vault by themselves"
    assert A.settings()["last_run"] and A.settings()["last"]["saved"]
    rows = _mined(topic_store)
    assert rows[0]["added_by"] == "nightly"
    # A second pass does not duplicate it.
    rec = A.run_all(brands=["Raat3Baje"])
    assert rec["saved"] == [] and len(_mined(topic_store)) == 1


def test_the_routes(desk):
    from app.main import app
    client = TestClient(app)
    assert client.get("/api/audience/sources?channel=Raat3Baje").json()["own"] == ["UCown"]
    body = client.post("/api/audience/sources", json={"channel": "Raat3Baje", "queries": ["q1"]}).json()
    assert body["queries"] == ["q1"]
    assert client.get("/api/audience/latest?channel=Raat3Baje").json()["findings"] == []
    assert client.get("/api/audience/jobs/nope").status_code == 404
    assert client.post("/api/audience/settings", json={"enabled": False}).json()["enabled"] is False
    assert client.post("/api/audience/save", json={"channel": "Raat3Baje", "finding": {"topic": ""}}).status_code == 400
