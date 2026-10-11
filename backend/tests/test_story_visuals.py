import re

import pytest

from integrations import buzzedit_settings as S
from integrations import story_visuals as V

SCRIPT = (
    "# COLD OPEN\n\n"
    "[broll: a dark corridor | look=noir] raat ke teen baje [statement: Ek *kahani*.] "
    "guard ne dekha [broll: the guard holds a torch] ki darwaza khula tha "
    "[newspaper: OLD NEWS | 1990] [music: eerie drone, 60 bpm] "
    "[broll: an empty office] aur phir [fx: flash] [broll: the guard runs] sab chup.\n"
)
CAST = {"world": "a 1990s government office at night",
        "characters": [{"name": "Ramesh", "aliases": ["guard"], "look": "a thin man in a khaki uniform"}]}


@pytest.fixture(autouse=True)
def _seeded_profiles(tmp_path, monkeypatch):
    # A throwaway profiles file, seeded from the defaults on first read.
    monkeypatch.setattr(S, "CHANNEL_PROFILES_PATH", str(tmp_path / "channel_profiles.json"))


def _spoken(text):
    text = re.sub(r"\[[a-z_]+:[^\]]*\]", "", text)
    text = re.sub(r"^#.*$", "", text, flags=re.M)
    return " ".join(text.split())


def test_only_pictures_videos_and_music_survive():
    out, stats = V.apply_to_script(SCRIPT, 0.5, None)
    kinds = re.findall(r"\[\s*([a-z_]+)\s*:", out)
    assert set(kinds) <= {"broll", "video", "music"}
    assert "#" not in out
    assert stats["removed"] == 3 and stats["headings_removed"] == 1
    assert _spoken(out) == _spoken(SCRIPT)


def test_video_share_spread_evenly():
    out, stats = V.apply_to_script(SCRIPT, 0.5, None)
    assert stats["pictures"] == 4 and stats["videos"] == 2
    kinds = [k for k in re.findall(r"\[\s*([a-z_]+)\s*:", out) if k != "music"]
    assert kinds == ["broll", "video", "broll", "video"]
    _, all_video = V.apply_to_script(SCRIPT, 1.0, None)
    assert all_video["videos"] == 4
    _, none = V.apply_to_script(SCRIPT, 0.0, None)
    assert none["videos"] == 0


def test_video_prompt_drops_options_and_is_calm():
    out, _ = V.apply_to_script("[broll: a dark corridor | look=noir] words\n", 1.0, None)
    assert out.startswith("[video: a dark corridor, noir look, slow steady")
    assert "look=" not in out


def test_cast_look_added_to_shots_of_that_character_only():
    out, _ = V.apply_to_script(SCRIPT, 0.0, CAST)
    shots = re.findall(r"\[broll: ([^\]]*)\]", out)
    assert "khaki uniform" in shots[1] and "khaki uniform" in shots[3]
    assert "khaki uniform" not in shots[2]
    assert all("1990s government office" in s for s in shots)


def test_story_channels_resolve_to_story_style():
    for brand in ("Raat3Baje", "Khayal3Baje", "Beyond3Baje"):
        settings, sources = S.resolve_settings(brand)
        assert settings["visual_style"] == "story"
        assert settings["captions"] is False and settings["sfx"] is False
        assert settings["newspapers"] is False and settings["mood_hits"] is False
        assert settings["video_broll_share"] == 0.3
    assert S.resolve_settings("Life3Baje")[0]["visual_style"] == "full"
    assert "captions" not in S.resolve_settings("Life3Baje")[0]


def test_project_can_override_story_fields_or_style():
    class P:
        metadata = {"video_settings": {"sfx": True, "video_broll_share": 1.0}}

    settings, sources = S.resolve_settings("Raat3Baje", None, P())
    assert settings["sfx"] is True and settings["video_broll_share"] == 1.0
    assert settings["captions"] is False

    class Full:
        metadata = {"video_settings": {"visual_style": "full"}}

    settings, _ = S.resolve_settings("Raat3Baje", None, Full())
    assert settings["visual_style"] == "full" and "captions" not in settings

    class Story:
        metadata = {"video_settings": {"visual_style": "story"}}

    settings, _ = S.resolve_settings("Life3Baje", None, Story())
    assert settings["captions"] is False and settings["video_broll_share"] == 0.3


