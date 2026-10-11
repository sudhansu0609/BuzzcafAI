"""Background music in production: the planner's `music_cue` beats become
`[music: ...]` directives, the planner is told the vocabulary and the
channel's direction, and a project's music settings are validated."""
from types import SimpleNamespace

from integrations import buzzedit_script, effect_catalog, music_catalog


def test_music_cue_beats_become_music_directives():
    script = "Main ne socha. Phir sab badal gaya."
    plan = {"beats": [
        {"anchor": "Main ne socha", "kind": "music_cue", "music": "sad solo violin, 70 bpm"},
        {"anchor": "Phir sab badal gaya", "kind": "music_cue", "music": "off"},
    ]}
    annotated, skipped = buzzedit_script.to_directive_script(script, plan)
    assert skipped == []
    assert annotated == "[music: sad solo violin, 70 bpm] Main ne socha. [music: off] Phir sab badal gaya."


def test_a_music_cue_with_no_description_is_silence_and_brackets_are_escaped():
    annotated, _ = buzzedit_script.to_directive_script(
        "Ek. Do.", {"beats": [{"anchor": "Ek", "kind": "music_cue"},
                              {"anchor": "Do", "kind": "music_cue", "music": "piano [soft]"}]})
    assert "[music: off] Ek." in annotated
    assert "[music: piano (soft)]" in annotated


def test_planner_prompt_teaches_music_cues():
    section = effect_catalog.prompt_section("vlog")
    assert "music_cue" in section and "Music cues" in section
    assert "sad solo violin" in section and "tanpura drone" in section
    assert "music_cue" in effect_catalog.kinds_pipe()


def test_every_channel_guide_has_a_music_direction():
    for brand in ("Life3Baje", "Raat3Baje", "Khayal3Baje", "Beyond3Baje", "Originals"):
        assert music_catalog.channel_music_section(brand).startswith("## Music"), brand


def _project(settings):
    return SimpleNamespace(brand="Life3Baje", metadata={"video_settings": settings})


def test_planner_direction_follows_the_project_settings():
    assert "plan no `music_cue`" in music_catalog.planner_direction(_project({"music": False}))
    assert "plan no `music_cue`" in music_catalog.planner_direction(_project({"music_cues": False}))
    direction = music_catalog.planner_direction(_project({"music_brief": "sad solo violin"}))
    assert "Channel music direction" in direction and '"sad solo violin"' in direction


def test_catalog_engines_match_the_project_settings_engines():
    from app.api.produce_api import MUSIC_ENGINES
    assert tuple(e["name"] for e in music_catalog.FALLBACK_CATALOG["engines"]) == MUSIC_ENGINES
