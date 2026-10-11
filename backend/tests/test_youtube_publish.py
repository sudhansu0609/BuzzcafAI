"""YouTube publishing: reading the SEO manager's package and YouTube's field limits."""
from integrations import youtube_publish as yt

PACKAGE = '''```json
{"status": "success", "agent": "SEOManagerAgent",
 "results": {"seo_package": {
   "titles": ["Basement Ke 14 Rules", "Raat 1:07 Baje Usne Rule Toda"],
   "description": "Raat ke 2 baje, ek basement.\\n\\n#Raat3Baje",
   "tags": ["basement horror story hindi", "raat3baje", "#pishach"],
   "hashtags": ["#Raat3Baje", "#Pishach"]}}}
```'''


def test_a_fenced_nested_seo_package_is_read():
    seo = yt.parse_seo_package(PACKAGE)
    assert seo["titles"] == ["Basement Ke 14 Rules", "Raat 1:07 Baje Usne Rule Toda"]
    assert seo["tags"] == ["basement horror story hindi", "raat3baje", "pishach"]
    assert seo["description"].startswith("Raat ke 2 baje")


def test_hashtags_already_in_the_description_are_not_added_twice():
    seo = yt.parse_seo_package(PACKAGE)
    text = yt.description_with_hashtags(seo["description"], seo["hashtags"])
    assert text.count("#Raat3Baje") == 1 and text.endswith("#Pishach")


def test_prose_without_a_package_gives_none():
    assert yt.parse_seo_package("Here are some ideas for your video.") is None


def test_youtube_limits_are_enforced():
    assert len(yt.clean_title("x" * 150)) == 100
    assert "<" not in yt.clean_title("Rule <4>")
    assert len(yt.clean_description("é" * 4000).encode("utf-8")) <= 5000
    tags = yt.clean_tags([f"tag number {i}" for i in range(100)] + ["Tag Number 1"])
    assert sum(len(t) + 2 for t in tags) + len(tags) - 1 <= 500
    assert len({t.lower() for t in tags}) == len(tags)


def test_upload_offset_comes_from_the_range_header():
    assert yt._offset_from_range("bytes=0-33554431") == 33554432
    assert yt._offset_from_range(None) == 0


def test_brand_is_guessed_from_the_channel_name(monkeypatch):
    monkeypatch.setattr(yt, "brands", lambda: ["Beyond3Baje", "Raat3Baje"])
    assert yt._guess_brand("Raat 3 Baje") == "Raat3Baje"
    assert yt._guess_brand("Someone Else") == ""


def test_a_hand_uploaded_link_is_recorded(monkeypatch):
    from app.api import youtube_api
    saved = {}
    monkeypatch.setattr(youtube_api, "_load", lambda pid: None)
    monkeypatch.setattr(youtube_api, "_save_meta", lambda pid, key, value: saved.update({key: value}))
    for url in ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=1",
                "https://studio.youtube.com/video/dQw4w9WgXcQ/edit"):
        assert youtube_api.project_youtube_manual("p", {"url": url})["video_id"] == "dQw4w9WgXcQ"
    assert saved["youtube"]["url"] == "https://youtu.be/dQw4w9WgXcQ" and saved["youtube"]["manual"]


def test_a_saved_brand_channel_needs_no_lookup(monkeypatch):
    from app.api import youtube_api
    import integrations.llm as llm
    monkeypatch.setattr(youtube_api.yt, "channel_for_brand", lambda brand: None)
    monkeypatch.setattr(llm, "load_config", lambda: {"youtube_upload_channels": {"Raat3Baje": "UCr_FGtc_7VRtvLvraENHraw"}})
    monkeypatch.setattr(youtube_api.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch")))
    assert youtube_api._brand_channel_id("Raat3Baje") == "UCr_FGtc_7VRtvLvraENHraw"


def test_a_connected_channel_wins_over_the_handle(monkeypatch):
    from app.api import youtube_api
    monkeypatch.setattr(youtube_api.yt, "channel_for_brand", lambda brand: "UCconnected")
    assert youtube_api._brand_channel_id("Raat3Baje") == "UCconnected"
