"""
`integrations/visual_windows.py`: chunking the kept-word transcript into
windows at sentence/pause boundaries, converting a model's index-anchored
beats back to verbatim quotes and timestamps, the repair-retry path on a bad
JSON response, and rejecting a provider's simulated fallback as a plan.
"""

import json

import pytest

from integrations import visual_windows as vw


def _words(specs):
    """`specs`: list of (word, start, end)."""
    return [{"word": w, "start": s, "end": e} for w, s, e in specs]


# --------------------------------------------------------------- chunking


def test_chunk_kept_words_closes_on_a_sentence_boundary_past_min_seconds():
    # Words 0..70, one per second; a "." on word 62 (62s in, past the 60s
    # minimum) is the first sentence end the chunker can close on.
    specs = [(f"w{i}", float(i), float(i) + 0.8) for i in range(70)]
    text, s, e = specs[62]
    specs[62] = ("w62.", s, e)
    words = _words(specs)

    windows = vw.chunk_kept_words(words, min_seconds=60.0, max_seconds=90.0)

    assert windows[0].word_start == 0
    assert windows[0].word_end == 63  # inclusive of the "w62." sentence end
    assert windows[1].word_start == 63


def test_chunk_kept_words_closes_on_a_pause_boundary_past_min_seconds():
    specs = [(f"w{i}", float(i), float(i) + 0.8) for i in range(70)]
    # A 0.6s gap after word 61 (61.8 -> 62.4): a pause boundary at/after 60s.
    specs[62] = ("w62", specs[61][2] + 0.6, specs[61][2] + 0.6 + 0.8)
    words = _words(specs)

    windows = vw.chunk_kept_words(words, min_seconds=60.0, max_seconds=90.0)

    assert windows[0].word_end == 62  # closes AT word 61 (index 61), before the gap
    assert windows[1].word_start == 62


def test_chunk_kept_words_forces_a_cut_at_max_seconds_mid_sentence():
    # No punctuation, no pause anywhere -- one long run-on sentence.
    specs = [(f"w{i}", float(i), float(i) + 1.0) for i in range(200)]
    words = _words(specs)

    windows = vw.chunk_kept_words(words, min_seconds=60.0, max_seconds=90.0)

    assert windows[0].end - windows[0].start <= 90.0
    assert windows[0].end - windows[0].start >= 89.0
    # Every window (but the last) hit the hard cap, not a boundary.
    assert len(windows) > 2


def test_chunk_kept_words_last_window_takes_the_remainder():
    specs = [(f"w{i}", float(i), float(i) + 0.8) for i in range(10)]  # ~8s total
    words = _words(specs)

    windows = vw.chunk_kept_words(words, min_seconds=60.0, max_seconds=90.0)

    assert len(windows) == 1
    assert windows[0].word_start == 0
    assert windows[0].word_end == 10


def test_chunk_kept_words_empty_input():
    assert vw.chunk_kept_words([]) == []


# ------------------------------------------------------- beats per minute


def test_beats_per_minute_target_scales_with_coverage_and_broll_length():
    calm = vw.beats_per_minute_target(
        {"target_coverage": 0.30, "broll_seconds_min": 2.5, "broll_seconds_max": 4.0})
    busy = vw.beats_per_minute_target(
        {"target_coverage": 0.65, "broll_seconds_min": 2.0, "broll_seconds_max": 3.0})
    assert busy > calm
    assert calm > 0


def test_beats_per_minute_target_zero_broll_length_is_safe():
    assert vw.beats_per_minute_target({"target_coverage": 0.5, "broll_seconds_min": 0, "broll_seconds_max": 0}) == 0.0


# --------------------------------------------------- index -> quote/anchor


def _sample_window(kept_words):
    windows = vw.chunk_kept_words(kept_words, min_seconds=1000.0, max_seconds=1000.0)
    assert len(windows) == 1
    return windows[0]


def test_parse_window_beats_converts_local_index_to_verbatim_anchor_and_timestamps():
    kept = _words([("Hello", 0.0, 0.4), ("world", 0.5, 0.9), ("welcome", 1.0, 1.5),
                    ("to", 1.6, 1.7), ("the", 1.8, 1.9), ("show", 2.0, 2.5)])
    window = _sample_window(kept)
    raw = json.dumps({"beats": [
        {"word_start": 2, "word_end": 6, "kind": "broll_image", "image_prompt": "a stage lighting up"},
    ]})

    beats = vw.parse_window_beats(raw, window, kept)

    assert len(beats) == 1
    beat = beats[0]
    assert beat["anchor"] == "welcome to the show"
    assert beat["kind"] == "broll_image"
    assert beat["start"] == pytest.approx(1.0)
    assert beat["end"] == pytest.approx(2.5)
    assert beat["prompt"] == "a stage lighting up"
    assert "word_start" not in beat and "word_end" not in beat