def test_filter_beats_and_planner_section():
    beats = [{"kind": "broll_image"}, {"kind": "statement_card"}, {"kind": "broll_video"}, {"kind": "fx"}]
    assert [b["kind"] for b in V.filter_beats(beats)] == ["broll_image", "broll_video"]
    section = V.planner_section(0.5, CAST)
    assert "About 50%" in section and "Ramesh: a thin man" in section


def test_camera_filming_the_shot_is_never_named():
    # The still model drew a DSLR into every shot that said "the camera ...".
    assert V.without_camera("The camera slowly pans across Arjun's face as he waits.") == \
        "Slow pan across Arjun's face as he waits."
    assert V.without_camera("The camera captures his hands shaking") == "His hands shaking"
    assert V.without_camera("the old ledger; the camera focusing on the ink") == \
        "The old ledger; close focus on the ink"
    assert V.without_camera("Shot on a DSLR, 35mm lens, f/1.8, a woman in a doorway") == "A woman in a doorway"
    assert V.without_camera("Arjun looks into the camera") == "Arjun looks toward the viewer"
    # A camera that is part of the story stays.
    assert "CCTV camera" in V.without_camera("A CCTV camera blinks above the gate")
    out, _ = V.apply_to_script("[video: The camera moves toward the door] words [broll: a door] x\n", 1.0, None)
    assert "camera" not in out.lower()
    assert out.startswith("[video: Push toward the door, slow steady")


def test_face_led_story_channels_keep_face_zooms():
    for brand in ("Raat3Baje", "Beyond3Baje"):
        settings, sources = S.resolve_settings(brand)
        assert settings["face_zoom"] is True and settings["punch_rate_per_minute"] > 0
        assert sources["face_zoom"] == "face_led"
    assert S.resolve_settings("Khayal3Baje")[0]["face_zoom"] is False

    class Off:
        metadata = {"video_settings": {"face_zoom": False}}

    assert S.resolve_settings("Raat3Baje", None, Off())[0]["face_zoom"] is False


def _timed_story(n_words=900, gap=0.4, every=12):
    words, times = [], []
    for j in range(n_words):
        if j % every == 0:
            words.append(f"[broll: scene {j // every}]")
        words.append(f"w{j}")
        times.append(round(j * gap, 3))
    return " ".join(words) + "\n", times, n_words * gap


@pytest.mark.parametrize("share", [0.3, 0.5, 0.7, 0.8])
def test_timed_clips_fill_the_share_of_runtime(share):
    text, times, duration = _timed_story()
    out, stats = V.apply_to_script(text, share, None, word_times=times, duration_s=duration)
    assert abs(stats["video_runtime_share"] - share) <= 0.01
    assert _spoken(out) == _spoken(text)
    shots, _ = V.plan_timed_shots(
        [j for j in range(0, 900, 12)], times, duration, share)
    spans = sorted((times[s["word"]], times[s["word"]] + s["seconds"], s["video"]) for s in shots)
    for (a0, a1, _), (b0, _, _) in zip(spans, spans[1:]):
        assert a1 <= b0 + 1e-6                      # never two shots at once
    assert all(s1 - s0 <= 8.0 + 1e-6 for s0, s1, _ in spans)
    assert all(s1 - s0 >= 3.0 - 1e-6 for s0, s1, video in spans if video)
    # Spread through the video, not bunched at the start.
    half = sum(min(s1, duration / 2) - s0 for s0, s1, v in spans if v and s0 < duration / 2)
    assert abs(half / (duration / 2) - share) < 0.1


def test_timed_directives_carry_their_length():
    text, times, duration = _timed_story(n_words=300, every=30)
    out, stats = V.apply_to_script(text, 0.8, None, word_times=times, duration_s=duration)
    holds = [float(x) for x in re.findall(r"\| seconds=([\d.]+)\]", out)]
    assert len(holds) == stats["clips"] + stats["stills"] and stats["continuation_clips"] > 0
    assert "the same" in out  # continuation clips carry the scene on


