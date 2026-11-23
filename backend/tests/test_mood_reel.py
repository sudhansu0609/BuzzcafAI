"""Life3Baje mood reel (REELS_DESK_PLAN.md §6, VR2): theme/mood rotation, the
real-line search (any rights, never Urdu script), the planner's shots and
couplet cards, and `make_mood_reel` end to end with the poem search, the
planner and BuzzEdit's vibe-reel renderer all faked."""
import json
import os
import types

import pytest

from app.services import auto_story, mood_reel, shorts_desk
from core.models import project as project_model
from core.models.project import Project
from integrations.buzzedit_client import BuzzEditClient

LINES = ["dil-e-nadan tujhe hua kya hai", "aakhir is dard ki dava kya hai",
         "hum hain mushtaq aur vo bezaar", "ya ilahi ye majra kya hai"]


def _shot(seconds=6, prompt="a lamp in rain, portrait, real", motion=None, kind=None):
    d = {"prompt": prompt, "seconds": seconds}
    if motion is not None:
        d["motion"] = motion
    if kind is not None:
        d["kind"] = kind
    return d


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(auto_story, "STORE_DIR", str(tmp_path / "auto_story"))
    return tmp_path


# --- theme / mood rotation ------------------------------------------------------------

def test_theme_rotation_avoids_recent_picks(store):
    picks = [mood_reel.pick_theme() for _ in range(12)]
    assert all(t in mood_reel.THEMES for t in picks)
    assert all(picks[i] != picks[i - 1] for i in range(1, len(picks)))
    # An explicit theme is always honoured, rotation or not.
    assert mood_reel.pick_theme("storm") == "storm"


def test_mood_rotation_avoids_recent_picks(store):
    picks = [mood_reel.pick_mood() for _ in range(10)]
    assert all(picks[i] != picks[i - 1] for i in range(1, len(picks)))
    assert mood_reel.pick_mood("ishq") == "ishq"


def test_every_theme_has_a_paired_mood_and_ambience():
    for key, theme in mood_reel.THEMES.items():
        assert theme["mood"] in mood_reel.MOODS
        assert theme["ambience"]


# --- finding the real lines -----------------------------------------------------------

def test_find_lines_accepts_the_highest_scoring_candidate_of_any_rights(monkeypatch):
    def fake_find(channel, fmt, filters=None, count=3, progress=None):
        return {"candidates": [
            {"title": "Modern ghazal", "poet": "Gulzar", "rights": "protected", "score": 90,
             "text": "\n".join(LINES[:2])},
        ]}
    monkeypatch.setattr(shorts_desk, "find", fake_find)
    found = mood_reel.find_lines("Life3Baje", "ishq", lambda m: None)
    assert found["poet"] == "Gulzar" and found["rights"] == "protected" and found["lines"] == LINES[:2]


def test_find_lines_skips_urdu_script(monkeypatch):
    urdu_text = "دل سے تری نگاہ جگر تک اتر گئی\nاتر گئی سیدھی اتر گئی"

    def fake_find(channel, fmt, filters=None, count=3, progress=None):
        return {"candidates": [
            {"title": "Urdu one", "poet": "Someone", "rights": "public_domain", "score": 95, "text": urdu_text},
            {"title": "Roman one", "poet": "Mirza Ghalib", "rights": "public_domain", "score": 80,
             "text": "\n".join(LINES[:2])},
        ]}
    monkeypatch.setattr(shorts_desk, "find", fake_find)
    found = mood_reel.find_lines("Life3Baje", "ishq", lambda m: None)
    assert found["poet"] == "Mirza Ghalib" and found["lines"] == LINES[:2]


def test_is_urdu_script_and_script_of():
    assert mood_reel.is_urdu_script("دل سے تری نگاہ") is True
    assert mood_reel.is_urdu_script("dil se teri nigaah") is False
    assert mood_reel.script_of(["दिल से तेरी निगाह"]) == "devanagari"
    assert mood_reel.script_of(["dil se teri nigaah"]) == "roman"


# --- the planner's shots and cards -----------------------------------------------------

def test_plan_is_rescaled_to_the_target():
    plan = {"world": "a hill road, night, rain", "shots": [_shot(10) for _ in range(3)], "bed": {}}
    out = mood_reel.validate_plan(plan, LINES[:2], 20.0)
    assert out["rescaled"] is True
    assert abs(sum(s["seconds"] for s in out["shots"]) - 20.0) < 0.05
    # within 10%: left alone
    plan = {"world": "w", "shots": [_shot(9) for _ in range(3)]}
    assert mood_reel.validate_plan(plan, LINES[:2], 27.0)["rescaled"] is False


