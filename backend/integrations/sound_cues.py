"""
Layer a dedicated SoundDesigner pass onto a take's visual plan: beyond the
`sounds` a PromptEngineer window call already cues alongside its pictures
(`integrations/visual_windows.py`), this second, focused pass asks
specifically for the scene's own sounds -- footsteps, a scream, a door, rain
-- `SPAN_WINDOWS` take windows at a time, so a persona built for this one job
gets a real look at the words rather than a few lines squeezed below a
picture-planning prompt.

Best-effort throughout, the same way `visual_windows.plan_window` is: a
provider error or a simulated (no-provider) reply fails only that span (never
the whole pass, never the production), and one repair retry follows a JSON
parse failure before the span is given up on.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from integrations import visual_windows
from integrations.visual_windows import SFX_CUE, Window, ensure_model_loaded_for

logger = logging.getLogger("buzzcaf_ai.sound_cues")

#: How many take windows one SoundDesigner call covers -- enough words to hear
#: a real scene, small enough to stay well inside a local model's read timeout.
SPAN_WINDOWS = 2

#: A second cue placed this close to one already accepted (of either kind) is
#: almost certainly the same real sound heard twice; dropped rather than kept.
DEDUPE_GAP_SECONDS = 2.0
#: Accents cue individual actions, not texture -- one every couple of seconds
#: reads as noise, not a scene. At most one per this many seconds.
ACCENT_MIN_GAP_SECONDS = 2.5


class SoundCuePlanError(Exception):
    """A span's raw model output could not be turned into cues."""


