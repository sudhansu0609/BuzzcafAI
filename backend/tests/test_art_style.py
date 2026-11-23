"""The art style (2026-10-21): real / explainer / stick_figure / cartoon,
picked per channel, project, request or vault topic, carried into every
picture prompt, the planner's instructions, the cast sheet and BuzzEdit."""
import pytest

from integrations import art_style as A
from integrations import buzzedit_settings as S
from integrations import story_visuals as V


@pytest.fixture
def profiles_file(tmp_path, monkeypatch):
    path = tmp_path / "channel_profiles.json"
    monkeypatch.setattr(S, "CHANNEL_PROFILES_PATH", str(path))
    return path


class _Proj:
    def __init__(self, brand, **video_settings):
        self.brand = brand
        self.metadata = {"video_settings": video_settings} if video_settings else {}


def test_every_style_is_known_and_real_is_the_default():
    assert A.ART_STYLES == ("real", "explainer", "stick_figure", "cartoon", "painterly", "mixed",
                            "mixed_quirky", "stick_world", "illustrated")
    assert A.normalise(None) == "real" and A.normalise("whiteboard") == "stick_figure"
    assert A.normalise("Stick Figure") == "stick_figure" and A.normalise("nonsense") == "real"
    assert A.apply_look("a man on a raft", "real") == "a man on a raft"
    stick = A.apply_look("a man on a raft.", "stick_figure")
    # The stick-figure medium leads the prompt (the scene words otherwise win
    # and Z-Image photographs a whiteboard, 2026-10-22) and its look ends it.
    assert stick.startswith("A crude whiteboard doodle") and "a man on a raft, " in stick
    assert "black marker" in stick
    assert A.apply_look("a man on a raft", "explainer").startswith("a man on a raft, ")
    assert A.apply_look(stick, "stick_figure") == stick, "the look is appended once"


def test_the_channel_profile_keeps_an_art_style_and_resolution_layers_it(profiles_file):
    S.set_channel_profile("beyond3baje", {"genre": "documentary", "density": "busy",
                                          "voice_preset": "broadcast", "art_style": "explainer"})
    # A PUT without the field keeps it.
    S.set_channel_profile("beyond3baje", {"genre": "documentary", "density": "busy", "voice_preset": "broadcast"})
    assert S.channel_art_style("Beyond3Baje") == "explainer"
    settings, sources = S.resolve_settings("Beyond3Baje", None, None)
    assert settings["art_style"] == "explainer" and sources["art_style"] == "channel_profile"
    # The story channel's cards come back for an explainer, and a project can
    # still switch them off or pick another medium.
    assert settings["visual_style"] == "story"
    assert settings["popups"] is True and settings["stat_callouts"] is True
    assert settings["captions"] is False, "captions stay off: only the short cards return"
    assert sources["popups"] == "art_style"
    settings, sources = S.resolve_settings("Beyond3Baje", None, _Proj("Beyond3Baje", art_style="cartoon"))
    assert settings["art_style"] == "cartoon" and sources["art_style"] == "project"
    assert settings["popups"] is False
    settings, sources = S.resolve_settings("Beyond3Baje", {"art_style": "real"}, _Proj("Beyond3Baje", art_style="cartoon"))
    assert settings["art_style"] == "real" and sources["art_style"] == "request"
    with pytest.raises(S.InvalidChannelProfile):
        S.set_channel_profile("beyond3baje", {"genre": "documentary", "density": "busy", "art_style": "oil"})


def test_a_real_channel_defaults_to_real_and_buzzedit_gets_the_field(profiles_file):
    settings = S.settings_for_brand("Life3Baje", None, None)
    assert settings["art_style"] == "real"
    settings = S.settings_for_brand("Life3Baje", {"art_style": "stick_figure"}, None)
    assert settings["art_style"] == "stick_figure"
    # A drawn style without text on a full channel turns the short cards off.
    settings = S.settings_for_brand("Life3Baje", {"art_style": "cartoon"}, None)
    assert settings["popups"] is False and settings["chapter_titles"] is False


_CAST = {"world": "a grey Atlantic, wet steel, night", "main_character": "Harrison",
         "characters": [{"name": "Harrison", "aliases": ["the cook"], "gender": "male",
                         "look": "a stocky man in his thirties, short hair, orange overalls"}]}


def test_the_script_carries_the_medium_and_no_real_face_on_a_drawing():
    text = ("He heard the water. [broll: Harrison in the dark air pocket, the cook's lamp on the steel wall] "
            "It was 30 metres down. [stat: 30 m] [broll: the ship on the seabed]\n# Day two\nThe air was thin.\n")
    real, stats = V.apply_to_script(text, 0.0, _CAST)
    assert "| face=main" in real and "[stat:" not in real and "# Day two" not in real
    stick, stats = V.apply_to_script(text, 0.0, _CAST, art_style="stick_figure")
    assert "face=main" not in stick, "a stick figure never gets his real face"
    assert stick.count("A crude whiteboard doodle") == 2, "every picture carries the medium"
    assert "[stat: 30 m]" in stick and "# Day two" in stick, "an explainer medium keeps its short text"
    cartoon, _ = V.apply_to_script(text, 1.0, _CAST, art_style="cartoon")
    assert "[stat:" not in cartoon and "# Day two" not in cartoon
    assert "2D cartoon animation" in cartoon and "calm and eerie" not in cartoon, "clips move the medium's way"


