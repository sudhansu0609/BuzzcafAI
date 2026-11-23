"""
Channel profiles and the layered settings resolution
(base -> density preset -> channel profile -> project -> request) in
`integrations/buzzedit_settings.py`, plus the `/api/channel_profiles` and
`/api/projects/{id}/video_settings` routes in `app/api/produce_api.py`.
"""

import shutil

import pytest
from fastapi.testclient import TestClient

from app.api import produce_api
from app.main import app
from core.models.project import Project
from integrations import buzzedit_settings as settings_mod


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def profiles_file(tmp_path, monkeypatch):
    path = tmp_path / "channel_profiles.json"
    monkeypatch.setattr(settings_mod, "CHANNEL_PROFILES_PATH", str(path))
    return path


@pytest.fixture
def project():
    # A brand with no seeded channel profile, so the effective settings start
    # from the plain base defaults (general/balanced) before any PUT.
    p = Project(id="vs_test_proj", name="Video Settings Probe", brand="UnknownBrandXYZ", workflow_name="life3baje_video")
    p.save()
    yield p
    shutil.rmtree(p.get_project_dir(), ignore_errors=True)


# ------------------------------------------------------------- resolution


def test_base_settings_are_general_and_balanced(profiles_file):
    settings = settings_mod.settings_for_brand("SomeUnknownBrand")
    assert settings["genre"] == "general"
    assert settings["genre_secondary"] is None
    assert settings["density"] == "balanced"
    # Coverage is the video + images mix (70% + 20% by default, 2026-10-03);
    # the density still sets the rest of its preset.
    assert settings["target_coverage"] == 0.85  # 30% clips + 55% stills of the running time (MIX_DEFAULTS)
    assert settings["zoom_depth"] == settings_mod._DENSITY_PRESETS["balanced"]["zoom_depth"]


def test_channel_profile_overrides_base_genre_and_density(profiles_file):
    settings_mod.set_channel_profile("life3baje", {
        "genre": "vlog", "genre_secondary": "motivational", "density": "busy", "voice_preset": "studio_mic",
    })
    settings = settings_mod.settings_for_brand("Life3Baje")
    assert settings["genre"] == "vlog"
    assert settings["genre_secondary"] == "motivational"
    assert settings["density"] == "busy"
    assert settings["target_coverage"] == 0.85
    assert settings["punch_rate_per_minute"] == settings_mod._DENSITY_PRESETS["busy"]["punch_rate_per_minute"]


def test_project_video_settings_override_the_channel_profile(profiles_file):
    settings_mod.set_channel_profile("life3baje", {
        "genre": "vlog", "genre_secondary": "motivational", "density": "busy", "voice_preset": "studio_mic",
    })

    class _Proj:
        brand = "Life3Baje"
        metadata = {"video_settings": {"density": "calm", "voice_preset": "podcast"}}

    settings, sources = settings_mod.resolve_settings("Life3Baje", None, _Proj())
    assert settings["density"] == "calm"
    assert settings["target_coverage"] == settings_mod._DENSITY_PRESETS["calm"]["target_coverage"]
    assert settings["voice_preset"] == "podcast"
    # Untouched by the project layer: still the channel profile's genre.
    assert settings["genre"] == "vlog"
    assert sources["density"] == "project"
    assert sources["voice_preset"] == "project"
    assert sources["genre"] == "channel_profile"


def test_request_override_wins_over_everything_else(profiles_file):
    settings_mod.set_channel_profile("life3baje", {
        "genre": "vlog", "genre_secondary": "motivational", "density": "busy", "voice_preset": "studio_mic",
    })

    class _Proj:
        brand = "Life3Baje"
        metadata = {"video_settings": {"density": "calm"}}

    settings, sources = settings_mod.resolve_settings("Life3Baje", {"genre": "comedy", "target_coverage": 0.77}, _Proj())
    assert settings["genre"] == "comedy"
    assert settings["target_coverage"] == 0.77
    # The request only set density implicitly via genre; the project's density
    # layer still applied before the request layer, so "calm" numbers stood
    # until the request's explicit target_coverage overrode just that field.
    assert settings["density"] == "calm"
    assert sources["genre"] == "request"
    assert sources["target_coverage"] == "request"


def test_an_explicit_field_beside_a_density_change_wins_in_the_same_layer(profiles_file):
    settings = settings_mod.settings_for_brand("SomeUnknownBrand", {"density": "max", "target_coverage": 0.5})
    assert settings["density"] == "max"
    assert settings["target_coverage"] == 0.5  # not max's 0.80
    assert settings["video_broll_share"] == settings_mod._DENSITY_PRESETS["max"]["video_broll_share"]


