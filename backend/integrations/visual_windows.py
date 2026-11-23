"""
Replan visuals against the CUT take, not the pre-cut transcript.

Once BuzzEdit's auto-cut has run, `produce_api.py` must plan new visual beats
against what actually survived the cut -- not the ad-lib passages alone, and
not the full (including-removed-fumbles) transcript. This module:

1. Chunks the kept-word transcript into ~60-90s windows at a sentence or pause
   boundary (`chunk_kept_words`), so each LLM call is small enough to answer
   well inside the local model's read timeout -- the fix for the "180s read
   timeout on one big batch" failure mode is smaller units, not a longer
   timeout.
2. For each window, asks the PromptEngineer to place NEW beats only where
   coverage is short (the window text plus which script beats already landed
   in it are both in the prompt, so the model does not duplicate them).
3. Anchors beats by WORD INDEX RANGE within the window rather than a verbatim
   quote (small local models paraphrase a quote just enough to break exact
   matching); `parse_window_beats` converts that index range back to the
   actual spoken words and source timestamps.
4. Treats a provider's simulated/fixture fallback as a failure, never as a
   plan, and retries a JSON parse failure once with a "return only JSON"
   repair prompt before giving up on that window.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from integrations import effect_catalog

logger = logging.getLogger("buzzcaf_ai.visual_windows")

#: How many windows to plan at once per provider kind. The Claude proxy keeps
#: a pool of warm workers, so several windows go out together. LM Studio
#: batches parallel requests (4 slots by default) against one shared KV cache:
#: measured on the 5060 Ti with gemma-4-12b, one window took 22 s alone and
#: two together 14 s each, while a third bought nothing more and overflowed a
#: 16k context (hence `lm_studio_context_length`, 32k by default). Other local
#: servers stay sequential -- a queued request waits out its read timeout.
DEFAULT_PLAN_WORKERS = {"claude": 8, "gemini": 3, "openai": 3, "lm_studio": 2}
LOCAL_PLAN_WORKERS = 1

#: A window is closed once it has run at least this long AND sits on a
#: sentence/pause boundary...
MIN_WINDOW_SECONDS = 60.0
#: ...or unconditionally once it reaches this long, boundary or not, so one
#: run-on sentence never grows a window past what the model can read quickly.
MAX_WINDOW_SECONDS = 90.0
#: A gap to the next word at least this long counts as a pause boundary.
PAUSE_GAP_SECONDS = 0.5

_SENTENCE_END_RE = re.compile(r"[.!?][\"'’”)]*$")

#: The window-planning beat schema: the same fields/kinds `VISUAL_PLAN_JSON_
#: INSTRUCTION` (runtime/workflow.py) uses, except the anchor is a word index
#: range into the numbered list the prompt gives, not a verbatim quote.
WINDOW_JSON_INSTRUCTION = """
### Required Output Format (JSON only)
Reply with a single JSON object and nothing else:

{
  "beats": [
    {"word_start": 3, "word_end": 7,
     "kind": "<one kind from the Effect catalog below>",
     "image_prompt": "...", "video_prompt": "...", "negative_prompt": "...",
     "text": "...", "subtext": "...", "items": ["...", "..."], "number": 1,
     "caption": "...", "look": "...", "source": "...", "format": "web", "site": "...",
     "ticks": ["...", "..."], "active": 0, "place": "...", "data": {"value": 40, "suffix": "%"},
     "effect": "...", "intensity": 0.6, "duration": 0.5, "priority": 1.0, "seconds": 6}
  ],
  "sounds": [
    {"anchor": "exact words from this window where it happens",
     "effect": "footsteps running on wet leaves (<= 8 words, diegetic: what the scene would really sound like, never music)",
     "kind": "accent|bed", "level": "subtle|normal", "seconds": 3}
  ]
}

`word_start`/`word_end` are a 0-based, end-exclusive index range into the
NUMBERED WORD LIST below -- NOT a character offset and NOT a quoted phrase.
They say which spoken words on screen this beat belongs to. Keep spans short
(2-8 words). Only add a beat where "Already covered" below leaves a real gap;
do not repeat a beat for a moment already covered. Include only the fields
relevant to `kind` (the catalog below says which); leave the rest out rather
than inventing values. A beat whose required fields are missing is dropped.