def test_parse_window_beats_clamps_out_of_range_indices():
    kept = _words([("a", 0.0, 0.1), ("b", 0.2, 0.3), ("c", 0.4, 0.5)])
    window = _sample_window(kept)
    raw = json.dumps({"beats": [{"word_start": -5, "word_end": 999, "kind": "fx", "effect": "flicker"}]})

    beats = vw.parse_window_beats(raw, window, kept)

    assert len(beats) == 1
    assert beats[0]["anchor"] == "a b c"


def test_parse_window_beats_skips_beats_with_no_kind_or_bad_indices():
    kept = _words([("a", 0.0, 0.1), ("b", 0.2, 0.3)])
    window = _sample_window(kept)
    raw = json.dumps({"beats": [
        {"word_start": 0, "word_end": 1},  # no kind
        {"kind": "fx"},  # no indices
        {"word_start": 0, "word_end": 1, "kind": "fx", "effect": "flicker"},
    ]})

    beats = vw.parse_window_beats(raw, window, kept)

    assert len(beats) == 1
    assert beats[0]["kind"] == "fx"


def test_parse_window_beats_rejects_non_json():
    kept = _words([("a", 0.0, 0.1)])
    window = _sample_window(kept)
    with pytest.raises(vw.WindowPlanError):
        vw.parse_window_beats("not json at all", window, kept)


def test_parse_window_beats_rejects_missing_beats_list():
    kept = _words([("a", 0.0, 0.1)])
    window = _sample_window(kept)
    with pytest.raises(vw.WindowPlanError):
        vw.parse_window_beats(json.dumps({"nope": []}), window, kept)


def test_apply_prompt_edit_writes_back_into_the_kind_specific_field():
    beat = {"kind": "broll_video", "video_prompt": "old"}
    edited = vw.apply_prompt_edit(beat, "new prompt")
    assert edited["video_prompt"] == "new prompt"
    assert beat["video_prompt"] == "old"  # not mutated in place


def test_apply_prompt_edit_falls_back_to_text_field():
    beat = {"kind": "quote_card", "text": "old"}
    edited = vw.apply_prompt_edit(beat, "new")
    assert edited["text"] == "new"


# --------------------------------------------------------------- hints


def test_hint_beats_for_window_filters_by_word_range():
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(10)])
    windows = vw.chunk_kept_words(kept, min_seconds=1.0, max_seconds=2.0)
    placed = [{"kind": "broll_image", "at_word": 0, "hint": "in window 0"},
              {"kind": "map", "at_word": 9, "hint": "in a later window"}]

    hints = vw.hint_beats_for_window(windows[0], placed)

    assert len(hints) == 1
    assert hints[0]["hint"] == "in window 0"


# ---------------------------------------------------- reliability / retry


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


def _window():
    kept = _words([("Hello", 0.0, 0.4), ("world", 0.5, 0.9), ("welcome", 1.0, 1.5)])
    return _sample_window(kept), kept


def test_plan_window_success_on_first_try():
    window, kept = _window()
    good = json.dumps({"beats": [{"word_start": 0, "word_end": 2, "kind": "fx", "effect": "flicker"}]})
    agent = _FakeAgent([(False, good)])

    result = vw.plan_window(agent, window, [], kept, "horror", None, ["flicker", "shake"], 1.0)

    assert result.ok is True
    assert len(result.beats) == 1
    assert result.repaired is False
    assert len(agent.calls) == 1


def test_plan_window_retries_once_on_bad_json_then_succeeds():
    window, kept = _window()
    good = json.dumps({"beats": [{"word_start": 0, "word_end": 1, "kind": "fx", "effect": "shake"}]})
    agent = _FakeAgent([(False, "not json"), (False, good)])

    result = vw.plan_window(agent, window, [], kept, "horror", None, ["shake"], 1.0)

    assert result.ok is True
    assert result.repaired is True
    assert len(agent.calls) == 2
    assert "ONLY the JSON object" in agent.calls[1]


def test_plan_window_fails_after_repair_also_bad():
    window, kept = _window()
    agent = _FakeAgent([(False, "not json"), (False, "still not json")])

    result = vw.plan_window(agent, window, [], kept, "horror", None, [], 1.0)

    assert result.ok is False
    assert result.repaired is True
    assert result.beats == []