def test_the_mix_is_video_then_images_then_face_each_up_to_the_whole_video():
    # Every channel starts at 30% video, 55% images, 15% face (2026-10-08; was 70/20/10 on 2026-10-03).
    for brand in ("Raat3Baje", "Beyond3Baje", "Life3Baje", "Originals"):
        assert S.runtime_mix(S.resolve_settings(brand)[0]) == {"video": 0.3, "images": 0.55, "face": 0.15, "mode": "runtime"}
    story = S.settings_for_brand("Raat3Baje")
    # BuzzEdit receives coverage = video + images (0.85); the clip share stays the runtime share.
    assert story["target_coverage"] == 0.85 and story["video_broll_share"] == 0.3

    # Video has priority: images get only what video leaves.
    class P:
        metadata = {"video_settings": {"video_broll_share": 0.7, "image_broll_share": 0.7}}
    assert S.runtime_mix(S.resolve_settings("Raat3Baje", None, P())[0])["images"] == 0.3

    # A project that saved BuzzEdit's coverage pair itself keeps that meaning...
    class Legacy:
        metadata = {"video_settings": {"target_coverage": 0.7, "video_broll_share": 0.35}}
    legacy = S.resolve_settings("Life3Baje", None, Legacy())[0]
    assert S.runtime_mix(legacy)["mode"] == "coverage"
    assert S.settings_for_brand("Life3Baje", None, Legacy())["target_coverage"] == 0.7
    assert S.settings_for_brand("Life3Baje", None, Legacy())["video_broll_share"] == 0.35

    # ...otherwise video + images become BuzzEdit's coverage (up to 100%), and
    # the clips' runtime share becomes their part of that coverage.
    class Mixed:
        metadata = {"video_settings": {"video_broll_share": 0.6, "image_broll_share": 0.4}}
    sent = S.settings_for_brand("Life3Baje", None, Mixed())
    assert sent["target_coverage"] == 1.0 and sent["video_broll_share"] == 0.6


@pytest.mark.parametrize("video,images", [(0.5, 0.3), (0.8, 0.2), (0.2, 0.5), (1.0, 0.0), (0.0, 1.0), (0.5, 0.5)])
def test_timed_shots_fill_video_and_images_to_their_shares(video, images):
    text, times, duration = _timed_story(n_words=1200, every=20)
    _, stats = V.apply_to_script(text, video, None, word_times=times, duration_s=duration, image_share=images)
    assert abs(stats["video_runtime_share"] - video) <= 0.015
    assert abs(stats["image_runtime_share"] - images) <= 0.02
    if video + images >= 1.0:
        assert stats["face_runtime_share"] <= 0.01           # a full mix leaves no face


# --- one face for the main character (BuzzEdit's ReActor swap) -----------------

FACE_CAST = {
    "world": "a 1990s government office at night",
    "main_character": "Ramesh",
    "characters": [
        {"name": "Ramesh", "aliases": ["guard"], "gender": "male", "look": "a thin man in a khaki uniform"},
        {"name": "Kamla", "aliases": ["old woman"], "gender": "female", "look": "an old woman in a grey shawl"},
    ],
}


def _pictures(out):
    return re.findall(r"\[(broll|video): ([^\]]*)\]", out)


def test_clean_cast_keeps_a_known_main_character_and_gender():
    cast = V._clean_cast({**FACE_CAST, "main_character": "ramesh"})
    assert cast["main_character"] == "Ramesh"
    assert V.main_character(cast)["gender"] == "male"
    # A name that is not in the cast is no main character at all.
    assert V._clean_cast({**FACE_CAST, "main_character": "Suresh"})["main_character"] == ""
    # A sheet from before the face swap stays undecided (no key).
    old = V._clean_cast({k: v for k, v in FACE_CAST.items() if k != "main_character"})
    assert "main_character" not in old and V.buzzedit_main_character(old) is None
    # Pronouns are never aliases: "he" would tie every shot to one person.
    cast = V._clean_cast({"characters": [{"name": "Ramesh", "aliases": ["he", "the guard"], "look": "x y"}]})
    assert cast["characters"][0]["aliases"] == ["the guard"]


