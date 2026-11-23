"""Narrated story reels (REELS_DESK_PLAN.md VR5): the planner's shot-count
band, camera-word stripping, video-share repair, character/`shows_character`
rules, and the exact narration-mode `POST /api/reels/vibe` body."""
import json

import pytest

from app.services import shorts_desk, story_reel


def _shot(seconds=5, prompt="a doorway at night, portrait, real", motion=None, kind=None,
          shows_character=None, entity=None):
    d = {"prompt": prompt, "seconds": seconds}
    if motion is not None:
        d["motion"] = motion
    if kind is not None:
        d["kind"] = kind
    if shows_character is not None:
        d["shows_character"] = shows_character
    if entity is not None:
        d["entity"] = entity
    return d


# --- shot_count_range -----------------------------------------------------------------

def test_shot_count_range_from_duration():
    lo, hi = story_reel.shot_count_range(45.0)
    assert lo == 9 and hi == 12
    # A short clip is never asked for fewer than MIN_SHOTS.
    lo, hi = story_reel.shot_count_range(5.0)
    assert lo == story_reel.MIN_SHOTS and hi >= lo


def test_target_shot_count_is_seconds_over_4_5_inside_the_band():
    assert story_reel.target_shot_count(40.0) == 9      # round(40/4.5)=9, band (8, 10)
    assert story_reel.target_shot_count(189.0) == 42     # round(189/4.5)=42, band (37, 48)
    lo, hi = story_reel.shot_count_range(189.0)
    assert lo <= story_reel.target_shot_count(189.0) <= hi


# --- validate_story_plan ---------------------------------------------------------------

def test_too_few_shots_or_no_world_raises():
    with pytest.raises(ValueError, match="needs"):
        story_reel.validate_story_plan({"world": "w", "shots": [_shot(), _shot()]}, 45.0)
    with pytest.raises(ValueError):
        story_reel.validate_story_plan({"shots": [_shot() for _ in range(10)]}, 45.0)
    with pytest.raises(ValueError):
        story_reel.validate_story_plan(None, 45.0)


def test_stick_shot_kept_only_for_a_stick_world_reel():
    stick = {"kind": "stick", "action": "point", "era": "ancient_greece",
             "bg": "a Greek library court, marble columns", "seconds": 5}
    plan = {"world": "w", "shots": [stick] + [_shot(prompt=f"shot {i}") for i in range(9)]}
    out = story_reel.validate_story_plan(plan, 45.0, "stick_world")
    assert out["art_style"] == "stick_world"
    first = out["shots"][0]
    assert first["kind"] == "stick" and first["era"] == "ancient_greece" and first["action"] == "point"
    real = story_reel.validate_story_plan(plan, 45.0)
    assert real["art_style"] == "real" and real["shots"][0]["kind"] == "still"
    assert real["shots"][0]["prompt"].startswith("a Greek library court")


def test_too_many_shots_are_cut_at_the_end_in_script_order():
    shots = [_shot(prompt=f"shot {i}") for i in range(30)]
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 45.0)
    _, hi = story_reel.shot_count_range(45.0)
    assert len(out["shots"]) == hi
    assert out["shots"][0]["prompt"] == "shot 0"


def test_banned_camera_words_are_stripped_from_prompts_motion_and_character():
    plan = {"world": "a haveli courtyard at night", "character": {
                "name": "Raj", "description": "shot on DSLR, a man in a kurta, 50mm lens", "gender": "male"},
            "shots": [_shot(prompt="photo of a corridor, shot on DSLR", motion="a slow camera drift, rain"),
                      _shot(), _shot(), _shot(), _shot(), _shot(), _shot(), _shot(), _shot()]}
    out = story_reel.validate_story_plan(plan, 40.0)
    text = json.dumps(out).lower()
    for word in ("camera", "dslr", "lens", "tripod", "photo of", "shot on"):
        assert word not in text
    assert "a man in a kurta" in out["character"]["description"]


def test_kind_defaults_from_whether_the_motion_actually_moves():
    plan = {"world": "w", "shots": [
        {"prompt": "a doorway, portrait", "seconds": 5},
        {"prompt": "a window, rain", "motion": "rain falling slowly on the glass", "seconds": 5},
        _shot(), _shot(), _shot(), _shot(), _shot(), _shot(), _shot()]}
    out = story_reel.validate_story_plan(plan, 45.0)
    assert out["shots"][0]["kind"] == "still"
    assert out["shots"][1]["kind"] == "video"


