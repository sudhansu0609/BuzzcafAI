"""Visuals come from the recording; the clip share asked for is checked on the finished edit."""
from app.api import produce_api
from integrations.buzzedit_settings import achieved_mix
from integrations.visual_windows import build_window_prompt, script_reference_section

SCRIPT_PLAN = {"beats": [
    {"anchor": "Raat ke sawa do baje", "kind": "music_cue", "music": "dark ambient"},
    {"anchor": "night shift security guard", "kind": "broll_video", "prompt": "old government building at dusk"},
    {"anchor": "Uski maa ko dialysis chahiye", "kind": "broll_image", "prompt": "a prescription slip on a cracked wall"},
]}


class _Rec:
    def __init__(self):
        self.placed = []

    def place_script_beat(self, beat):
        self.placed.append(beat)
        return True


def test_only_the_scripts_music_cues_are_placed():
    rec = _Rec()
    assert produce_api._place_script_cues(rec, SCRIPT_PLAN) == 1
    assert [b["kind"] for b in rec.placed] == ["music_cue"]


def test_script_visuals_reach_the_take_planner_as_ideas_only():
    ref = script_reference_section(SCRIPT_PLAN)
    assert "reference only" in ref and "old government building at dusk" in ref
    assert "dark ambient" not in ref           # music cues are not scene ideas
    assert script_reference_section({"beats": []}) == ""

    class _W:
        index, start, end, word_start = 0, 0.0, 60.0, 0
        words = [{"word": "raat"}]
    prompt = build_window_prompt(_W(), [], "horror", None, [], 2.0, reference_section=ref)
    assert ref in prompt


def _timeline(items):
    return {"timeline": {"fps_num": 30, "fps_den": 1, "duration_frames": 3000,
                         "sources": [{"id": "rec", "path": "take.mp4"}, {"id": "c", "path": "a.mp4"},
                                     {"id": "s", "path": "b.png"}],
                         "items": items}}


def _item(track, source, start, end, origin="broll"):
    return {"kind": "media", "track": track, "source_id": source, "origin": origin, "enabled": True,
            "timeline_start_frame": start, "timeline_end_frame": end}


def test_the_mix_is_measured_on_the_final_timeline():
    mix = achieved_mix(_timeline([
        _item("V1", "rec", 0, 3000, origin="auto"),       # the recording itself
        _item("V3", "c", 0, 2100),                         # 70 s of clips
        _item("V3", "s", 2100, 2700),                      # 20 s of stills
        _item("V2", "rec", 0, 150, origin="coldopen"),     # not a cutaway
    ]))
    assert mix["video"] == 0.7 and mix["images"] == 0.2 and mix["clips"] == 1 and mix["stills"] == 1


def test_a_short_clip_share_is_reported(monkeypatch):
    import integrations.buzzedit_settings as bs
    monkeypatch.setattr(bs, "resolve_settings", lambda brand, o, p: ({}, None))
    monkeypatch.setattr(bs, "runtime_mix", lambda s: {"video": 0.7, "images": 0.2, "face": 0.1, "mode": "runtime"})

    class _Client:
        def get_project(self, _):
            return _timeline([_item("V3", "c", 0, 600)])  # 20 s of clips = 20%

    class _P:
        id, brand = "p", "Raat3Baje"
    report = {"generation": {"video_phase": {"planned": 30, "made": 8, "skipped_reason": "x"}}}
    mix, warning = produce_api._check_runtime_mix(_P(), _Client(), "b", report)
    assert mix["video"] == 0.2 and mix["target"]["video"] == 0.7
    assert warning and "20%" in warning and "70%" in warning and "8 of 30" in warning
