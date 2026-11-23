"""The `mixed` art style (2026-10-27): real + stick figure per shot, plus
maps and charts, for the Beyond3Baje survival stories (MIXED_ART_STYLE_PLAN.md)."""
import re

import pytest

from integrations import art_style as A
from integrations import buzzedit_script as B
from integrations import effect_catalog as E
from integrations import story_visuals as V

CAST = {"world": "a grey Atlantic, wet steel, night", "main_character": "Harrison",
        "characters": [{"name": "Harrison", "aliases": ["the cook"], "gender": "male",
                        "look": "a stocky man in his thirties, short hair, orange overalls"}]}


# --------------------------------------------------------------- art_style

def test_mixed_is_known_and_aliased():
    assert "mixed" in A.ART_STYLES
    assert A.normalise("mix") == "mixed" and A.normalise("combo") == "mixed"
    assert A.normalise("hybrid") == "mixed" and A.normalise("mixed_media") == "mixed"
    assert A.is_mixed("mixed") and A.is_mixed("mix") and not A.is_mixed("real")
    assert A.uses_face_swap("mixed") and A.text_cards("mixed") is True


def test_shot_style_picks_the_medium_per_beat():
    assert A.shot_style("mixed", "stick_figure") == "stick_figure"
    assert A.shot_style("mixed", "real") == "real"
    assert A.shot_style("mixed", None) == "real"
    assert A.shot_style("mixed", "nonsense") == "real"
    # Any other style always draws every shot the same way.
    assert A.shot_style("stick_figure", "real") == "stick_figure"
    assert A.shot_style("real", "stick_figure") == "real"


def test_mixed_planner_section_skips_the_one_look_line():
    section = A.planner_section("mixed")
    assert "ART STYLE -- MIXED" in section
    assert "added per shot from `art`" in section
    assert 'Append to every image_prompt and video_prompt, word for word: ""' not in section


def test_mixed_step_direction_names_every_medium():
    direction = A.step_direction("mixed")
    assert "mixes photoreal story shots, stick-figure explainer drawings, plus maps" in direction


# ------------------------------------------------------------ story_visuals

def test_kept_kinds_add_map_chart_timeline_for_mixed_only():
    assert set(V.kept_directives("mixed")) >= {"map", "chart", "timeline", "broll", "video"}
    assert set(V.kept_beat_kinds("mixed")) >= {"map", "chart", "timeline"}
    assert "map" not in V.kept_directives("real") and "map" not in V.kept_directives("stick_figure")
    kept = V.filter_beats([{"kind": "broll_image"}, {"kind": "map"}, {"kind": "chart"}], "mixed")
    assert [b["kind"] for b in kept] == ["broll_image", "map", "chart"]
    assert V.filter_beats([{"kind": "map"}], "real") == []


def test_planner_section_lists_map_and_chart_for_mixed():
    section = V.planner_section(0.5, CAST, art_style="mixed")
    assert "**map**" in section and "**chart**" in section
    assert "removed before the render" in section
    assert "maps, charts" not in section.split("### This video's art style")[0]
    assert "`art`" in section


def test_picture_real_vs_stick_shot_in_a_mixed_video():
    prompt, options = V._picture(
        "Harrison in the dark air pocket", {"art": "real"}, CAST, infer=False, art_style="mixed")
    assert "Harrison: a stocky man" in prompt and "grey Atlantic" in prompt
    assert "crude" not in prompt.lower()
    assert "art" not in options

    prompt, options = V._picture(
        "a diagram of the air pocket", {"art": "stick_figure"}, CAST, infer=False, art_style="mixed")
    assert prompt.startswith("A crude whiteboard doodle")
    assert "Harrison:" not in prompt and "grey Atlantic" not in prompt, "no realistic continuity on a doodle"
    assert "art" not in options and options.get(V.FACE_OPTION) != "main"


def test_face_mark_only_reaches_the_real_shot():
    out, stats = V.apply_to_script(
        "[broll: Harrison at the rail | art=real] a [broll: a diagram of forces | art=stick_figure] b\n",
        0.0, CAST, art_style="mixed")
    shots = re.findall(r"\[broll: ([^\]]*)\]", out)
    assert "face=main" in shots[0] and "Harrison: a stocky man" in shots[0]
    assert "face=" not in shots[1] and "crude whiteboard doodle" in shots[1].lower()
    assert "art=" not in out, "the art= option must never reach the emitted directive"
    assert stats["main_face"] == 1


def test_untimed_map_and_chart_are_left_exactly_as_written():
    text = ("[broll: Harrison at the rail | art=real] a [map: Mumbai port to Alang, 25 km] b "
            "[chart: bar: Survivors: Day1=25, Day2=10] c\n")
    out, _ = V.apply_to_script(text, 0.0, CAST, art_style="mixed")
    assert "[map: Mumbai port to Alang, 25 km]" in out
    assert "[chart: bar: Survivors: Day1=25, Day2=10]" in out
    # The untimed path never touches a map/chart with the medium's look.
    assert "crude" not in out.split("[map:")[1].split("[chart:")[0].lower()