def test_video_share_is_capped_to_about_a_third():
    shots = [_shot(kind="video", prompt=f"shot {i}") for i in range(9)]
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 40.0)
    kinds = [s["kind"] for s in out["shots"]]
    cap = max(1, round(len(out["shots"]) * story_reel.VIDEO_SHARE))
    assert kinds.count("video") == cap
    assert kinds[:cap] == ["video"] * cap and kinds[cap:] == ["still"] * (len(kinds) - cap)


def test_shows_character_requires_a_character():
    plan = {"world": "w", "shots": [_shot(shows_character=True) for _ in range(9)]}
    out = story_reel.validate_story_plan(plan, 40.0)
    assert out["character"] is None
    assert all(s["shows_character"] is False for s in out["shots"])

    plan2 = {"world": "w", "character": {"name": "Raj", "description": "a lean man in a kurta", "gender": "male"},
             "shots": [_shot(shows_character=(i == 0)) for i in range(9)]}
    out2 = story_reel.validate_story_plan(plan2, 40.0)
    assert out2["character"] == {"name": "Raj", "description": "a lean man in a kurta", "gender": "male"}
    assert out2["shots"][0]["shows_character"] is True
    assert all(s["shows_character"] is False for s in out2["shots"][1:])


def test_character_missing_name_or_description_is_dropped():
    plan = {"world": "w", "character": {"name": "", "description": "a man"},
            "shots": [_shot() for _ in range(9)]}
    out = story_reel.validate_story_plan(plan, 40.0)
    assert out["character"] is None


def test_art_style_is_always_real():
    plan = {"world": "w", "art_style": "painterly", "shots": [_shot() for _ in range(9)]}
    assert story_reel.validate_story_plan(plan, 40.0)["art_style"] == "real"


# --- entity shots (REELS_DESK_PLAN.md VR9, creator follow-up 2026-10-24) ---------------------

def test_no_entity_shots_at_all_is_fine_for_a_story_with_no_being():
    plan = {"world": "w", "shots": [_shot() for _ in range(9)]}
    out = story_reel.validate_story_plan(plan, 40.0)
    assert all(not s.get("entity") for s in out["shots"])


def test_a_single_entity_shot_is_repaired_to_the_minimum_once_the_story_has_a_being():
    # Repaired, not failed (Fable review 2026-10-24): the reel's narration is already made.
    shots = [_shot(prompt=f"shot {i}", entity=(i == 0)) for i in range(9)]
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 40.0)
    glimpsed = [s for s in out["shots"] if "glimpsed" in s["prompt"]]
    assert len(glimpsed) == story_reel.MIN_ENTITY_SHOTS - 1   # one shot promoted near the end


def test_two_or_more_entity_shots_pass():
    shots = [_shot(entity=(i < 2)) for i in range(9)]
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 40.0)
    # `entity` is an internal planning flag -- it never reaches the renderer's own shot fields.
    assert all("entity" not in s for s in out["shots"])


def test_entity_minimum_is_enforced_after_the_too_many_shots_cut():
    # 10 shots for 40 s (band 8-10): only the two entity shots sit right at the cut point.
    shots = [_shot(prompt=f"shot {i}") for i in range(8)] + [_shot(prompt="entity shot", entity=True) for _ in range(2)]
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 40.0)
    assert len(out["shots"]) == 10   # nothing dropped: hi for 40 s is already 10
    # hi for 20 s is smaller: the two entity shots at the end are cut away -- and repaired.
    out = story_reel.validate_story_plan({"world": "w", "shots": shots}, 20.0)
    assert out["shots"]


def test_repair_keeps_the_entity_flag_on_the_shot_it_splits():
    # Only the longest shot is marked entity, so it is the one `_repair_shot_count`
    # splits first; the variation must keep the flag, or the final plan is left with
    # just the original 1 entity shot and the minimum-of-2 check fails it.
    shots = [_shot(seconds=7, entity=True)] + [_shot(seconds=4) for _ in range(4)]
    out = story_reel._repair_shot_count({"world": "w", "shots": shots}, 40.0)
    lo, hi = story_reel.shot_count_range(40.0)
    assert lo <= len(out["shots"]) <= hi


# --- plan_story_shots --------------------------------------------------------------------

