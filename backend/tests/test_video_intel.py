"""
Video intelligence (v6, S1): link parsing, metrics from a fixture, the
model read with a JSON reply, the metrics-only fallback when no model answers,
and the route's error codes. No network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import video_intel as vi

client = TestClient(app)

FIXTURE = {
    "id": "abcdefghijk",
    "title": "Why Nobody Talks About Bhangarh Fort",
    "channel": "Some Creator",
    "channel_id": "UC123",
    "channel_url": "https://www.youtube.com/channel/UC123",
    "uploader_id": "@somecreator",
    "upload_date": "20260801",
    "duration": 600,
    "view_count": 500000,
    "like_count": 25000,
    "comment_count": 2500,
    "channel_follower_count": 100000,
    "tags": ["bhangarh", "haunted"],
    "categories": ["Entertainment"],
    "thumbnail": "https://i.ytimg.com/vi/abcdefghijk/maxresdefault.jpg",
    "heatmap": [{"start_time": 0, "end_time": 6, "value": 1.0}, {"start_time": 300, "end_time": 306, "value": 0.9}, {"start_time": 12, "end_time": 18, "value": 0.2}],
    "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 120, "title": "The legend"}],
    "description": "A story.",
}
RECENT = [{"id": f"v{i}", "title": f"Video {i}", "view_count": 50000 * (i + 1), "duration": 500} for i in range(5)]
TRANSCRIPT = {"language": "en", "auto": False, "segments": [
    {"t": 0.5, "text": "In 1573 a curse was placed on this fort."},
    {"t": 20.0, "text": "And nobody who stayed the night came back."},
    {"t": 300.0, "text": "This is the room where it happened."},
]}


def test_parse_target_recognises_videos_and_channels():
    assert vi.parse_target("https://www.youtube.com/watch?v=abcdefghijk") == ("video", "abcdefghijk")
    assert vi.parse_target("https://youtu.be/abcdefghijk?t=5") == ("video", "abcdefghijk")
    assert vi.parse_target("https://www.youtube.com/shorts/abcdefghijk") == ("video", "abcdefghijk")
    assert vi.parse_target("https://www.youtube.com/@somecreator/videos") == ("channel", "https://www.youtube.com/@somecreator")
    assert vi.parse_target("https://www.youtube.com/channel/UC123") == ("channel", "https://www.youtube.com/channel/UC123")
    with pytest.raises(ValueError):
        vi.parse_target("https://example.com/not-youtube")


def test_metrics_measure_against_the_channel_baseline():
    m = vi.compute_metrics(FIXTURE, RECENT, TRANSCRIPT)
    assert m["recent_median_views"] == 150000 and m["outlier_multiple"] == 3.33
    assert m["rank_in_recent"] == 1 and m["videos_sampled"] == 5
    assert m["like_rate_pct"] == 5.0 and m["comments_per_1k_views"] == 5.0
    assert m["views_to_subs"] == 5.0
    assert m["hook_transcript"].startswith("In 1573")
    assert m["peaks"][0]["t"] == 0 and "1573" in m["peaks"][0]["transcript"]
    assert m["peaks"][1]["t"] == 300 and "room" in m["peaks"][1]["transcript"]
    assert m["title"]["is_question"] is True and "nobody" in m["title"]["curiosity_words"]
    assert m["chapters"][1]["title"] == "The legend"


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(vi, "STORE_DIR", str(tmp_path / "vi"))
    monkeypatch.setattr(vi, "fetch_video", lambda video_id: dict(FIXTURE))
    monkeypatch.setattr(vi, "fetch_transcript", lambda info: TRANSCRIPT)
    monkeypatch.setattr(vi, "fetch_channel_videos", lambda url, limit=30: list(RECENT))
    monkeypatch.setattr(vi, "_guide", lambda channel: "Beyond3Baje: calm, documentary, Hindi narration.")


class FakeLLM:
    def __init__(self, reply, simulated=False):
        self.reply = reply
        self.last_response_simulated = simulated
        self.seen = []

    def generate_chat(self, system_prompt, messages, require_json=False, **kwargs):
        self.seen.append((system_prompt, messages))
        return self.reply


def test_analysis_uses_the_model_reply_and_the_brand_guide(offline, monkeypatch):
    reply = json.dumps({
        "why_it_works": [{"factor": "Curse hook", "evidence": "opens with a date and a curse", "weight": 5}],
        "hook": {"first_line": "In 1573...", "technique": "specific date + threat", "what_it_promises": "a true curse"},
        "structure": [{"t": 0, "beat": "curse"}],
        "packaging": {"title_pattern": "Why Nobody...", "thumbnail_read": "fort at dusk", "promise": "hidden truth"},
        "audience": {"who": "mystery fans", "why_they_click": "curiosity", "why_they_stay": "escalation"},
        "blueprint": {"working_titles": ["Why Nobody Talks About Kuldhara"], "hook_script": "...", "outline": [], "thumbnail_direction": "", "tags": [], "target_length_minutes": 10, "cta": "", "differentiator": "local sources"},
        "do_not_copy": ["the jump scares"],
    })
    fake = FakeLLM("```json\n" + reply + "\n```")
    monkeypatch.setattr(vi, "_llm_service", lambda: fake)
    result = vi.analyze("https://www.youtube.com/watch?v=abcdefghijk", channel="Beyond3Baje")
    assert result["kind"] == "video" and result["simulated"] is False
    assert result["analysis"]["why_it_works"][0]["factor"] == "Curse hook"
    assert result["analysis"]["blueprint"]["working_titles"] == ["Why Nobody Talks About Kuldhara"]
    system_prompt, messages = fake.seen[0]
    assert "Beyond3Baje" in system_prompt and "documentary" in system_prompt
    assert "outlier_multiple" in messages[0]["content"]
    # cached on the second call: no second model call
    again = vi.analyze("https://www.youtube.com/watch?v=abcdefghijk", channel="Beyond3Baje")
    assert again["generated_at"] == result["generated_at"] and len(fake.seen) == 1
    assert vi.recent_analyses()[0]["id"] == "abcdefghijk"


def test_no_model_means_a_labelled_metrics_only_read(offline, monkeypatch):
    monkeypatch.setattr(vi, "_llm_service", lambda: FakeLLM("simulated text", simulated=True))
    result = vi.analyze("https://youtu.be/abcdefghijk")
    assert result["simulated"] is True
    factors = [f["factor"] for f in result["analysis"]["why_it_works"]]
    assert "Outlier on its own channel" in factors and "Rewatched moment" in factors
    assert result["analysis"]["blueprint"]["working_titles"] == []
    assert "No model" in result["analysis"]["note"]


def test_channel_analysis_finds_outliers(offline, monkeypatch):
    monkeypatch.setattr(vi, "_llm_service", lambda: FakeLLM(json.dumps({
        "what_works": [{"factor": "Long-form legends", "evidence": "Video 4 leads", "weight": 4}],
        "outlier_pattern": "place names", "packaging": {"title_formula": "X of Y", "length": "8-10 min", "cadence": "weekly"},
        "borrow": [{"idea": "local legends", "for_us": "Rajasthan forts", "working_title": "The fort that ate a village"}], "avoid": [],
    })))
    result = vi.analyze("https://www.youtube.com/@somecreator")
    assert result["kind"] == "channel" and result["metrics"]["median_views"] == 150000
    assert result["metrics"]["outliers"][0]["title"] == "Video 4" and result["metrics"]["outliers"][0]["outlier_multiple"] == 1.67
    assert result["analysis"]["borrow"][0]["working_title"].startswith("The fort")


def test_routes_report_bad_links_and_fetch_failures(offline, monkeypatch):
    assert client.post("/api/video-intel/analyze", json={"url": "https://example.com"}).status_code == 400
    monkeypatch.setattr(vi, "fetch_video", lambda video_id: (_ for _ in ()).throw(vi.VideoFetchError("Private video")))
    res = client.post("/api/video-intel/analyze", json={"url": "https://youtu.be/abcdefghijk"})
    assert res.status_code == 502 and "Private video" in res.json()["detail"]
    assert client.get("/api/video-intel/recent").json() == {"items": []}
    assert client.get("/api/video-intel/nothing").status_code == 404