def _timed_story(n_words):
    words, times = [], []
    for j in range(n_words):
        words.append(f"w{j}")
        times.append(round(j * 0.4, 3))
    return words, times


def test_timed_map_is_never_a_clip_and_never_repeats():
    words, times = _timed_story(80)
    text = ("[broll: Harrison at the rail | art=real] " + " ".join(words[:10]) +
            " [map: Mumbai to Alang, 25 km] " + " ".join(words[10:]) + "\n")
    duration = times[-1] + 0.4
    out, stats = V.apply_to_script(text, 0.8, CAST, word_times=times, duration_s=duration,
                                   image_share=0.2, art_style="mixed")
    assert re.search(r"\[map: Mumbai to Alang, 25 km \| seconds=\d", out)
    assert "[video:" not in out.split("[map:")[1], "a map is never promoted to a clip"
    assert out.count("[map:") == 1, "a long map window is one shot, not a repeat"
    holds = [float(x) for x in re.findall(r"seconds=([\d.]+)", out)]
    assert len(holds) == stats["clips"] + stats["stills"]


def test_plan_timed_shots_still_only_none_matches_default():
    words, times = _timed_story(60)
    anchors = list(range(0, 60, 10))
    duration = times[-1] + 0.4
    default_shots, default_stats = V.plan_timed_shots(anchors, times, duration, 0.5)
    none_shots, none_stats = V.plan_timed_shots(anchors, times, duration, 0.5, still_only=None)
    assert default_shots == none_shots and default_stats == none_stats


def test_stamp_art_style_leaves_real_shots_untouched_and_stamps_stick_shots():
    text = ("[broll: Harrison at the rail | art=real] [video: Harrison walks | art=real] "
            "[broll: a diagram of forces | art=stick_figure | face=no]")
    out = V.stamp_art_style(text, "mixed")
    assert "[broll: Harrison at the rail]" in out, "a real shot is untouched"
    assert "[video: Harrison walks]" in out, "a real clip's prompt is untouched too"
    assert "crude whiteboard doodle" in out
    assert "art=" not in out and "face=no" not in out.split("crude")[0]


# ------------------------------------------------------------- effect_catalog

def test_art_option_in_the_directive():
    assert E.art_option({"art": "stick_figure"}) == " | art=stick_figure"
    assert E.art_option({"art": "real"}) == " | art=real"
    assert E.art_option({}) == "" and E.art_option({"art": ""}) == ""
    assert E.directive_for({"kind": "broll_image", "image_prompt": "x", "art": "stick_figure"}) == \
        "[broll: x | art=stick_figure]"
    assert B._directive_for({"kind": "broll_video", "video_prompt": "y", "art": "real"}) == \
        "[video: y | art=real] "


def test_normalize_beat_keeps_the_art_key():
    beat, _ = E.normalize_beat({"kind": "broll_image", "image_prompt": "x", "art": "stick_figure"})
    assert beat.get("art") == "stick_figure"


# -------------------------------------------------------- the quirky mix

def test_quirky_is_known_and_aliased():
    assert "mixed_quirky" in A.ART_STYLES
    assert A.normalise("quirky") == "mixed_quirky" and A.normalise("quirky_doc") == "mixed_quirky"
    assert A.is_mixed("mixed_quirky") and A.is_mixed("quirky")
    assert A.uses_face_swap("mixed_quirky") and A.text_cards("mixed_quirky") is True


def test_quirky_shot_style_and_unknown_art_falls_back_to_illustrated():
    assert A.shot_style("mixed_quirky", "illustrated") == "illustrated"
    assert A.shot_style("mixed_quirky", "stick_figure") == "stick_figure"
    assert A.shot_style("mixed_quirky", "real") == "real"
    assert A.shot_style("mixed_quirky", "nonsense") == "illustrated"
    assert A.shot_style("mixed_quirky", None) == "illustrated"


def test_quirky_thumbnail_is_illustrated_not_real():
    assert A.thumbnail_look("mixed_quirky") == A.get("illustrated").thumbnail
    assert A.thumbnail_look("mixed") == A.get("real").thumbnail


def test_quirky_illustrated_shot_gets_the_illustrated_look_and_no_face_mark():
    out, stats = V.apply_to_script(
        "[broll: Harrison walks the deck | art=illustrated] a [broll: Harrison at the rail | art=real] b\n",
        0.0, CAST, art_style="mixed_quirky")
    shots = re.findall(r"\[broll: ([^\]]*)\]", out)
    assert "hand-drawn digital illustration" in shots[0] and "face=" not in shots[0]
    # The real shot alone is inferred as the main character's face.
    assert "face=main" in shots[1] and "Harrison: a stocky man" in shots[1]
    assert stats["main_face"] == 1
    assert "art=" not in out


def test_quirky_stamp_art_style_leaves_real_untouched_and_stamps_illustrated():
    text = "[broll: Harrison at the rail | art=real] [broll: Harrison walks | art=illustrated]"
    out = V.stamp_art_style(text, "mixed_quirky")
    assert "[broll: Harrison at the rail]" in out
    assert "hand-drawn digital illustration" in out and "art=" not in out