# --------------------------------------------------------------- validation


def test_set_channel_profile_rejects_unknown_genre(profiles_file):
    with pytest.raises(settings_mod.InvalidChannelProfile):
        settings_mod.set_channel_profile("life3baje", {"genre": "not_a_genre", "density": "busy"})


def test_set_channel_profile_rejects_unknown_density(profiles_file):
    with pytest.raises(settings_mod.InvalidChannelProfile):
        settings_mod.set_channel_profile("life3baje", {"genre": "vlog", "density": "medium"})


def test_unknown_brand_falls_back_to_general_balanced_studio_mic(profiles_file):
    profile = settings_mod.get_channel_profile("SomeBrandNobodyConfigured")
    assert profile == {"genre": "general", "genre_secondary": None, "density": "balanced", "voice_preset": "studio_mic"}


# ------------------------------------------------------------------ routes


def test_get_and_put_channel_profiles(client, profiles_file):
    resp = client.put("/api/channel_profiles/life3baje", json={
        "genre": "vlog", "genre_secondary": "motivational", "density": "busy", "voice_preset": "studio_mic",
    })
    assert resp.status_code == 200

    resp = client.get("/api/channel_profiles")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profiles"]["life3baje"]["genre"] == "vlog"
    assert "vlog" in body["genres"]
    assert "busy" in body["densities"]


def test_put_channel_profile_rejects_bad_density(client, profiles_file):
    resp = client.put("/api/channel_profiles/life3baje", json={"genre": "vlog", "density": "extreme"})
    assert resp.status_code == 400


