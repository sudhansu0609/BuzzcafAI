"""
`integrations/sound_cues.py`: the SoundDesigner's own span-by-span pass that
layers extra `sfx_cue` beats onto a take's visual plan -- anchoring cues
against the take's own words, spacing new cues from whatever is already
there, and the same call/retry/simulated-reply discipline as
`visual_windows.plan_window`.
"""

import json

import pytest

from integrations import sound_cues
from integrations import visual_windows as vw


def _words(specs):
    """`specs`: list of (word, start, end)."""
    return [{"word": w, "start": s, "end": e} for w, s, e in specs]


def _windows():
    kept = _words([
        ("Woh", 0.0, 0.3), ("jungle", 0.4, 0.9), ("mein", 1.0, 1.2), ("bhaagne", 1.3, 1.8),
        ("laga,", 1.9, 2.3), ("baarish", 2.5, 3.0), ("ho", 3.1, 3.2), ("rahi", 3.3, 3.5), ("thi.", 3.6, 4.0),
    ])
    windows = vw.chunk_kept_words(kept, min_seconds=1000.0, max_seconds=1000.0)
    assert len(windows) == 1
    return windows, kept


class _FakeLLMService:
    def __init__(self):
        self.last_response_simulated = False


class _FakeAgent:
    """Stands in for a BaseAgent: `.execute()` returns queued answers in
    order, `.llm_service.last_response_simulated` flags the last one."""

    def __init__(self, answers):
        self._answers = list(answers)
        self.llm_service = _FakeLLMService()
        self.model_tier = "strong"
        self.calls = []

    def execute(self, prompt, require_json=False):
        self.calls.append(prompt)
        simulated, text = self._answers.pop(0)
        self.llm_service.last_response_simulated = simulated
        return text


# ------------------------------------------------------------- parse_cues


def test_parse_cues_returns_two_anchored_sfx_cue_beats():
    windows, kept = _windows()
    raw = json.dumps({"cues": [
        {"anchor": "bhaagne laga", "effect": "footsteps running on wet leaves", "kind": "accent",
         "level": "subtle", "seconds": 3},
        {"anchor": "baarish ho rahi thi", "effect": "steady rain on leaves", "kind": "bed", "seconds": 8},
    ]})

    beats = sound_cues.parse_cues(raw, windows, kept)

    assert [b["kind"] for b in beats] == ["sfx_cue", "sfx_cue"]
    accent, bed = beats
    assert accent["anchor"] == "bhaagne laga," and accent["start"] == pytest.approx(1.3)
    assert bed["anchor"] == "baarish ho rahi thi." and bed["start"] == pytest.approx(2.5)


def test_parse_cues_drops_a_cue_on_words_nobody_said():
    windows, kept = _windows()
    raw = json.dumps({"cues": [{"anchor": "words nobody said", "effect": "a door slams"}]})

    beats = sound_cues.parse_cues(raw, windows, kept)

    assert beats == []


def test_parse_cues_rejects_non_json():
    windows, kept = _windows()
    with pytest.raises(sound_cues.SoundCuePlanError):
        sound_cues.parse_cues("not json at all", windows, kept)


def test_parse_cues_rejects_missing_cues_list():
    windows, kept = _windows()
    with pytest.raises(sound_cues.SoundCuePlanError):
        sound_cues.parse_cues(json.dumps({"nope": []}), windows, kept)


# ------------------------------------------------------------------ merge


def test_merge_drops_a_new_cue_within_2s_of_an_existing_one_and_keeps_one_further_away():
    existing = [{"kind": "sfx_cue", "sfx_kind": "accent", "start": 10.0, "end": 10.5,
                 "effect": "a door", "anchor": "x", "level": "normal", "seconds": 2}]
    close = {"kind": "sfx_cue", "sfx_kind": "bed", "start": 11.0, "end": 11.4,
             "effect": "footsteps", "anchor": "y", "level": "normal", "seconds": 2}
    far = {"kind": "sfx_cue", "sfx_kind": "accent", "start": 20.0, "end": 20.4,
           "effect": "a scream", "anchor": "z", "level": "normal", "seconds": 2}

    merged = sound_cues.merge(existing, [close, far])

    assert close not in merged
    assert far in merged
    assert len(merged) == 2
    starts = [b["start"] for b in merged]
    assert starts == sorted(starts)


def test_merge_keeps_non_sfx_beats_untouched():
    existing = [{"kind": "broll_image", "start": 1.0, "image_prompt": "a lantern"}]
    new = [{"kind": "sfx_cue", "sfx_kind": "accent", "start": 5.0, "effect": "a scream", "anchor": "a",
            "level": "normal", "seconds": 2}]

    merged = sound_cues.merge(existing, new)

    assert existing[0] in merged
    assert new[0] in merged
    assert len(merged) == 2


# ------------------------------------------------------- plan_sound_cues


def test_simulated_reply_yields_no_beats_and_one_failed_span():
    windows, kept = _windows()
    agent = _FakeAgent([(True, json.dumps({"cues": []}))])

    result = sound_cues.plan_sound_cues(agent, windows, kept, [], "horror", None)

    assert result["beats"] == []
    assert result["added"] == 0
    assert result["spans"] == 1
    assert result["ok"] == 0
    assert len(result["failed"]) == 1
    assert "simulated" in result["failed"][0]["reason"]
    assert len(agent.calls) == 1  # no repair retry burned on a dead provider


def test_parse_failure_then_a_good_repair_reply_works():
    windows, kept = _windows()
    good = json.dumps({"cues": [{"anchor": "bhaagne laga", "effect": "footsteps running on wet leaves",
                                  "kind": "accent", "level": "subtle", "seconds": 3}]})
    agent = _FakeAgent([(False, "not json"), (False, good)])

    result = sound_cues.plan_sound_cues(agent, windows, kept, [], "horror", None)

    assert result["ok"] == 1
    assert result["failed"] == []
    assert len(result["beats"]) == 1
    assert result["added"] == 1
    assert len(agent.calls) == 2
    assert "ONLY the JSON object" in agent.calls[1]


def test_directive_for_renders_a_produced_sound_cue():
    from integrations import buzzedit_script

    windows, kept = _windows()
    good = json.dumps({"cues": [{"anchor": "bhaagne laga", "effect": "footsteps running on wet leaves",
                                  "kind": "accent", "level": "normal", "seconds": 3}]})
    agent = _FakeAgent([(False, good)])

    result = sound_cues.plan_sound_cues(agent, windows, kept, [], "horror", None)
    beat = result["beats"][0]

    assert buzzedit_script._directive_for(beat).strip() == \
        "[sfx: footsteps running on wet leaves | kind=accent | level=normal | seconds=3]"