def test_banned_camera_words_are_stripped():
    plan = {"world": "w", "shots": [
        _shot(5, prompt="photo of a lamp in rain, shot on DSLR, 50mm lens", motion="slow camera drift, rain"),
        _shot(5, prompt="a tripod beside a window, curtains", motion="curtains lifting"),
        _shot(5), _shot(5)]}
    out = mood_reel.validate_plan(plan, LINES[:2], 20.0)
    text = json.dumps(out["shots"]).lower()
    for word in ("camera", "dslr", "lens", "tripod", "photo of", "shot on"):
        assert word not in text
    assert "a lamp in rain" in out["shots"][0]["prompt"]


def test_every_shot_is_repaired_to_video():
    """2026-10-23: the creator wants hyper-realistic AI motion, not a
    mostly-still reel -- every shot is "video" whatever the planner wrote."""
    plan = {"world": "w", "shots": [_shot(6, kind="still") for _ in range(5)]}
    out = mood_reel.validate_plan(plan, LINES[:2], 30.0)
    kinds = [s["kind"] for s in out["shots"]]
    assert kinds == ["video"] * len(kinds)


def test_kind_is_always_video_regardless_of_the_planners_own_kind_or_motion():
    plan = {"world": "w", "shots": [
        {"prompt": "a lamp in rain, portrait", "seconds": 6},
        {"prompt": "a window, rain", "motion": "rain falling slowly on the glass", "seconds": 6},
        _shot(6, kind="still"), _shot(6, kind="video")]}
    out = mood_reel.validate_plan(plan, LINES[:2], 24.0)
    assert all(s["kind"] == "video" for s in out["shots"])


def test_too_few_shots_or_no_world_raises():
    with pytest.raises(ValueError):
        mood_reel.validate_plan({"world": "w", "shots": []}, LINES[:2], 20.0)
    with pytest.raises(ValueError):
        mood_reel.validate_plan({"shots": [_shot(6) for _ in range(4)]}, LINES[:2], 20.0)
    with pytest.raises(ValueError):
        mood_reel.validate_plan(None, LINES[:2], 20.0)


def test_cards_are_whole_couplets_timed_across_the_reel_with_credit():
    plan = {"world": "w", "shots": [_shot(6) for _ in range(4)]}
    out = mood_reel.validate_plan(plan, LINES, 26.0, poet="Mirza Ghalib")
    assert [c["text"] for c in out["cards"]] == ["\n".join(LINES[:2]), "\n".join(LINES[2:])]
    assert all(c["script"] == "roman" for c in out["cards"])
    assert out["cards"][0]["start_s"] == mood_reel.CARD_LEAD_S
    assert abs(out["cards"][-1]["end_s"] - (26.0 - mood_reel.CARD_TAIL_S)) < 0.01
    assert out["credit"] == "— Mirza Ghalib"
    # no poet: no credit
    out2 = mood_reel.validate_plan(plan, LINES[:2], 20.0, poet="")
    assert out2["credit"] is None and len(out2["cards"]) == 1


def test_take_lines_keeps_whole_couplets():
    text = "\n".join(LINES[:2]) + "\n\n" + "\n".join(LINES[2:]) + "\n\nfifth line\nsixth line"
    assert mood_reel.take_lines(text) == LINES
    assert mood_reel.take_lines("one\ntwo\nthree") == ["one", "two"]
    assert mood_reel.take_lines("only one line") == []


def test_take_lines_never_joins_two_ghazals():
    text = ("हज़ारों ख़्वाहिशें ऐसी कि हर ख़्वाहिश पर दम निकले\nबहुत निकले मेरे अरमान लेकिन फिर भी कम निकले।\n"
            "यही है आज़माना तो सताना किसको कहते हैं,\nअदू के हो लिए जब तुम तो मेरा इम्तहां क्यों हो।")
    assert len(mood_reel.take_lines(text)) == 2


# --- make_mood_reel end to end ---------------------------------------------------------