def test_buzzedit_setting_names_the_face_or_says_none():
    assert V.buzzedit_main_character(FACE_CAST) == {
        "name": "Ramesh", "description": "a thin man in a khaki uniform", "gender": "male"}
    assert V.buzzedit_main_character({**FACE_CAST, "main_character": ""}) == {}
    # BuzzEdit takes a look under 6 words as no lead: then nothing is marked either.
    thin = {**FACE_CAST, "characters": [dict(FACE_CAST["characters"][0], look="a thin man")]}
    assert V.buzzedit_main_character(thin) == {}
    out, _ = V.apply_to_script("[broll: the guard | face=main] a\n", 0.0, thin)
    assert "face=" not in out


def test_planner_marks_only_main_character_shots():
    out, stats = V.apply_to_script(
        "[broll: the guard at his desk | face=main] a [broll: Kamla in the doorway | face=no] b "
        "[broll: an empty corridor] c\n", 0.0, FACE_CAST)
    shots = _pictures(out)
    assert shots[0][1].endswith("| face=main") and shots[0][1].startswith("Ramesh: a thin man")
    assert "face=" not in shots[1][1] and "face=" not in shots[2][1]
    # Kamla keeps her own look; she never gets his.
    assert "grey shawl" in shots[1][1] and "khaki" not in shots[1][1]
    assert stats["main_face"] == 1


def test_group_shot_puts_the_main_character_nearest():
    out, _ = V.apply_to_script("[broll: the guard talks to the old woman | face=main] a\n", 0.0, FACE_CAST)
    prompt = _pictures(out)[0][1]
    assert "face=main" in prompt
    assert "Ramesh in the foreground, nearest, the largest face" in prompt
    assert "Kamla further back" in prompt


def test_unmarked_script_is_marked_from_who_the_prompt_names():
    out, stats = V.apply_to_script(
        "[broll: the guard holds a torch] a [broll: the guard seen from behind] b "
        "[broll: the old woman smiles] c [video: the guard's hands tremble] d\n", 0.0, FACE_CAST)
    shots = _pictures(out)
    assert "face=main" in shots[0][1]
    assert all("face=" not in s[1] for s in shots[1:])
    assert stats["main_face"] == 1


def test_no_main_character_means_no_face_marks():
    for cast in ({**FACE_CAST, "main_character": ""}, CAST, None):
        out, stats = V.apply_to_script("[broll: the guard | face=main] a [video: the guard | face=main] b\n",
                                       0.5, cast)
        assert "face=" not in out and stats["main_face"] == 0


def test_face_mark_survives_clips_and_timing():
    out, _ = V.apply_to_script("[broll: the guard at the gate | face=main | look=noir] raat ko\n", 1.0, FACE_CAST)
    assert re.match(r"\[video: .*noir look, slow steady.* \| face=main\]", out)
    text = "[broll: the guard at the gate | face=main] one two three four five six seven eight\n"
    times = [float(i) for i in range(8)]
    out, stats = V.apply_to_script(text, 1.0, FACE_CAST, word_times=times, duration_s=8.0)
    assert re.search(r"\[video: [^\]]*\| seconds=[\d.]+ \| face=main\]", out)
    assert stats["main_face"] >= 1


def test_planner_section_explains_the_face_mark():
    section = V.planner_section(0.5, FACE_CAST)
    assert "Ramesh (MAIN CHARACTER): a thin man" in section
    assert '"main_face": true' in section and "foreground" in section
    assert "main_face" not in V.planner_section(0.5, CAST)


def test_plan_beats_carry_the_mark_into_directives():
    from integrations import buzzedit_script as B
    from integrations import effect_catalog as E
    assert E.directive_for({"kind": "broll_image", "image_prompt": "the guard", "main_face": True}) == \
        "[broll: the guard | face=main]"
    assert E.directive_for({"kind": "broll_image", "image_prompt": "a gate", "main_face": False}) == \
        "[broll: a gate | face=no]"
    assert E.directive_for({"kind": "broll_image", "image_prompt": "a gate"}) == "[broll: a gate]"
    assert B._directive_for({"kind": "broll_video", "video_prompt": "the guard walks", "main_face": "true"}) == \
        "[video: the guard walks | face=main] "