def _kept_sfx(beats: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [b for b in beats if isinstance(b, dict) and str(b.get("kind") or "").strip().lower() == SFX_CUE]


def _start(beat: Dict[str, Any]) -> float:
    try:
        return float(beat.get("start") or 0.0)
    except (TypeError, ValueError):
        return 0.0


_CUES_JSON_INSTRUCTION = """
### Required Output Format (JSON only)
Reply with a single JSON object and nothing else:

{"cues": [{"anchor": "exact words from the text", "effect": "diegetic sound, <= 8 words",
           "kind": "accent|bed", "level": "subtle|normal", "seconds": 3}]}

`anchor` must quote this passage's own words exactly. `{"cues": []}` when this
passage has no real sound to cue. Never music, whooshes, stingers or UI hits.
"""


def build_prompt(windows: Sequence[Window], existing: Sequence[Dict[str, Any]],
                 genre: str, genre_secondary: Optional[str]) -> str:
    """The prompt for one span: the genre, what is already cued in this exact
    passage (so the model does not repeat it), the passage's own words, and
    the JSON format reminder."""
    genre_line = f"Genre: {genre}" + (f" (secondary: {genre_secondary})" if genre_secondary else "") + "."
    indices = {w.index for w in windows}
    already = [b for b in _kept_sfx(existing) if b.get("window_index") in indices]
    if already:
        cued = "\n".join(f"Already cued (do not repeat): {b.get('effect')} on '{b.get('anchor')}'"
                         for b in already)
    else:
        cued = "(nothing cued yet in this passage)"
    words = "\n\n".join(f"Window {w.index}:\n{w.text}" for w in windows)
    return (
        f"{genre_line}\n\n"
        f"{cued}\n\n"
        f"### The words (quote anchors exactly)\n{words}\n\n"
        f"{_CUES_JSON_INSTRUCTION}"
    )


def parse_cues(raw: str, windows: Sequence[Window], kept_words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`raw`'s `cues` list turned into `sfx_cue` beats, each anchored against
    one of `windows`' own words (`visual_windows._sound_beats`) -- a cue
    anchors in exactly one window; one that matches none is dropped.

    `kept_words` is accepted for parity with `visual_windows.parse_window_beats`
    but is not needed here: each window already carries its own words.

    Raises `SoundCuePlanError` on anything unusable, so the caller can retry
    or give up on the span rather than silently planning nothing.
    """
    from integrations.llm import clean_json_response

    try:
        data = json.loads(clean_json_response(str(raw)))
    except (ValueError, TypeError) as exc:
        raise SoundCuePlanError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SoundCuePlanError("response was not a JSON object")
    cues = data.get("cues")
    if not isinstance(cues, list):
        raise SoundCuePlanError("response had no 'cues' list")

    beats: List[Dict[str, Any]] = []
    for window in windows:
        beats.extend(visual_windows._sound_beats(cues, window))
    return beats


def merge(existing_beats: Sequence[Dict[str, Any]], new_beats: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """`existing_beats` (every kind, untouched) plus each of `new_beats` that
    does not land within `DEDUPE_GAP_SECONDS` of an sfx cue already there --
    original or accepted earlier in this same call -- and, for an accent, not
    within `ACCENT_MIN_GAP_SECONDS` of another accepted accent either. Sorted
    by start, so a later caller can simply append more."""
    merged: List[Dict[str, Any]] = list(existing_beats)

    for beat in new_beats:
        start = _start(beat)
        sfx_so_far = _kept_sfx(merged)
        if any(abs(start - _start(other)) < DEDUPE_GAP_SECONDS for other in sfx_so_far):
            continue
        if str(beat.get("sfx_kind") or "").strip().lower() == "accent":
            accents = [b for b in sfx_so_far if str(b.get("sfx_kind") or "").strip().lower() == "accent"]
            if any(abs(start - _start(other)) < ACCENT_MIN_GAP_SECONDS for other in accents):
                continue
        merged.append(beat)

    merged.sort(key=_start)
    return merged


def _call(agent: Any, prompt: str) -> Tuple[str, bool]:
    raw = agent.execute(prompt, require_json=True)
    simulated = bool(getattr(agent.llm_service, "last_response_simulated", False))
    return str(raw), simulated


def _plan_span(agent: Any, span: Sequence[Window], existing: Sequence[Dict[str, Any]],
               kept_words: Sequence[Dict[str, Any]], genre: str,
               genre_secondary: Optional[str]) -> Tuple[bool, List[Dict[str, Any]], Optional[str]]:
    """One span: strict JSON, one repair retry on a parse failure, simulated
    output rejected outright -- the same shape as `visual_windows.plan_window`."""
    prompt = build_prompt(span, existing, genre, genre_secondary)

    try:
        raw, simulated = _call(agent, prompt)
    except Exception as exc:  # noqa: BLE001 - a provider error fails just this span
        return False, [], str(exc)
    if simulated:
        return False, [], "simulated content (no LLM provider reachable)"
    try:
        return True, parse_cues(raw, span, kept_words), None
    except SoundCuePlanError as exc:
        logger.info("sound_cues: span JSON parse failed (%s); retrying with a repair prompt.", exc)

    repair_prompt = (
        prompt + "\n\nYour previous answer could not be parsed as JSON. "
        "Return ONLY the JSON object described above -- no prose, no markdown code fences, no explanation."
    )
    try:
        raw, simulated = _call(agent, repair_prompt)
    except Exception as exc:  # noqa: BLE001
        return False, [], str(exc)
    if simulated:
        return False, [], "simulated content (no LLM provider reachable)"
    try:
        return True, parse_cues(raw, span, kept_words), None
    except SoundCuePlanError as exc:
        return False, [], str(exc)


def plan_sound_cues(agent: Any, windows: Sequence[Window], kept_words: Sequence[Dict[str, Any]],
                    beats: Sequence[Dict[str, Any]], genre: str, genre_secondary: Optional[str],
                    progress_cb: Optional[Any] = None) -> Dict[str, Any]:
    """The SoundDesigner's own pass over the whole take, `SPAN_WINDOWS` windows
    at a time: every accepted cue is merged into `beats` (every other kind
    passes through untouched), spaced from whatever is already there.

    Never raises -- a span that fails (a provider error, a simulated reply, or
    two bad JSON replies in a row) is recorded in `failed` and simply adds no
    cues; the production always gets back a usable (if unchanged) plan.
    """
    ensure_model_loaded_for(agent)
    spans = [list(windows[i:i + SPAN_WINDOWS]) for i in range(0, len(windows), SPAN_WINDOWS)]
    total = len(spans)
    merged = list(beats)
    before = len(_kept_sfx(merged))
    ok = 0
    failed: List[Dict[str, Any]] = []

    for n, span in enumerate(spans):
        if progress_cb:
            try:
                progress_cb(n, total)
            except Exception:  # noqa: BLE001 - status text must never end the pass
                pass
        success, new_beats, reason = _plan_span(agent, span, merged, kept_words, genre, genre_secondary)
        if not success:
            logger.warning("sound_cues: span %d failed (%s).", n, reason)
            failed.append({"span": n, "reason": reason or "unknown error"})
            continue
        ok += 1
        merged = merge(merged, new_beats)

    after = len(_kept_sfx(merged))
    return {"beats": merged, "added": after - before, "spans": total, "ok": ok, "failed": failed}