def test_plan_window_rejects_simulated_content_without_wasting_a_retry():
    window, kept = _window()
    agent = _FakeAgent([(True, json.dumps({"beats": []}))])

    result = vw.plan_window(agent, window, [], kept, "horror", None, [], 1.0)

    assert result.ok is False
    assert "simulated" in result.reason
    assert len(agent.calls) == 1  # no repair retry burned on a dead provider


def test_plan_visual_windows_aggregates_ok_and_failed():
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(4)])
    windows = vw.chunk_kept_words(kept, min_seconds=0.5, max_seconds=1.0)
    assert len(windows) >= 2

    good = json.dumps({"beats": [{"word_start": 0, "word_end": 1, "kind": "fx", "effect": "flicker"}]})
    # First window succeeds, the rest fail (bad JSON, repair also bad).
    answers = [(False, good)] + [(False, "bad"), (False, "still bad")] * (len(windows) - 1)
    agent = _FakeAgent(answers)

    result = vw.plan_visual_windows(agent, windows, kept, [], "horror", None, ["flicker"], 1.0)

    assert result["windows"] == len(windows)
    assert result["ok"] == 1
    assert len(result["failed"]) == len(windows) - 1
    assert len(result["beats"]) == 1


# ------------------------------------------------------ parallel planning
#
# `workers` > 1 plans windows concurrently -- one agent per worker thread from
# `agent_factory` -- and still returns beats in window order.


class _AlwaysGoodAgent:
    """Answers one valid beat for whatever window it is asked about."""

    created = 0

    def __init__(self):
        _AlwaysGoodAgent.created += 1
        self.llm_service = _FakeLLMService()
        self.model_tier = "strong"

    def execute(self, prompt, require_json=False):
        return json.dumps({"beats": [{"word_start": 0, "word_end": 1, "kind": "fx", "effect": "flicker"}]})


def test_plan_visual_windows_parallel_keeps_window_order_and_counts_finished_windows():
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(12)])
    windows = vw.chunk_kept_words(kept, min_seconds=0.5, max_seconds=1.0)
    assert len(windows) >= 4
    _AlwaysGoodAgent.created = 0
    progress = []

    result = vw.plan_visual_windows(
        _AlwaysGoodAgent(), windows, kept, [], "horror", None, ["flicker"], 1.0,
        progress_cb=lambda n, total: progress.append((n, total)),
        workers=3, agent_factory=_AlwaysGoodAgent,
    )

    assert result["ok"] == len(windows) and result["failed"] == []
    # One beat per window, in window order (each beat anchors that window's first word).
    starts = [b["start"] for b in result["beats"]]
    assert starts == sorted(starts)
    assert len(starts) == len(windows)
    # Progress counts finished windows 0..n-1, each exactly once.
    assert sorted(progress) == [(n, len(windows)) for n in range(len(windows))]
    # The shared agent plus at most one per worker thread.
    assert 2 <= _AlwaysGoodAgent.created <= 4


def test_plan_visual_windows_stays_sequential_without_an_agent_factory():
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(4)])
    windows = vw.chunk_kept_words(kept, min_seconds=0.5, max_seconds=1.0)
    good = json.dumps({"beats": [{"word_start": 0, "word_end": 1, "kind": "fx", "effect": "flicker"}]})
    agent = _FakeAgent([(False, good)] * len(windows))

    result = vw.plan_visual_windows(agent, windows, kept, [], "horror", None, ["flicker"], 1.0, workers=4)

    assert result["ok"] == len(windows)
    assert len(agent.calls) == len(windows)


class _ProviderAgent:
    def __init__(self, provider):
        self.model_tier = "strong"
        self.llm_service = type("Svc", (), {"_provider_order": lambda self, tier: [provider]})()


def test_workers_for_is_parallel_for_the_claude_proxy_and_one_for_a_local_model():
    assert vw.workers_for(_ProviderAgent("claude")) == vw.DEFAULT_PLAN_WORKERS["claude"]
    assert vw.workers_for(_ProviderAgent("lm_studio")) == 2  # LM Studio batches parallel slots
    assert vw.workers_for(_ProviderAgent("llamacpp")) == 1
    assert vw.workers_for(_FakeAgent([])) == 1  # no provider order at all


class _SimulatedAgent(_AlwaysGoodAgent):
    """A worker whose every call falls through to simulated output -- what a
    parallel window got when LM Studio could not fit two requests in VRAM."""

    def execute(self, prompt, require_json=False):
        self.llm_service.last_response_simulated = True
        return "{}"