def test_older_cast_sheet_gets_its_main_character_once(tmp_path):
    import json

    class Project:
        assets = {}

        def get_project_dir(self):
            return str(tmp_path)

        def save(self):
            pass

    sheet = tmp_path / "production" / "cast_sheet.json"
    sheet.parent.mkdir()
    sheet.write_text(json.dumps({k: v for k, v in FACE_CAST.items() if k != "main_character"}), encoding="utf-8")
    calls = []

    class Agent:
        llm_service = None

        def execute(self, prompt, require_json=False):
            calls.append(prompt)
            return '{"main_character": "Ramesh", "gender": "male"}'

    cast = V.ensure_cast_sheet(Project(), "Ramesh guard ki kahani", Agent)
    assert cast["main_character"] == "Ramesh" and len(calls) == 1
    assert json.loads(sheet.read_text(encoding="utf-8"))["main_character"] == "Ramesh"
    V.ensure_cast_sheet(Project(), "Ramesh guard ki kahani", Agent)
    assert len(calls) == 1


def test_marked_prompt_carries_the_look_buzzedit_checks_for():
    out, _ = V.apply_to_script("[broll: the guard at the gate | face=main] a\n", 0.0, FACE_CAST)
    description = V.buzzedit_main_character(FACE_CAST)["description"]
    assert description.lower()[:40] in _pictures(out)[0][1].lower()


# ------------------------------------------- creatures stay in their own beats

def test_world_line_loses_the_tiger_reserve_and_keeps_the_look():
    world = V.visual_world("A dense, remote tiger reserve forest in Central India during the monsoon, "
                           "grey light, wet sal leaves")
    assert world == "A dense, remote forest in Central India during the monsoon, grey light, wet sal leaves"
    assert V.visual_world("a dense, remote tiger reserve") == "a dense, remote forest"


def test_continuity_never_appends_a_creature_the_beat_lacks():
    cast = {"world": "misty sal forest at dawn where a leopard prowls, cold blue light",
            "characters": [{"name": "Ramesh", "aliases": ["ranger"],
                            "look": "a thin ranger in khaki with a black dog at his heel"}]}
    out = V._with_continuity("the ranger walks a muddy trail", cast)
    assert "leopard" not in out and "dog" not in out
    assert "khaki" in out and "misty sal forest" in out
    kept = V._with_continuity("the ranger kneels beside his dog", cast)
    assert "black dog at his heel" in kept and "leopard" not in kept


def test_lint_prompt_cuts_a_leaked_creature_and_keeps_one_the_beat_names():
    linted = V.lint_prompt("a jeep on a forest road, a tiger in the tall grass", "a jeep on a forest road")
    assert "tiger" not in linted and linted.startswith("a jeep on a forest road")
    named = V.lint_prompt("a tiger drinks at the river, an owl above", "a tiger drinks at the river")
    assert "tiger drinks at the river" in named and "owl" not in named
    out, _ = V.apply_to_script("[broll: a jeep on a forest road] words [broll: a tiger at the river] more\n",
                               0.0, {"world": "a dense tiger reserve forest in the monsoon", "characters": []})
    shots = re.findall(r"\[broll: ([^\]]*)\]", out)
    assert "tiger" not in shots[0] and "dense forest in the monsoon" in shots[0]
    assert "a tiger at the river" in shots[1]


def test_story_style_keeps_the_scenes_own_sound_cues():
    cue = "[sfx: footsteps running on wet leaves | kind=accent | level=subtle | seconds=3]"
    out, stats = V.apply_to_script(f"[broll: a dark trail] woh {cue} bhaagne laga\n", 0.0, None)
    assert cue in out and stats["pictures"] == 1 and stats["removed"] == 0
    text, times, duration = _timed_story(n_words=120, every=30)
    timed, _ = V.apply_to_script(text.replace("w40 ", f"w40 {cue} "), 0.5, None,
                                 word_times=times, duration_s=duration)
    assert f"w40 {cue} w41" in timed
    assert [b["kind"] for b in V.filter_beats([{"kind": "sfx_cue"}, {"kind": "fx"}])] == ["sfx_cue"]
    settings, _ = S.resolve_settings("Raat3Baje")
    assert settings["sfx"] is False and settings["sfx_diegetic"] is True
    assert S.resolve_settings("Life3Baje")[0]["sfx_diegetic"] is True