@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(project_model, "PROJECTS_DIR", str(root), raising=False)
    monkeypatch.setattr(project_model, "_project_dir_for", lambda pid: str(root / pid), raising=False)
    import core.paths
    monkeypatch.setattr(core.paths, "PROJECTS_DIR", str(root))
    monkeypatch.setattr(auto_story, "STORE_DIR", str(tmp_path / "auto_story"))
    monkeypatch.setattr(auto_story, "_sleep", lambda s: None)
    calls = {"find": [], "agent": [], "vibe_body": []}

    def new_project(channel, theme):
        p = Project(id="mood_1", name="Mood reel", brand=channel, workflow_name="shorts_ready")
        p.save()
        return Project.load("mood_1")

    monkeypatch.setattr(auto_story, "_new_mood_project", new_project)

    def find(channel, fmt, filters=None, count=3, progress=None):
        calls["find"].append((channel, fmt, filters, count))
        return {"candidates": [
            {"title": "Dil-e-nadan", "poet": "Mirza Ghalib", "rights": "public_domain", "poet_died": 1869,
             "verdict": "strong", "score": 88,
             "text": "\n".join(LINES[:2]) + "\n\n" + "\n".join(LINES[2:]) + "\n\nx\ny"}]}

    monkeypatch.setattr(shorts_desk, "find", find)

    def agent_json(agent, task):
        calls["agent"].append((agent, task))
        return {"world": "an old haveli courtyard, late evening, monsoon rain",
                "shots": [{"prompt": f"corner {i} of the haveli courtyard, portrait, real",
                           "motion": "rain falling slowly on the stone" if i == 1 else None,
                           "seconds": 5, "kind": "video" if i == 1 else "still"} for i in range(1, 4)],
                "bed": {"mood": "calm longing", "instruments": ["santoor", "rain"], "bpm": 60}}

    monkeypatch.setattr(shorts_desk, "_agent_json", agent_json)

    polls = {"n": 0}

    def vibe_reel(self, body):
        calls["vibe_body"].append(body)
        return {"job_id": "vibe1"}

    def vibe_reel_job(self, job_id):
        polls["n"] += 1
        stage_dir = root / "mood_1" / "production" / "vibe_reel"
        stage_dir.mkdir(parents=True, exist_ok=True)
        if polls["n"] < 2:
            return {"state": "running", "progress": 0.3, "message": "Rendering shot 1/4"}
        video = stage_dir / "reel.mp4"
        video.write_bytes(b"video")
        cover = stage_dir / "cover.jpg"
        cover.write_bytes(b"cover")
        # No AI music (2026-10-24, VR8): BuzzEdit writes no `_nomusic` file
        # for a lines reel whose request carried `music: null`.
        return {"state": "done", "progress": 1.0, "message": "Done",
                "result": {"video": str(video), "video_nomusic": None, "cover": str(cover),
                          "duration_s": 20.0, "shots": [str(video)], "failures": []}}

    monkeypatch.setattr(BuzzEditClient, "vibe_reel", vibe_reel)
    monkeypatch.setattr(BuzzEditClient, "vibe_reel_job", vibe_reel_job)
    return types.SimpleNamespace(root=root, calls=calls, tmp=tmp_path)