def test_windows_that_fail_in_parallel_are_retried_one_at_a_time():
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(12)])
    windows = vw.chunk_kept_words(kept, min_seconds=0.5, max_seconds=1.0)

    result = vw.plan_visual_windows(
        _AlwaysGoodAgent(), windows, kept, [], "horror", None, ["flicker"], 1.0,
        workers=2, agent_factory=_SimulatedAgent,
    )

    # Every parallel call failed; the sequential retry on the shared agent saved them all.
    assert result["ok"] == len(windows) and result["failed"] == []


def test_tight_vram_plans_local_windows_one_at_a_time(monkeypatch):
    kept = _words([(f"w{i}", float(i), float(i) + 0.5) for i in range(12)])
    windows = vw.chunk_kept_words(kept, min_seconds=0.5, max_seconds=1.0)
    monkeypatch.setattr(vw, "parallel_fits", lambda agent: False)
    _AlwaysGoodAgent.created = 0

    result = vw.plan_visual_windows(
        _AlwaysGoodAgent(), windows, kept, [], "horror", None, ["flicker"], 1.0,
        workers=2, agent_factory=_AlwaysGoodAgent,
    )

    assert result["ok"] == len(windows)
    assert _AlwaysGoodAgent.created == 1  # only the shared agent: no worker threads


def test_parallel_fits_asks_sentinel_only_for_local_models(monkeypatch):
    import integrations.sentinel_client as sc

    asked = []
    monkeypatch.setattr(sc, "client", lambda: type("S", (), {
        "query": lambda self, mib: asked.append(mib) or (False, {"reason": "only 2001 MiB available"})})())
    assert vw.parallel_fits(_ProviderAgent("claude")) is True
    assert vw.parallel_fits(_ProviderAgent("lm_studio")) is False
    assert asked == [vw.PARALLEL_HEADROOM_MIB]


# ------------------------------------------------ clip length and sound cues


def test_broll_video_beats_run_at_least_five_seconds():
    kept = _words([(f"w{i}", float(i), i + 0.8) for i in range(20)])
    window = _sample_window(kept)
    raw = json.dumps({"beats": [
        {"word_start": 1, "word_end": 3, "kind": "broll_video", "video_prompt": "rain on a tin roof", "seconds": 2},
        {"word_start": 5, "word_end": 7, "kind": "broll_video", "video_prompt": "a jeep on a muddy road"},
        {"word_start": 17, "word_end": 19, "kind": "broll_video", "video_prompt": "lantern light on a wall"},
    ]})

    beats = vw.parse_window_beats(raw, window, kept)

    assert [b["kind"] for b in beats] == ["broll_video", "broll_video", "broll_image"]
    assert beats[0]["seconds"] >= 5.0 and beats[1]["seconds"] >= 5.0
    # 2.8 s left in the window: too short for a clip, so a still.
    assert beats[2]["image_prompt"] == "lantern light on a wall"


def test_window_sounds_become_sfx_cue_beats_and_sfx_directives():
    from integrations import buzzedit_script

    kept = _words([("Woh", 0.0, 0.3), ("jungle", 0.4, 0.9), ("mein", 1.0, 1.2), ("bhaagne", 1.3, 1.8),
                   ("laga,", 1.9, 2.3), ("baarish", 2.5, 3.0), ("ho", 3.1, 3.2), ("rahi", 3.3, 3.5),
                   ("thi.", 3.6, 4.0)])
    window = _sample_window(kept)
    raw = json.dumps({"beats": [], "sounds": [
        {"anchor": "bhaagne laga", "effect": "footsteps running on wet leaves", "kind": "accent",
         "level": "subtle", "seconds": 3},
        {"anchor": "baarish ho rahi thi", "effect": "steady rain on leaves", "kind": "bed", "seconds": 8},
        {"anchor": "words nobody said", "effect": "a door slams"},
    ]})

    beats = vw.parse_window_beats(raw, window, kept)

    assert [b["kind"] for b in beats] == ["sfx_cue", "sfx_cue"]
    accent, bed = beats
    assert accent["anchor"] == "bhaagne laga," and accent["start"] == pytest.approx(1.3)
    assert accent["prompt"] == "" and vw.apply_prompt_edit(accent, "a tiger") == accent
    assert buzzedit_script._directive_for(accent).strip() == \
        "[sfx: footsteps running on wet leaves | kind=accent | level=subtle | seconds=3]"
    assert buzzedit_script._directive_for(bed).strip() == \
        "[sfx: steady rain on leaves | kind=bed | level=normal | seconds=8]"
    annotated, skipped = buzzedit_script.to_directive_script(
        "Woh jungle mein bhaagne laga, baarish ho rahi thi.", {"beats": beats})
    assert not skipped and annotated.count("[sfx: ") == 2
    assert vw.script_reference_section({"beats": beats}) == ""