def test_a_full_style_script_is_stamped_without_being_timed():
    text = "Hello. [broll: a raft at sea | look=warm] [video: waves rolling] [title: Day 1]"
    out = V.stamp_art_style(text, "explainer")
    assert "[title: Day 1]" in out
    assert out.count("flat vector explainer illustration") == 2
    assert "2D animation" in out and "look=warm" in out.split("[video:")[0]
    assert V.stamp_art_style(text, "real") == text


def test_the_planner_and_the_cast_prompt_know_the_medium():
    section = V.planner_section(0.5, _CAST, art_style="explainer")
    assert "ART STYLE -- EXPLAINER" in section and "**popup**" in section and "**stat_callout**" in section
    assert "No text on screen" not in section
    assert "face" not in section.split("### This video's art style")[0].lower() or "swapped" not in section, \
        "no face-swap instructions in a drawn style"
    cartoon = V.planner_section(0.5, _CAST, art_style="cartoon")
    assert "No text on screen" in cartoon and "ART STYLE -- CARTOON" in cartoon
    assert "ART STYLE" not in V.planner_section(0.5, _CAST)
    assert "stick figure" in A.cast_direction("stick_figure").lower()
    assert A.cast_direction("real") == ""
    assert A.step_direction("real") == "" and "Cartoon" in A.step_direction("cartoon")
    kept = V.filter_beats([{"kind": "broll_image"}, {"kind": "popup"}, {"kind": "map"}], "stick_figure")
    assert [b["kind"] for b in kept] == ["broll_image", "popup"]
    assert [b["kind"] for b in V.filter_beats([{"kind": "broll_image"}, {"kind": "popup"}])] == ["broll_image"]


def test_explainer_and_mixed_favour_kinetic_text_and_a_shape_transition():
    explainer = A.planner_section("explainer")
    assert "`kinetic_text`" in explainer and "shape_wipe, iris or bars" in explainer
    quirky = A.planner_section("mixed_quirky")
    assert "`kinetic_text`" in quirky and "paper_tear or ink" in quirky
    mixed = A.planner_section("mixed")
    assert "`kinetic_text`" in mixed
    # stick_figure keeps short text cards but not this specific favouring.
    assert "`kinetic_text`" not in A.planner_section("stick_figure")


def test_a_vault_topic_s_style_reaches_the_project(tmp_path, monkeypatch):
    from app.services import topic_store
    monkeypatch.setattr(topic_store, "_saved_topics_file", lambda: str(tmp_path / "topics.json"))
    row = topic_store.add_topic({"topic": "Harrison Okene", "channel": "Beyond3Baje", "art_style": "explainer"})
    assert topic_store.update_topic(row["id"], {"art_style": "stick_figure"})["art_style"] == "stick_figure"


def test_painterly_is_a_drawn_style_that_leaves_text_to_the_channel():
    s = A.get("painterly")
    assert A.normalise("watercolour") == "painterly" and A.normalise("oil") == "painterly"
    assert not A.uses_face_swap("painterly") and s.text == "channel"
    assert A.text_cards("painterly") is None
    assert A.apply_look("a lamp in a far window", "painterly") == f"a lamp in a far window, {s.look}"


def test_illustrated_is_a_drawn_style_never_photoreal():
    s = A.get("illustrated")
    assert not A.uses_face_swap("illustrated")
    assert "photorealistic" in s.negative and "anime" in s.negative
    assert A.apply_look("a lamp in a far window", "illustrated") == f"a lamp in a far window, {s.look}"
    assert "ART STYLE -- ILLUSTRATED" in A.planner_section("illustrated")


def test_buzzedit_and_studio_art_style_tables_have_the_same_keys():
    """presentation/art_style.py (BuzzEdit) and integrations/art_style.py
    (this app) keep separate tables on purpose (the two repos share no
    code), but a style added to one and not the other is a bug -- loaded
    standalone, by file path, since the two repos cannot otherwise import
    each other's packages."""
    import importlib.util
    from pathlib import Path

    buzzedit_path = (Path(__file__).resolve().parents[3] / "BuzzEdit" / "backend" /
                     "presentation" / "art_style.py")
    assert buzzedit_path.is_file(), f"BuzzEdit not found at {buzzedit_path}"
    spec = importlib.util.spec_from_file_location("_buzzedit_art_style", buzzedit_path)
    buzzedit_art_style = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(buzzedit_art_style)
    assert set(buzzedit_art_style.STYLES.keys()) == set(A.STYLES.keys())