def test_make_mood_reel_end_to_end(env):
    rec = auto_story.make_mood_reel("Life3Baje", "20 seconds", style="painterly", theme="storm")
    assert rec["project_id"] == "mood_1" and rec["state"] == "packaged" and rec["format"] == "mood_reel"
    assert rec["theme"] == "storm" and rec["mood"] == mood_reel.THEMES["storm"]["mood"]
    assert rec["lines"] == LINES and rec["poet"] == "Mirza Ghalib" and rec["style"] == "painterly"

    ch, fmt, filters, count = env.calls["find"][0]
    assert (ch, fmt, count) == ("Life3Baje", "shayari", 3) and filters["length"] == "Short (4-8 lines)"

    agent, task = env.calls["agent"][0]
    assert agent == "MoodReelPlanner" and task["theme"] == mood_reel.THEMES["storm"]["world"]
    assert task["seconds"] == 20 and task["style"] == "painterly" and task["channel"] == "Life3Baje"

    body = env.calls["vibe_body"][0]
    assert body["out_dir"].replace("\\", "/").endswith("mood_1/production/vibe_reel")
    assert body["name"] == "reel" and body["art_style"] == "painterly"
    # the theme's own world leads, then the planner's, then India (his first look)
    assert body["world"] == mood_reel.reel_world("storm", "an old haveli courtyard, late evening, monsoon rain")
    assert body["world"].startswith(mood_reel.THEMES["storm"]["world"]) and "India" in body["world"]
    assert len(body["shots"]) == 3
    assert abs(sum(s["seconds"] for s in body["shots"]) - 20.0) < 0.5
    assert all(s["kind"] == "video" for s in body["shots"])
    assert body["quality"] == "reel_hq"
    assert [c["text"] for c in body["lines"]] == ["\n".join(LINES[:2]), "\n".join(LINES[2:])]
    assert all(c["script"] in ("devanagari", "roman") for c in body["lines"])
    assert body["credit"] == "— Mirza Ghalib"
    # 2026-10-24, VR8: no AI music -- the creator adds his own Instagram song
    # over the ambience the renderer still lays down.
    assert body["music"] is None
    assert body["ambience"] and body["ambience"][0]["gain_db"] == mood_reel.AMBIENCE_GAIN_DB
    assert "script" not in body
    assert body["font"] is None

    out_dir = env.root / "mood_1" / "publish" / "instagram"
    assert (out_dir / "reel.mp4").exists() and (out_dir / "cover.jpg").exists()
    assert not (out_dir / "reel_nomusic.mp4").exists()
    caption = (out_dir / "caption.txt").read_text(encoding="utf-8")
    assert LINES[0] in caption and "Mirza Ghalib" in caption and "#khayal3bajefeels" in caption
    pkg = json.loads((out_dir / "short_package.json").read_text(encoding="utf-8"))
    assert pkg["poet"] == "Mirza Ghalib"
    assert os.path.isfile(rec["final"]) and os.path.basename(rec["final"]) == "reel.mp4"
    assert rec["posted"]["instagram"] == "packaged"

    p = Project.load("mood_1")
    assert p.metadata["orientation"] == "vertical"
    assert p.metadata["auto_story"]["state"] == "packaged"
    assert p.assets["mood_reel_plan"] == "production/mood_reel_plan.json"
    assert p.assets["short_package"] == "publish/short_package.json"
    plan = json.loads((env.root / "mood_1" / "production" / "mood_reel_plan.json").read_text(encoding="utf-8"))
    assert plan["world"] == "an old haveli courtyard, late evening, monsoon rain"


def test_make_mood_reel_failure_records_the_reason(env, monkeypatch):
    def fail(self, job_id):
        return {"state": "failed", "error": "ComfyUI offline"}

    monkeypatch.setattr(BuzzEditClient, "vibe_reel_job", fail)
    with pytest.raises(RuntimeError, match="ComfyUI offline"):
        auto_story.make_mood_reel("Life3Baje", "20 seconds")
    p = Project.load("mood_1")
    assert p.metadata["auto_story"]["state"] == "failed"
    assert "ComfyUI offline" in p.metadata["auto_story"]["error"]


def test_mood_reel_formats_and_settings(env):
    assert "mood_reel" in auto_story.channel_formats("Life3Baje")
    assert "mood_reel" not in auto_story.channel_formats("Raat3Baje")
    assert auto_story.settings()["formats"]["Life3Baje"] == ["mood_reel"]
    with pytest.raises(ValueError):
        auto_story.make("Life3Baje", "mood_reel", style="cartoon")
    from fastapi.testclient import TestClient
    from app.main import app
    fmts = TestClient(app).get("/api/auto_story/formats").json()
    entry = next(f for f in fmts["Life3Baje"] if f["key"] == "mood_reel")
    assert entry["label"] == "Mood reel (ghazal lines over slow scenes)"
    assert entry["lengths"] == list(mood_reel.LENGTHS)
    assert entry["styles"] == ["real", "painterly", "illustrated"]
    assert {t["key"] for t in entry["themes"]} == set(mood_reel.THEMES)


# --- lengths and shot counts (2026-10-23 night rules, VR7) -----------------------

def test_lengths_are_15_to_30_with_45_dropped():
    assert mood_reel.LENGTHS == ("15 seconds", "20 seconds", "26 seconds", "30 seconds")
    assert mood_reel.MIN_SECONDS == 15.0 and mood_reel.MAX_SECONDS == 30.0
    assert mood_reel.parse_seconds("45 seconds") == 30.0   # clamped, not honoured
    assert mood_reel.parse_seconds("15 seconds") == 15.0
    assert mood_reel.parse_seconds(None) == mood_reel.DEFAULT_SECONDS == 26.0


def test_shot_bounds_are_1_to_3():
    assert mood_reel.MIN_SHOTS == 1 and mood_reel.MAX_SHOTS == 3
    plan = {"world": "w", "shots": [_shot(20)]}
    out = mood_reel.validate_plan(plan, LINES[:2], 20.0)
    assert len(out["shots"]) == 1   # one long shot is a valid plan now