def test_get_and_put_project_video_settings(client, profiles_file, project):
    resp = client.get(f"/api/projects/{project.id}/video_settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_settings"] == {}
    assert body["effective"]["genre"] == "general"  # no channel profile saved yet

    resp = client.put(f"/api/projects/{project.id}/video_settings", json={"genre": "vlog", "density": "busy"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["video_settings"] == {"genre": "vlog", "density": "busy"}
    assert body["effective"]["genre"] == "vlog"
    assert body["sources"]["genre"] == "project"

    # Reload confirms it persisted to project.metadata.
    reloaded = Project.load(project.id)
    assert reloaded.metadata["video_settings"]["genre"] == "vlog"


def test_put_project_video_settings_rejects_bad_genre(client, profiles_file, project):
    resp = client.put(f"/api/projects/{project.id}/video_settings", json={"genre": "not_real"})
    assert resp.status_code == 400


def test_put_project_video_settings_null_clears_a_field(client, profiles_file, project):
    client.put(f"/api/projects/{project.id}/video_settings", json={"genre": "vlog", "voice_preset": "podcast"})
    resp = client.put(f"/api/projects/{project.id}/video_settings", json={"voice_preset": None})
    assert resp.status_code == 200
    assert resp.json()["video_settings"] == {"genre": "vlog"}


def test_put_project_video_settings_carries_motion_switches(client, profiles_file, project):
    resp = client.put(f"/api/projects/{project.id}/video_settings",
                      json={"motion_graphics": False, "parallax_share": 0})
    assert resp.status_code == 200
    eff = resp.json()["effective"]
    assert eff["motion_graphics"] is False and eff["parallax_share"] == 0
    assert client.put(f"/api/projects/{project.id}/video_settings",
                      json={"parallax_share": 1.5}).status_code == 400


# ---------------------------------------------------------- precut default


def test_precut_defaults_to_false_when_unset(project):
    assert produce_api._resolve_precut(None, project) is False


def test_precut_request_value_wins(project):
    assert produce_api._resolve_precut(True, project) is True


def test_precut_falls_back_to_the_saved_project_setting(project):
    project.metadata["video_settings"] = {"precut": True}
    assert produce_api._resolve_precut(None, project) is True


# ------------------------------------------- Studio-wide Pixabay switch
#
# Settings -> "Use Pixabay stock footage" seeds `allow_free_stock` for every
# render, one layer above base so a project can still turn it off.


def test_pixabay_switch_turns_the_stock_fallback_on_by_default(profiles_file, monkeypatch):
    import integrations.llm as llm_mod
    monkeypatch.setattr(llm_mod, "load_config", lambda: {"pixabay_enabled": True, "pixabay_api_key": "k"})
    settings, sources = settings_mod.resolve_settings("SomeUnknownBrand")
    assert settings["allow_free_stock"] is True
    assert sources["allow_free_stock"] == "studio_settings"


def test_pixabay_switch_needs_a_key(profiles_file, monkeypatch):
    import integrations.llm as llm_mod
    monkeypatch.setattr(llm_mod, "load_config", lambda: {"pixabay_enabled": True, "pixabay_api_key": ""})
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    settings, sources = settings_mod.resolve_settings("SomeUnknownBrand")
    assert settings["allow_free_stock"] is False
    assert sources["allow_free_stock"] == "base"


def test_a_project_can_still_turn_the_stock_fallback_off(profiles_file, monkeypatch, project):
    import integrations.llm as llm_mod
    monkeypatch.setattr(llm_mod, "load_config", lambda: {"pixabay_enabled": True, "pixabay_api_key": "k"})
    project.metadata["video_settings"] = {"allow_free_stock": False}
    settings, sources = settings_mod.resolve_settings(project.brand, None, project)
    assert settings["allow_free_stock"] is False
    assert sources["allow_free_stock"] == "project"


def test_the_studio_stock_switch_does_not_reach_horror(monkeypatch):
    """Keyword stock photos never fit fiction horror; the Studio-wide switch
    stays on for other genres, and a project/request can still ask for it."""
    from integrations import buzzedit_settings as b
    monkeypatch.setattr(b, "_studio_settings_layer", lambda: {"allow_free_stock": True})
    horror, src = b.resolve_settings("Raat3Baje")
    assert horror["allow_free_stock"] is False and src["allow_free_stock"] == "genre_rule"
    documentary, _ = b.resolve_settings("Beyond3Baje")
    assert documentary["allow_free_stock"] is True
    asked, _ = b.resolve_settings("Raat3Baje", {"allow_free_stock": True})
    assert asked["allow_free_stock"] is True


def test_picked_music_tracks_are_saved_cleaned_and_reach_the_render(client, profiles_file, project):
    url = f"/api/projects/{project.id}/video_settings"
    resp = client.put(url, json={"music_tracks_mode": "sequence", "music_tracks": [
        {"file": r"uploads\rain.flac", "volume_db": -18, "duck": True},
        {"file": "uploads/rain.flac", "volume_db": -6},          # duplicate: dropped
        {"file": "../../secrets.wav"},                           # outside the library: dropped
        {"file": "general/piano.wav"}]})
    assert resp.status_code == 200
    saved = Project.load(project.id).metadata["video_settings"]
    assert saved["music_tracks"] == [
        {"file": "uploads/rain.flac", "volume_db": -18.0, "duck": True},
        {"file": "general/piano.wav", "volume_db": -20.0, "duck": False}]
    effective = client.get(url).json()["effective"]
    assert effective["music_tracks_mode"] == "sequence" and len(effective["music_tracks"]) == 2

    assert client.put(url, json={"music_tracks_mode": "shuffle"}).status_code == 400
    assert client.put(url, json={"music_tracks": [{"file": "a.wav", "volume_db": 20}]}).status_code == 422
    # null clears the picks: back to the automatic music.
    client.put(url, json={"music_tracks": None})
    assert client.get(url).json()["effective"]["music_tracks"] == []


def test_the_planner_writes_no_music_cues_over_picked_tracks(profiles_file, project):
    from integrations import music_catalog
    project.metadata["video_settings"] = {"music_tracks": [{"file": "uploads/rain.flac", "volume_db": -20}]}
    project.save()
    assert "plan no `music_cue` beats" in music_catalog.planner_direction(Project.load(project.id))


def test_the_clip_generation_mode_is_pushed_to_buzzedit(monkeypatch):
    sent = []
    monkeypatch.setattr(produce_api.BuzzEditClient, "set_clip_generation",
                        lambda self, mode: sent.append(mode) or {"mode": mode})
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {"clip_generation_mode": "hq"})
    assert produce_api.sync_clip_generation_to_buzzedit() == {"mode": "hq"}
    monkeypatch.setattr(produce_api, "load_llm_config", lambda: {})
    produce_api.sync_clip_generation_to_buzzedit()
    assert sent == ["hq", "classic"]

    def down(self, mode):
        raise produce_api.BuzzEditUnavailable("not running")

    monkeypatch.setattr(produce_api.BuzzEditClient, "set_clip_generation", down)
    assert produce_api.sync_clip_generation_to_buzzedit() is None