Consecutive beats must show different subjects -- a different object, place,
action or detail -- never the same subject again from another angle. Name an
animal, creature or person only when the story's words in this window mention
it. A `broll_video` beat must run at least 5 seconds: set its `seconds` to 5-8.

`sounds` is optional: the real sounds of the scene, for the mix engineer. Cue
every real sound of the scene: an `accent` on each action (footsteps, a door,
a scream), one accent per action, never two for the same one, and a `bed` for weather,
insects, engines or a crowd. A `bed` (rain, wind, insects, an engine idling)
runs for the stretch it belongs to; an `accent` sits on the word where the
thing happens. `anchor` quotes this window's words exactly. Never music.
Speech is always on top, so the mix engineer decides the level.
"""

#: A window `sounds` entry becomes a beat of this kind (`[sfx: ...]` in the
#: script, placed on the spoken line like a music cue). Not a picture.
SFX_CUE = "sfx_cue"
SFX_KINDS = ("accent", "bed")
SFX_LEVELS = ("subtle", "normal")
SFX_MAX_WORDS = 8
#: Shortest generated clip: a `broll_video` beat runs at least this long.
MIN_VIDEO_SECONDS = 5.0
_TOKEN_RE = re.compile(r"[\w\u0900-\u097f]+")

#: Fields (in priority order) a beat's user-facing "what to generate" text is
#: read from, for the frontend's editable prompt box and for the repair/hint
#: previews below.
_PROMPT_FIELDS = ("image_prompt", "video_prompt", "text", "place", "effect")

#: kind -> which field an edited `prompt` value is written back into on
#: placement (`apply_plan_edits`). Falls back to "text" for any kind not
#: listed (every card/chart/quote kind reads "text" as its base label).
_KIND_PROMPT_FIELD = {
    "broll_image": "image_prompt",
    "broll_video": "video_prompt",
    "own_clip": "video_prompt",
    "canvas_card": "image_prompt",
    "map": "place",
    "fx": "effect",
    "atmos": "effect",
    "transition": "effect",
    "pill_labels": "items",
}


def prompt_text_for(beat: Dict[str, Any]) -> str:
    """The single editable string the frontend shows for a beat, whichever
    underlying field it actually came from. A sound cue has none."""
    if str(beat.get("kind") or "").lower() == SFX_CUE:
        return ""
    if isinstance(beat.get("items"), list) and beat.get("items"):
        return "; ".join(str(i) for i in beat["items"])
    for key in _PROMPT_FIELDS:
        value = beat.get(key)
        if value:
            return str(value)
    return ""


def apply_prompt_edit(beat: Dict[str, Any], prompt: str) -> Dict[str, Any]:
    """`beat` with an edited `prompt` string folded back into the field it
    reads from for placement (`_directive_for` in buzzedit_script.py). A
    sound cue has no prompt and is left as it is."""
    beat = dict(beat)
    if str(beat.get("kind") or "").lower() == SFX_CUE:
        return beat
    field_name = _KIND_PROMPT_FIELD.get(str(beat.get("kind") or "").lower(), "text")
    if field_name == "items":
        beat["items"] = [p.strip() for p in prompt.split(";") if p.strip()]
    else:
        beat[field_name] = prompt
    return beat


def beats_per_minute_target(settings: Dict[str, Any]) -> float:
    """How many new visual beats per minute this density calls for, derived
    from `target_coverage` (the share of runtime that should carry a visual)
    and this density's average B-roll beat length -- both already resolved
    per-brand/per-project by `resolve_settings` (buzzedit_settings.py)."""
    try:
        avg_broll = (float(settings.get("broll_seconds_min", 2.0)) +
                     float(settings.get("broll_seconds_max", 3.5))) / 2.0
        coverage = float(settings.get("target_coverage", 0.5))
    except (TypeError, ValueError):
        return 0.0
    if avg_broll <= 0:
        return 0.0
    return round((coverage * 60.0) / avg_broll, 2)


@dataclass
class Window:
    index: int
    word_start: int  # inclusive, index into the kept-words list
    word_end: int  # exclusive
    start: float  # source seconds
    end: float
    words: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(str(w.get("word") or w.get("text") or "") for w in self.words)

    def as_status(self) -> Dict[str, Any]:
        return {"index": self.index, "word_start": self.word_start, "word_end": self.word_end,
                "start": self.start, "end": self.end}


def _is_boundary(word: Dict[str, Any], next_word: Optional[Dict[str, Any]]) -> bool:
    text = str(word.get("word") or word.get("text") or "").strip()
    if _SENTENCE_END_RE.search(text):
        return True
    if next_word is not None:
        try:
            gap = float(next_word.get("start") or 0.0) - float(word.get("end") or 0.0)
        except (TypeError, ValueError):
            gap = 0.0
        if gap >= PAUSE_GAP_SECONDS:
            return True
    return False


def chunk_kept_words(
    words: Sequence[Dict[str, Any]],
    min_seconds: float = MIN_WINDOW_SECONDS,
    max_seconds: float = MAX_WINDOW_SECONDS,
) -> List[Window]:
    """The kept-word transcript, split into windows of `min_seconds` to
    `max_seconds` (source time), each closed on a sentence end or a pause of
    at least `PAUSE_GAP_SECONDS` once the window is already long enough --
    never mid-sentence unless a window would otherwise run past `max_seconds`."""
    windows: List[Window] = []
    n = len(words)
    i = 0
    while i < n:
        start_idx = i
        start_time = float(words[start_idx].get("start") or 0.0)
        j = start_idx
        end_idx = n - 1
        while j < n:
            word = words[j]
            try:
                duration = float(word.get("end") or 0.0) - start_time
            except (TypeError, ValueError):
                duration = 0.0
            next_word = words[j + 1] if j + 1 < n else None
            if duration >= max_seconds:
                end_idx = j
                break
            if duration >= min_seconds and _is_boundary(word, next_word):
                end_idx = j
                break
            j += 1
        else:
            end_idx = n - 1
        window_words = list(words[start_idx:end_idx + 1])
        windows.append(Window(
            index=len(windows),
            word_start=start_idx,
            word_end=end_idx + 1,
            start=start_time,
            end=float(window_words[-1].get("end") or start_time) if window_words else start_time,
            words=window_words,
        ))
        i = end_idx + 1
    return windows


def hint_beats_for_window(window: Window, placed: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The already-placed script beats (`Reconciliation.placed`) that landed
    inside this window -- told to the model as "already covered" so it plans
    only the gaps, not a second beat for a line already illustrated."""
    return [p for p in placed if window.word_start <= int(p.get("at_word", -1)) < window.word_end]