def test_a_single_long_shot_can_span_the_whole_reel():
    plan = {"world": "w", "shots": [_shot(26)]}
    out = mood_reel.validate_plan(plan, LINES[:2], 26.0)
    assert len(out["shots"]) == 1
    assert out["shots"][0]["seconds"] <= mood_reel.SHOT_MAX_S
    assert abs(out["shots"][0]["seconds"] - 26.0) < 2.0


# --- the new, ordinary-phone-footage themes (2026-10-23 night rules, VR7) -------

NEW_THEME_KEYS = ("old_houses", "night_forest", "old_hut", "broken_walls", "village_evening",
                 "train_window", "city_golden_hour", "monsoon_garden", "night_street_leaves")


def test_new_themes_are_present_and_valid():
    for key in NEW_THEME_KEYS:
        assert key in mood_reel.THEMES, key
        theme = mood_reel.THEMES[key]
        assert theme["mood"] in mood_reel.MOODS
        assert theme["ambience"]
        assert theme["world"].strip()
        assert not mood_reel._BANNED_RE.search(theme["world"]), theme["world"]


def test_new_themes_are_indian_settings_not_european():
    for key in NEW_THEME_KEYS:
        world = mood_reel.THEMES[key]["world"].lower()
        assert any(hint in world for hint in ("india", "indian", "kerala")), world


# --- Hinglish transliteration (2026-10-23 night rules, VR7) ---------------------

def test_transliterate_lines_skips_already_roman_lines():
    lines = ["dil-e-nadan tujhe hua kya hai", "aakhir is dard ki dava kya hai"]
    out, ok = mood_reel.transliterate_lines(lines)
    assert ok is True
    assert out == lines


def test_transliterate_lines_converts_devanagari_with_matching_count(monkeypatch):
    import integrations.llm as llm_mod

    def fake_generate_text(self, system_prompt, user_prompt, require_json=False, tier=None,
                           temperature=None):
        n = len(json.loads(user_prompt)["lines"])
        return json.dumps({"lines": [f"hinglish {i}" for i in range(n)]})

    monkeypatch.setattr(llm_mod.LLMService, "generate_text", fake_generate_text)
    lines = ["सुबह जल्दी घर से निकल गया", "फिर कभी लौट कर नहीं आया"]
    out, ok = mood_reel.transliterate_lines(lines)
    assert ok is True
    assert out == ["hinglish 0", "hinglish 1"]


def test_transliterate_lines_falls_back_on_a_count_mismatch(monkeypatch):
    import integrations.llm as llm_mod

    def fake_generate_text(self, system_prompt, user_prompt, require_json=False, tier=None,
                           temperature=None):
        return json.dumps({"lines": ["only one"]})

    monkeypatch.setattr(llm_mod.LLMService, "generate_text", fake_generate_text)
    lines = ["सुबह जल्दी घर से निकल गया", "फिर कभी लौट कर नहीं आया"]
    out, ok = mood_reel.transliterate_lines(lines)
    assert ok is False
    assert out == lines


def test_transliterate_lines_falls_back_when_the_llm_is_unavailable(monkeypatch):
    import integrations.llm as llm_mod

    def fake_generate_text(self, system_prompt, user_prompt, require_json=False, tier=None,
                           temperature=None):
        raise llm_mod.LLMUnavailable("no provider reachable")

    monkeypatch.setattr(llm_mod.LLMService, "generate_text", fake_generate_text)
    lines = ["सुबह जल्दी घर से निकल गया"]
    out, ok = mood_reel.transliterate_lines(lines)
    assert ok is False
    assert out == lines


# --- caption.txt layout: Hinglish, blank line, Devanagari, credit --------------

def test_package_caption_shows_hinglish_then_devanagari_when_they_differ():
    devanagari = ["सुबह जल्दी घर से निकल गया"]
    hinglish = ["subah jaldi ghar se nikal gaya"]
    pkg = mood_reel.package(devanagari, "Mirza Ghalib", hinglish_lines=hinglish)
    lines = pkg["caption"].split("\n\n")
    assert lines[0] == hinglish[0]
    assert lines[1] == devanagari[0]
    assert lines[2] == "— Mirza Ghalib"


def test_package_caption_shows_once_when_already_roman():
    lines = ["dil-e-nadan tujhe hua kya hai"]
    pkg = mood_reel.package(lines, "Mirza Ghalib", hinglish_lines=lines)
    assert pkg["caption"] == "dil-e-nadan tujhe hua kya hai\n\n— Mirza Ghalib"
    assert pkg["caption"].count(lines[0]) == 1
