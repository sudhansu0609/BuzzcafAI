"""
Topic demand validation (v12): the YouTube-derived stats, the model verdict with
the brand guide in context, the labelled metrics-only fallback when no model
answers, and the route's wiring. No network.
"""

import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import topic_validation as tv
from app.services import video_intel as vi

try:
    import app.services.deep_research as dr
except ImportError:
    dr = types.ModuleType("app.services.deep_research")
    dr.deep_research = lambda *a, **k: {"results": [], "by_kind": {}, "sources_searched": []}
    dr.build_source_brief = lambda *a, **k: ""
    sys.modules["app.services.deep_research"] = dr

SOURCES = {
    "results": [{"title": "Old news", "url": "http://x", "source": "GDELT", "kind": "news"}],
    "by_kind": {},
    "sources_searched": [{"source": "GDELT", "count": 1}],
}

client = TestClient(app)

YT = [
    {"id": "a" * 11, "title": "The Bhangarh Fort Mystery Explained", "url": "https://youtu.be/a", "view_count": 500000, "duration": 600, "channel": "C1", "upload_date": "20260801"},
    {"id": "b" * 11, "title": "Bhangarh Fort Haunted Truth", "url": "https://youtu.be/b", "view_count": 200000, "duration": 700, "channel": "C2", "upload_date": "20260101"},
    {"id": "c" * 11, "title": "Unrelated cooking video", "url": "https://youtu.be/c", "view_count": 1000, "duration": 300, "channel": "C3", "upload_date": "20200101"},
]
WEB = [{"title": "Bhangarh Fort", "snippet": "A ruined fort in Rajasthan.", "url": "https://en.wikipedia.org/wiki/Bhangarh_Fort", "source": "Wikipedia"}]


class FakeLLM:
    def __init__(self, reply, simulated=False):
        self.reply = reply
        self.last_response_simulated = simulated
        self.seen = []

    def generate_chat(self, system_prompt, messages, require_json=False, **kwargs):
        self.seen.append((system_prompt, messages))
        return self.reply


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(tv, "STORE_DIR", str(tmp_path / "tv"))
    # search_youtube is imported inside validate_topic from video_intel, so patch it there.
    monkeypatch.setattr(vi, "search_youtube", lambda q, limit=12: list(YT))
    monkeypatch.setattr(tv, "_web_interest", lambda q: list(WEB))
    monkeypatch.setattr(tv, "google_trends_interest", lambda q: {"available": True, "avg": 55.0, "latest": 70, "trend": "rising"})
    # Source material goes through deep_research; keep it off the network.
    monkeypatch.setattr(tv, "_source_material", lambda q: dict(SOURCES))
    monkeypatch.setattr(tv, "_guide", lambda channel: "Beyond3Baje: calm documentary, Hindi narration." if channel else "")


def test_youtube_stats_measure_demand_and_saturation():
    stats = tv._youtube_stats(YT, "Bhangarh Fort")
    assert stats["results"] == 3
    assert stats["median_views"] == 200000 and stats["max_views"] == 500000
    # Two of the three titles share >=2 significant words with the query.
    assert stats["title_saturation_pct"] == 67


def test_validate_uses_model_verdict_and_channel_guide(offline, monkeypatch):
    verdict = {
        "demand": {"score": 8, "reason": "high views"},
        "competition": {"level": "medium", "saturation": "some overlap", "note": "room on the angle"},
        "differentiation": {"angle": "local sources", "gap": "no first-person accounts"},
        "audience_fit": "fits the channel",
        "recommendation": "make",
        "confidence": 8,
        "reasons": ["strong demand"],
        "suggested_title": "The Fort That Time Forgot",
        "risks": ["saturation"],
        "top_competitors": [{"title": "The Bhangarh Fort Mystery Explained", "views": 500000, "url": "https://youtu.be/a"}],
        "alternatives": [{"topic": "The Kuldhara Curse", "why": "same audience, less saturated"}],
    }
    fake = FakeLLM("```json\n" + json.dumps(verdict) + "\n```")
    monkeypatch.setattr(tv, "_llm_service", lambda: fake)

    result = tv.validate_topic("Bhangarh Fort", channel="Beyond3Baje")
    assert result["simulated"] is False
    assert result["verdict"]["recommendation"] == "make"
    assert result["verdict"]["alternatives"][0]["topic"] == "The Kuldhara Curse"
    assert result["evidence"]["youtube_stats"]["results"] == 3
    assert result["evidence"]["trends"]["trend"] == "rising"
    # Transparency: the ordered steps and the source-material evidence are recorded.
    assert result["steps"] and result["steps"][0]["source"] == "YouTube search"
    assert result["evidence"]["sources"]["sources_searched"][0]["source"] == "GDELT"
    system_prompt, messages = fake.seen[0]
    assert "Beyond3Baje" in system_prompt and "documentary" in system_prompt
    assert "youtube_stats" in messages[0]["content"]


def test_no_model_gives_a_labelled_metrics_only_verdict(offline, monkeypatch):
    monkeypatch.setattr(tv, "_llm_service", lambda: FakeLLM("simulated", simulated=True))
    result = tv.validate_topic("Bhangarh Fort", channel="Beyond3Baje", force=True)
    assert result["simulated"] is True
    assert result["verdict"]["recommendation"] in {"make", "refine", "skip"}
    assert "note" in result["verdict"]
    # Top competitors are echoed from the YouTube evidence.
    assert result["verdict"]["top_competitors"][0]["url"] == "https://youtu.be/a"


def test_endpoint_wires_through(offline, monkeypatch):
    monkeypatch.setattr(tv, "_llm_service", lambda: FakeLLM("simulated", simulated=True))
    res = client.post("/api/topics/validate", json={"topic": "Bhangarh Fort", "channel": "Beyond3Baje"})
    assert res.status_code == 200
    body = res.json()
    assert body["topic"] == "Bhangarh Fort"
    assert body["verdict"]["recommendation"] in {"make", "refine", "skip"}


def test_endpoint_rejects_an_empty_topic():
    res = client.post("/api/topics/validate", json={"topic": "   "})
    assert res.status_code == 400
