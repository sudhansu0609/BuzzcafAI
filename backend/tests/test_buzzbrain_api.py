"""
BuzzBrain snapshots (roadmap v5, 5.1): stored, indexed, ownership decided
only by channel id or a brand name, history answered per video.
"""

import json
import os

import pytest
from fastapi.testclient import TestClient

from app.api import buzzbrain_api
from app.main import app
from app.services import events


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(buzzbrain_api, "BUZZBRAIN_DIR", str(tmp_path))
    monkeypatch.setattr(buzzbrain_api, "SNAPSHOTS_PATH", str(tmp_path / "snapshots.jsonl"))
    monkeypatch.setattr(buzzbrain_api, "INDEX_PATH", str(tmp_path / "index.json"))
    return TestClient(app)


@pytest.fixture
def recorded(monkeypatch):
    seen = []
    monkeypatch.setattr(events.bus, "publish", lambda kind, payload=None: seen.append((kind, payload)))
    return seen


def _snapshot(video_id="abc123", channel_name="Some Creator", channel_id="UCxyz", views=1000, vph=40):
    return {
        "captured_at": "2026-09-06T10:00:00+00:00",
        "reason": "scrape",
        "videoMeta": {
            "videoId": video_id, "title": f"Video {video_id}", "channelName": channel_name,
            "channelId": channel_id, "viewCount": views, "likeCount": 50, "commentCount": 5,
            "subscriberCount": 12000, "durationSeconds": 600, "tags": ["a", "b"], "isShorts": False,
        },
        "metrics": {"vph": vph, "likeRatio": 5.0, "detectedNiche": "True Crime", "estimatedRpmMin": 2, "estimatedRpmMax": 4},
        "keywords": {"seoScore": 70, "titleHookScore": 60},
    }


def test_snapshot_is_stored_indexed_and_published(client, recorded):
    res = client.post("/api/buzzbrain/snapshot", json=_snapshot())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "stored" and body["video_id"] == "abc123"
    assert os.path.exists(buzzbrain_api.SNAPSHOTS_PATH)
    assert any(kind == "buzzbrain_snapshot" for kind, _ in recorded)

    latest = client.get("/api/buzzbrain/latest").json()
    assert latest["count"] == 1
    assert latest["videos"][0]["video_id"] == "abc123"
    assert latest["videos"][0]["views"] == 1000


def test_ownership_is_never_assumed(client):
    stranger = client.post("/api/buzzbrain/snapshot", json=_snapshot(video_id="s1", channel_name="Random Vlogs")).json()
    assert stranger["mine"] is False
    brand = client.post("/api/buzzbrain/snapshot", json=_snapshot(video_id="b1", channel_name="Beyond3Baje", channel_id="")).json()
    assert brand["mine"] is True
    channels = client.get("/api/buzzbrain/channels").json()["channels"]
    mine = [c for c in channels if c["mine"]]
    assert [c["name"] for c in mine] == ["Beyond3Baje"]
    assert channels[0]["mine"] is True  # owner's channels sort first


def test_owner_channel_ids_setting_marks_mine(client, monkeypatch):
    monkeypatch.setattr(buzzbrain_api, "_owner_ids", lambda: ["UC-owner"])
    res = client.post("/api/buzzbrain/snapshot", json=_snapshot(video_id="o1", channel_name="Unbranded", channel_id="UC-owner")).json()
    assert res["mine"] is True
    only_mine = client.get("/api/buzzbrain/latest?mine=true").json()["videos"]
    assert [v["video_id"] for v in only_mine] == ["o1"]


def test_history_accumulates_per_video(client):
    for views, vph in ((100, 10), (250, 25), (900, 60)):
        client.post("/api/buzzbrain/snapshot", json=_snapshot(video_id="h1", views=views, vph=vph))
    res = client.get("/api/buzzbrain/videos/h1")
    assert res.status_code == 200
    body = res.json()
    assert body["latest"]["views"] == 900
    assert [h["views"] for h in body["history"]] == [100, 250, 900]
    assert client.get("/api/buzzbrain/videos/nope").status_code == 404


def test_snapshot_without_video_id_is_rejected(client):
    bad = _snapshot()
    bad["videoMeta"]["videoId"] = ""
    assert client.post("/api/buzzbrain/snapshot", json=bad).status_code == 422


def test_state_reports_buzzbrain_summary(client):
    client.post("/api/buzzbrain/snapshot", json=_snapshot(video_id="z1"))
    with open(buzzbrain_api.INDEX_PATH, "r", encoding="utf-8") as handle:
        index = json.load(handle)
    assert index["last_snapshot_at"] and index["videos"]["z1"]["history"] == 1