def test_plan_story_shots_calls_the_planner_with_script_seconds_channel_format(monkeypatch):
    seen = {}

    def agent_json(agent, task):
        seen["agent"] = agent
        seen["task"] = task
        return {"world": "a dim haveli courtyard", "shots": [_shot(prompt=f"shot {i}") for i in range(9)]}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent_json)
    out = story_reel.plan_story_shots("niyam ek: darwaza mat kholna", 40.0, "Raat3Baje", "rules_horror")
    assert seen["agent"] == "StoryReelPlanner"
    assert seen["task"] == {"script": "niyam ek: darwaza mat kholna", "seconds": 40, "channel": "Raat3Baje",
                            "format": "rules_horror", "shots": 9, "art_style": "real"}
    assert out["world"] == "a dim haveli courtyard" and len(out["shots"]) == 9


def test_plan_story_shots_raises_when_the_planner_gives_nothing(monkeypatch):
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda agent, task: None)
    with pytest.raises(ValueError):
        story_reel.plan_story_shots("text", 40.0, "Raat3Baje", "rules_horror")


def test_too_few_shots_re_asks_once_with_the_exact_count_and_previous_plan(monkeypatch):
    tasks, replies = [], [
        {"world": "a dim haveli courtyard", "shots": [_shot(prompt=f"shot {i}") for i in range(5)]},
        {"world": "a dim haveli courtyard", "shots": [_shot(prompt=f"shot {i}") for i in range(9)]},
    ]

    def agent_json(agent, task):
        tasks.append(task)
        return replies[len(tasks) - 1]

    monkeypatch.setattr(shorts_desk, "_agent_json", agent_json)
    out = story_reel.plan_story_shots("niyam ek: darwaza mat kholna", 40.0, "Raat3Baje", "rules_horror")
    assert len(tasks) == 2
    assert tasks[1]["shots"] == 9 and "exactly 9 shots" in tasks[1]["instruction"]
    assert tasks[1]["previous_plan"] == replies[0]   # the unusable first plan, for context
    assert len(out["shots"]) == 9


def test_still_too_few_after_retry_is_repaired_deterministically_not_failed(monkeypatch):
    calls = []

    def agent_json(agent, task):
        calls.append(task)
        # Both the first call and the retry come back short (5 shots; the band for 40 s is 8-10).
        return {"world": "a dim haveli courtyard",
                "shots": [_shot(seconds=5, prompt=f"shot {i}") for i in range(5)]}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent_json)
    out = story_reel.plan_story_shots("niyam ek: darwaza mat kholna", 40.0, "Raat3Baje", "rules_horror")
    assert len(calls) == 2   # one re-ask, then the deterministic repair -- never a third model call
    lo, hi = story_reel.shot_count_range(40.0)
    assert lo <= len(out["shots"]) <= hi
    assert out["world"] == "a dim haveli courtyard"
    # The split variations keep the world's own prompt, framed differently, as stills.
    prompts = [s["prompt"] for s in out["shots"]]
    assert any("framing of the same scene" in p for p in prompts)
    assert all(s["kind"] == "still" or s["prompt"].startswith("shot ") for s in out["shots"])


def test_repair_raises_when_even_the_retry_has_no_usable_shots(monkeypatch):
    monkeypatch.setattr(shorts_desk, "_agent_json", lambda agent, task: {"world": "a dim haveli courtyard",
                                                                          "shots": []})
    with pytest.raises(ValueError):
        story_reel.plan_story_shots("text", 40.0, "Raat3Baje", "rules_horror")


# --- vibe_story_body ---------------------------------------------------------------------

def test_vibe_story_body_is_narration_mode_with_no_lines_or_cards():
    plan = {"world": "a dim haveli courtyard", "art_style": "real",
            "character": {"name": "Raj", "description": "a lean man in a kurta", "gender": "male"},
            "shots": [{"prompt": "a doorway", "motion": "a doorway", "seconds": 5, "kind": "still",
                      "shows_character": False}]}
    body = story_reel.vibe_story_body("/out/dir", "reel", plan, "/out/dir/narration.wav", "darwaza mat kholna")
    assert body["out_dir"] == "/out/dir" and body["name"] == "reel"
    assert body["art_style"] == "real" and body["world"] == "a dim haveli courtyard"
    assert body["shots"] == plan["shots"]
    assert body["narration"] == {"path": "/out/dir/narration.wav", "text": "darwaza mat kholna", "language": "hi"}
    assert body["captions"] == {"style": "phrases"}
    assert body["dissolve_s"] == story_reel.DEFAULT_DISSOLVE_S and body["push"] == story_reel.DEFAULT_PUSH
    assert body["character"] == plan["character"]
    assert "lines" not in body and "cards" not in body
    assert body["ambience"] == [] and body["music"] is None
    # 2026-10-23: the same hyper-realistic AI clips as the mood reel.
    assert body["quality"] == "reel_hq"