def build_window_prompt(
    window: Window,
    hint_beats: Sequence[Dict[str, Any]],
    genre: str,
    genre_secondary: Optional[str],
    fx_palette: Sequence[str],
    bpm_target: float,
    music_direction: str = "",
    catalog_section: Optional[str] = None,
    reference_section: str = "",
) -> str:
    """`catalog_section`, when given, replaces the effect catalog and the
    genre's fx palette -- a story channel's planner sees only the kinds it
    may use (`story_visuals.planner_section`). `reference_section` lists the
    scenes the script planned before recording: ideas only, the recording
    decides (`script_reference_section`)."""
    numbered = "\n".join(f"{i}: {w.get('word') or w.get('text') or ''}" for i, w in enumerate(window.words))
    genre_line = f"Genre: {genre}" + (f" (secondary: {genre_secondary})" if genre_secondary else "") + "."
    if hint_beats:
        covered = "\n".join(f"- word {p.get('at_word') - window.word_start} ({p['at_word']}): "
                             f"{p.get('kind')} -- {p.get('hint') or ''}".rstrip(" -")
                             for p in hint_beats)
    else:
        covered = "(none yet in this window)"
    target_beats = max(0, round(bpm_target * (window.end - window.start) / 60.0))
    return (
        "This is a window of what the speaker actually said in the recording (after cuts), "
        "given as a NUMBERED WORD LIST. Plan new visuals only for moments that need one.\n\n"
        f"### Numbered word list (window {window.index})\n{numbered}\n\n"
        f"### Already covered in this window\n{covered}\n\n"
        f"### Target\nAbout {target_beats} new beat(s) for this ~{round(window.end - window.start)}s window, "
        "given this video's density -- fewer if there is nothing worth illustrating, never one for every line.\n\n"
        f"{WINDOW_JSON_INSTRUCTION}\n\n"
        + (f"{catalog_section}\n\n### This video's genre\n{genre_line}\n" if catalog_section else
           f"{effect_catalog.prompt_section(genre, genre_secondary)}\n\n"
           f"### This video's genre and effect palette\n{genre_line} "
           f"For `fx`/`atmos` beats favour these effects: {', '.join(fx_palette)}.\n")
        + (f"\n{music_direction}\n" if music_direction else "")
        + (f"\n{reference_section}\n" if reference_section else "")
    )


class WindowPlanError(Exception):
    """A window's raw model output could not be turned into beats."""


def _hold_video(beat: Dict[str, Any], window: Window) -> None:
    """A `broll_video` beat runs at least `MIN_VIDEO_SECONDS`; one starting
    too close to the window's end to hold that becomes a `broll_image`."""
    if window.end - float(beat.get("start") or 0.0) < MIN_VIDEO_SECONDS:
        beat["kind"] = "broll_image"
        if not beat.get("image_prompt"):
            beat["image_prompt"] = beat.get("video_prompt") or ""
        return
    try:
        seconds = float(beat.get("seconds") or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    beat["seconds"] = max(MIN_VIDEO_SECONDS, seconds)


def _tokens(text: Any) -> List[str]:
    return _TOKEN_RE.findall(str(text or "").lower())


def _sound_beats(raw_sounds: Any, window: Window) -> List[Dict[str, Any]]:
    """The window's `sounds` as `sfx_cue` beats, each anchored on the window's
    own words (verbatim, with their timestamps) like every other beat. A sound
    without an effect, or whose anchor is not in this window, is dropped."""
    if not isinstance(raw_sounds, list):
        return []
    tokens = [(i, t) for i, w in enumerate(window.words)
              for t in _tokens(w.get("word") or w.get("text") or "")]
    keys = [t for _, t in tokens]
    beats: List[Dict[str, Any]] = []
    for raw in raw_sounds:
        if not isinstance(raw, dict):
            continue
        effect = " ".join(str(raw.get("effect") or "").split()[:SFX_MAX_WORDS])
        wanted = _tokens(raw.get("anchor"))
        if not effect or not wanted:
            continue
        at = next((k for k in range(len(keys) - len(wanted) + 1) if keys[k:k + len(wanted)] == wanted), None)
        if at is None:
            logger.info("visual plan: dropped a sound (%s) not anchored in window %d", effect, window.index)
            continue
        span = window.words[tokens[at][0]:tokens[at + len(wanted) - 1][0] + 1]
        sfx_kind = str(raw.get("kind") or "").strip().lower()
        level = str(raw.get("level") or "").strip().lower()
        try:
            seconds = float(raw.get("seconds"))
        except (TypeError, ValueError):
            seconds = 0.0
        beats.append({
            "kind": SFX_CUE,
            "anchor": " ".join(str(w.get("word") or w.get("text") or "") for w in span).strip(),
            "effect": effect,
            "sfx_kind": sfx_kind if sfx_kind in SFX_KINDS else "accent",
            "level": level if level in SFX_LEVELS else "normal",
            "seconds": seconds if seconds > 0 else 3.0,
            "start": float(span[0].get("start") or window.start),
            "end": float(span[-1].get("end") or window.end),
            "window_index": window.index,
            "prompt": "",
        })
    return beats


def parse_window_beats(raw_text: str, window: Window, kept_words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The model's raw JSON text -> beats anchored against `kept_words` (the
    same list `window` was cut from), each with a verbatim `anchor`
    (`Reconciliation.place_transcript_beat` needs a real quote) plus `start`/
    `end` source timestamps and a `prompt` field for the review UI.

    Raises `WindowPlanError` on anything unusable -- not a dict, no `beats`
    list, or every beat out of range -- so the caller can retry or fail the
    window rather than silently plan nothing.
    """
    from integrations.llm import clean_json_response

    try:
        data = json.loads(clean_json_response(str(raw_text)))
    except (ValueError, TypeError) as exc:
        raise WindowPlanError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise WindowPlanError("response was not a JSON object")
    raw_beats = data.get("beats")
    if not isinstance(raw_beats, list):
        raise WindowPlanError("response had no 'beats' list")

    window_len = len(window.words)
    beats: List[Dict[str, Any]] = []
    for raw in raw_beats:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        if not kind:
            continue
        try:
            local_start = int(raw.get("word_start"))
            local_end = int(raw.get("word_end"))
        except (TypeError, ValueError):
            continue
        local_start = max(0, min(local_start, window_len))
        local_end = max(local_start + 1, min(local_end, window_len))
        if local_start >= window_len:
            continue
        global_start = window.word_start + local_start
        global_end = window.word_start + local_end
        span_words = kept_words[global_start:global_end]
        anchor = " ".join(str(w.get("word") or w.get("text") or "") for w in span_words).strip()
        if not anchor:
            continue
        beat = dict(raw)
        beat.pop("word_start", None)
        beat.pop("word_end", None)
        beat["kind"] = kind
        beat["anchor"] = " ".join(str(w.get("word") or w.get("text") or "") for w in span_words).strip()
        beat, dropped_because = effect_catalog.normalize_beat(beat)
        if beat is None:
            logger.info("visual plan: dropped a %s beat (%s)", kind, dropped_because)
            continue
        kind = beat["kind"]
        beat["anchor"] = anchor
        beat["start"] = float(span_words[0].get("start") or window.start)
        beat["end"] = float(span_words[-1].get("end") or window.end)
        beat["window_index"] = window.index
        if kind == "broll_video":
            _hold_video(beat, window)
        beat["prompt"] = prompt_text_for(beat)
        beats.append(beat)
    beats.extend(_sound_beats(data.get("sounds"), window))
    return beats


@dataclass
class WindowResult:
    window: Window
    ok: bool
    beats: List[Dict[str, Any]] = field(default_factory=list)
    reason: Optional[str] = None
    repaired: bool = False


def plan_window(
    agent: Any,
    window: Window,
    hint_beats: Sequence[Dict[str, Any]],
    kept_words: Sequence[Dict[str, Any]],
    genre: str,
    genre_secondary: Optional[str],
    fx_palette: Sequence[str],
    bpm_target: float,
    music_direction: str = "",
    catalog_section: Optional[str] = None,
    reference_section: str = "",
) -> WindowResult:
    """Plan one window: strict JSON, one repair retry on a parse failure,
    simulated output rejected outright (retrying it would not help -- no
    provider was reachable at all)."""
    prompt = build_window_prompt(window, hint_beats, genre, genre_secondary, fx_palette, bpm_target,
                                 music_direction, catalog_section, reference_section)

    def _call(text: str) -> Tuple[str, bool]:
        raw = agent.execute(text, require_json=True)
        simulated = bool(getattr(agent.llm_service, "last_response_simulated", False))
        return str(raw), simulated

    try:
        raw, simulated = _call(prompt)
    except Exception as exc:  # noqa: BLE001 - a provider error fails just this window
        logger.warning("visual_windows: window %d call failed (%s).", window.index, exc)
        return WindowResult(window=window, ok=False, reason=str(exc))

    if simulated:
        logger.warning("visual_windows: window %d got simulated output (no provider reachable); failing window.",
                        window.index)
        return WindowResult(window=window, ok=False, reason="simulated content (no LLM provider reachable)")

    try:
        beats = parse_window_beats(raw, window, kept_words)
        return WindowResult(window=window, ok=True, beats=beats)
    except WindowPlanError as exc:
        logger.info("visual_windows: window %d JSON parse failed (%s); retrying with a repair prompt.",
                     window.index, exc)

    repair_prompt = (
        prompt + "\n\nYour previous answer could not be parsed as JSON. "
        "Return ONLY the JSON object described above -- no prose, no markdown code fences, no explanation."
    )
    try:
        raw, simulated = _call(repair_prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("visual_windows: window %d repair call failed (%s).", window.index, exc)
        return WindowResult(window=window, ok=False, reason=str(exc), repaired=True)

    if simulated:
        return WindowResult(window=window, ok=False, reason="simulated content (no LLM provider reachable)",
                             repaired=True)
    try:
        beats = parse_window_beats(raw, window, kept_words)
        return WindowResult(window=window, ok=True, beats=beats, repaired=True)
    except WindowPlanError as exc:
        logger.warning("visual_windows: window %d failed after repair retry (%s).", window.index, exc)
        return WindowResult(window=window, ok=False, reason=str(exc), repaired=True)


def ensure_model_loaded_for(agent: Any) -> None:
    """Best-effort: make sure a local model is actually resident before the
    window loop starts, rather than paying a cold-load on window 1's call.
    Never fatal -- planning still proceeds and just eats that first load."""
    try:
        from integrations.llm import LOCAL_PROVIDERS, ensure_local_model_loaded

        llm = agent.llm_service
        provider = (llm._provider_order(agent.model_tier) or [None])[0]
        if provider in LOCAL_PROVIDERS:
            ensure_local_model_loaded(provider, llm._model_for(provider, agent.model_tier))
    except Exception as exc:  # noqa: BLE001
        logger.debug("visual_windows: ensure_model_loaded_for skipped (%s).", exc)


#: Spare VRAM a second parallel local window needs once the model is
#: loaded: a real window prompt is ~12k tokens, and two of them beside a
#: starved card crashed LM Studio's engine mid-answer ("terminated").
PARALLEL_HEADROOM_MIB = 3072


def parallel_fits(agent: Any) -> bool:
    """False when a local model would plan windows in parallel but Sentinel
    says the card lacks the headroom. True for remote providers, and when
    Sentinel cannot be asked (the retry pass still catches failures)."""
    try:
        from integrations.llm import LOCAL_PROVIDERS

        provider = (agent.llm_service._provider_order(getattr(agent, "model_tier", None)) or [None])[0]
        if provider not in LOCAL_PROVIDERS:
            return True
        from integrations.sentinel_client import client as sentinel_client

        granted, details = sentinel_client().query(mib=PARALLEL_HEADROOM_MIB)
        if not granted:
            logger.info("visual_windows: planning one window at a time -- %s",
                        details.get("reason") or "not enough free VRAM for two")
        return bool(granted)
    except Exception as exc:  # noqa: BLE001
        logger.debug("visual_windows: VRAM headroom check skipped (%s).", exc)
        return True


def workers_for(agent: Any) -> int:
    """How many windows may be in flight for the provider `agent` will hit
    first: parallel for the Claude proxy and cloud APIs, one at a time for a
    local model (see DEFAULT_PLAN_WORKERS)."""
    try:
        llm = agent.llm_service
        provider = (llm._provider_order(getattr(agent, "model_tier", None)) or [None])[0]
    except Exception:  # noqa: BLE001 - a fake agent in tests has no provider order
        return LOCAL_PLAN_WORKERS
    return DEFAULT_PLAN_WORKERS.get(provider or "", LOCAL_PLAN_WORKERS)


def plan_visual_windows(
    agent: Any,
    windows: Sequence[Window],
    kept_words: Sequence[Dict[str, Any]],
    placed: Sequence[Dict[str, Any]],
    genre: str,
    genre_secondary: Optional[str],
    fx_palette: Sequence[str],
    bpm_target: float,
    progress_cb: Optional[Any] = None,
    workers: int = 1,
    agent_factory: Optional[Callable[[], Any]] = None,
    music_direction: str = "",
    catalog_section: Optional[str] = None,
    reference_section: str = "",
) -> Dict[str, Any]:
    """Plan every window, returning the combined beats plus a status block:
    `{"beats": [...], "windows": n, "ok": n, "failed": [{"window_index", "reason"}, ...]}`.

    `workers` > 1 plans that many windows concurrently. A BaseAgent (and its
    LLMService, whose `last_response_simulated` flag `plan_window` reads
    right after each call) is not thread-safe, so a parallel run gives every
    worker thread its own agent from `agent_factory`; without a factory the
    shared `agent` is used and the run stays sequential. Beats come back in
    window order either way, and `progress_cb(done, total)` counts finished
    windows rather than started ones.
    """
    ensure_model_loaded_for(agent)
    if workers > 1 and not parallel_fits(agent):
        workers = 1
    total = len(windows)
    hints_by_window = [hint_beats_for_window(window, placed) for window in windows]

    def _one(agent_for_call: Any, n: int) -> WindowResult:
        window = windows[n]
        return plan_window(agent_for_call, window, hints_by_window[n], kept_words,
                           genre, genre_secondary, fx_palette, bpm_target, music_direction,
                           catalog_section, reference_section)

    results: List[Optional[WindowResult]] = [None] * total
    if workers <= 1 or total <= 1 or agent_factory is None:
        for n in range(total):
            if progress_cb:
                progress_cb(n, total)
            results[n] = _one(agent, n)
    else:
        local = threading.local()
        done_lock = threading.Lock()
        done = 0

        def _run(n: int) -> None:
            nonlocal done
            if not hasattr(local, "agent"):
                local.agent = agent_factory()
            results[n] = _one(local.agent, n)
            with done_lock:
                done += 1
                if progress_cb:
                    progress_cb(done - 1, total)

        # Each window runs in the caller's context, so the step's model route
        # (llm.llm_job) reaches the worker threads too.
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=min(workers, total), thread_name_prefix="visual-plan") as pool:
            list(pool.map(lambda n: ctx.copy().run(_run, n), range(total)))

        # Parallel calls share the model's KV cache; under VRAM pressure LM
        # Studio fails them ("failed to decode") and the fallback chain ends
        # in simulated output. One sequential pass over just those windows
        # usually fits where two at once did not.
        retry = [n for n, r in enumerate(results) if r is None or not r.ok]
        if retry:
            logger.info("visual_windows: retrying %d failed window(s) one at a time.", len(retry))
            for n in retry:
                again = _one(agent, n)
                if again.ok:
                    results[n] = again

    all_beats: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    ok = 0
    for window, result in zip(windows, results):
        if result is not None and result.ok:
            ok += 1
            all_beats.extend(result.beats)
        else:
            reason = (result.reason if result is not None else None) or "unknown error"
            failed.append({"window_index": window.index, "reason": reason})

    # Windows are planned independently, so a designed effect can repeat
    # across a window boundary; the catalog's per-kind gaps decide.
    all_beats = effect_catalog.space_beats(all_beats)
    return {"beats": all_beats, "windows": total, "ok": ok, "failed": failed}


def script_reference_section(visual_plan: Dict[str, Any], limit: int = 30, chars: int = 110) -> str:
    """The script's pre-recording visual plan as a short idea list for the
    take planner. The recording is the source of truth: these are never
    placed as they are, only offered where the speaker says that thing."""
    lines = []
    for beat in (visual_plan or {}).get("beats") or []:
        if not isinstance(beat, dict) or str(beat.get("kind") or "").lower() == SFX_CUE:
            continue
        idea = str(beat.get("prompt") or beat.get("image_prompt") or beat.get("hint")
                   or beat.get("topic") or beat.get("description") or "").strip()
        said = str(beat.get("anchor") or beat.get("quote") or beat.get("line") or "").strip()
        if not idea:
            continue
        idea = " ".join(idea.split())[:chars]
        lines.append(f"- {idea}" + (f'  (for: "{" ".join(said.split())[:60]}")' if said else ""))
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    return ("### Scene ideas from the script (reference only)\n"
            "Written before the recording. Use one ONLY where the speaker actually says that moment in "
            "this window, and match what he says, not the script. Most windows will use few or none.\n"
            + "\n".join(lines))
