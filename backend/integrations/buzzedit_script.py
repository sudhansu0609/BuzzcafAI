"""
Turn BuzzcafAI's `production/visual_plan.json` into a script annotated with
BuzzEdit's inline `[kind: arg]` directives (`BuzzEdit/backend/asr/script_align.py`).

BuzzEdit aligns each directive to the nearest word in the Whisper transcript
of your recording; this module's only job is placing each directive at the
right *text* position ahead of time -- word-level alignment happens later, on
BuzzEdit's side, once the recording exists. Spoken words are never touched:
every directive is spliced in by index, so nothing outside a `[...]` bracket
or an inserted `# heading` line can differ from the input script.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("buzzcaf_ai.buzzedit_script")

# BuzzEdit's own directive vocabulary (`asr/script_align.py::DIRECTIVES`),
# copied literally rather than imported: the two repos share no dependency
# apart from the byte-identical `buzzcaf_ports.py`, and reaching across the
# filesystem into BuzzEdit's tree for one regex would be fragile. Used only
# for the self-check at the bottom of this file.
_DIRECTIVES = (
    "map", "sfx", "broll", "video", "text", "title", "card", "chapter",
    "music", "mood", "quote", "stat", "source", "character", "location",
    "chart", "definition", "split", "freeze", "newspaper", "case_file",
    "fx", "atmos", "grade",
)
_DIRECTIVE_RE = re.compile(r"\[\s*(" + "|".join(_DIRECTIVES) + r")\s*:\s*[^\]]+?\s*\]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+.+$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

_HEADING_KINDS = {"chapter", "heading"}


def _clean_arg(value: Any) -> str:
    """One line, no literal `]` -- an unescaped `]` would truncate the
    directive early against BuzzEdit's `[^\\]]+?` regex."""
    text = "" if value is None else str(value)
    text = text.replace("]", ")").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _stat_text(beat: Dict[str, Any]) -> str:
    data = beat.get("data")
    if isinstance(data, dict) and "value" in data:
        return f"{data.get('value')}{data.get('suffix', '')}"
    return str(beat.get("text") or "")


def _chart_arg(beat: Dict[str, Any]) -> str:
    """A `[chart: ...]` argument BuzzEdit's `_chart_data` can parse.

    Prefers an explicit `arg` string; otherwise builds `type: l1=v1, l2=v2`
    from the beat's `data` (`chart_type` picks pie/line/bar; default is bar)."""
    if beat.get("arg"):
        return _clean_arg(beat.get("arg"))
    data = beat.get("data")
    if not isinstance(data, dict):
        return _clean_arg(data)
    labels = data.get("labels") or []
    values = data.get("values") or []
    pairs = ", ".join(f"{l}={v}" for l, v in zip(labels, values))
    chart_type = str(data.get("chart_type") or "").strip().lower()
    title = str(data.get("title") or "").strip()
    body = f"{chart_type}: {pairs}" if chart_type else pairs
    if title and not chart_type:
        body = f"{title}: {pairs}"
    return _clean_arg(body)


def _newspaper_arg(beat: Dict[str, Any]) -> str:
    """`MASTHEAD :: HEADLINE :: DATELINE` (or `HEADLINE | DATELINE`) for BuzzEdit's
    `_newspaper_data`. The headline is the only required part."""
    data = beat.get("data") if isinstance(beat.get("data"), dict) else {}
    headline = _clean_arg(data.get("headline") or beat.get("text"))
    dateline = _clean_arg(data.get("dateline"))
    masthead = _clean_arg(data.get("masthead"))
    if masthead:
        return f"{masthead} :: {headline} :: {dateline}"
    return f"{headline} | {dateline}" if dateline else headline


def _case_file_arg(beat: Dict[str, Any]) -> str:
    """`TITLE | label=value; label=value | STAMP` for BuzzEdit's `_case_file_data`."""
    data = beat.get("data") if isinstance(beat.get("data"), dict) else {}
    title = _clean_arg(data.get("title") or beat.get("text") or "CASE FILE")
    fields = data.get("fields") or []
    field_str = "; ".join(
        f"{_clean_arg(f.get('label'))}={_clean_arg(f.get('value'))}"
        for f in fields if isinstance(f, dict) and f.get("label"))
    stamp = _clean_arg(data.get("stamp"))
    parts = [title]
    if field_str:
        parts.append(field_str)
    if stamp:
        parts.append(stamp)
    return " | ".join(parts)


def _fx_arg(beat: Dict[str, Any]) -> str:
    """`<effect> intensity=.. speed=.. dur=.. color=..` for a `[fx: ]`/`[atmos: ]`
    directive. Reads the effect and options from the beat or its `data` block."""
    data = beat.get("data") if isinstance(beat.get("data"), dict) else {}

    def pick(*keys):
        for key in keys:
            value = beat.get(key)
            if value is None:
                value = data.get(key)
            if value is not None and str(value).strip() != "":
                return value
        return None

    effect = _clean_arg(pick("effect") or beat.get("text") or "")
    parts = [effect] if effect else []
    for label, keys in (("intensity", ("intensity",)), ("speed", ("speed",)),
                        ("dur", ("dur", "duration")), ("color", ("color",))):
        value = pick(*keys)
        if value is not None:
            parts.append(f"{label}={_clean_arg(value)}")
    return " ".join(parts)


def _grade_arg(beat: Dict[str, Any]) -> str:
    """`saturation=.. contrast=.. vignette=..` for a `[grade: ]` directive."""
    data = beat.get("data") if isinstance(beat.get("data"), dict) else {}
    parts = []
    for key in ("saturation", "contrast", "brightness", "vignette",
                "temperature", "gamma", "exposure", "sharpen"):
        value = beat.get(key)
        if value is None:
            value = data.get(key)
        if value is not None and str(value).strip() != "":
            parts.append(f"{key}={_clean_arg(value)}")
    return " ".join(parts)


# plan `kind` -> a formatter producing the `[kind: arg]` string (source plan's
# "Interchange schema" mapping table). `chapter`/`heading` are handled
# separately below since they are a block insert, not a bracket directive.
_DIRECTIVE_KIND = {
    "broll_image": lambda b: f"[broll: {_clean_arg(b.get('image_prompt'))}]",
    "broll_video": lambda b: f"[video: {_clean_arg(b.get('video_prompt'))}]",
    "map": lambda b: f"[map: {_clean_arg(b.get('place'))}]",
    "chart": lambda b: f"[chart: {_chart_arg(b)}]",
    "newspaper": lambda b: f"[newspaper: {_newspaper_arg(b)}]",
    "case_file": lambda b: f"[case_file: {_case_file_arg(b)}]",
    "stat_callout": lambda b: f"[stat: {_clean_arg(_stat_text(b))}]",
    "quote_card": lambda b: f"[quote: {_clean_arg(b.get('text'))} — {_clean_arg(b.get('subtext'))}]",
    "character_card": lambda b: f"[character: {_clean_arg(b.get('text'))} — {_clean_arg(b.get('subtext'))}]",
    "location_card": lambda b: f"[location: {_clean_arg(b.get('text'))} — {_clean_arg(b.get('subtext'))}]",
    "definition_card": lambda b: f"[definition: {_clean_arg(b.get('text'))} = {_clean_arg(b.get('subtext'))}]",
    "split": lambda b: f"[split: {_clean_arg(b.get('text'))} | {_clean_arg(b.get('subtext'))}]",
    "fx": lambda b: f"[fx: {_fx_arg(b)}]",
    "atmos": lambda b: f"[atmos: {_fx_arg(b)}]",
    "grade": lambda b: f"[grade: {_grade_arg(b)}]",
}


def _directive_for(beat: Dict[str, Any]) -> Optional[str]:
    """The exact text to splice in for one beat, or None for an unknown kind."""
    kind = str(beat.get("kind") or "").strip().lower()
    if kind in _HEADING_KINDS:
        heading = _clean_arg(beat.get("text") or beat.get("arg") or beat.get("anchor") or "")
        return f"\n\n# {heading}\n\n"
    formatter = _DIRECTIVE_KIND.get(kind)
    if not formatter:
        return None
    return formatter(beat) + " "


def _sentence_spans(script_text: str) -> List[Tuple[int, str]]:
    """`(start_index, sentence_text)` for a simple sentence split. Anchors are
    expected to be short, so matching at sentence granularity (not a full
    word-alignment pass -- that is BuzzEdit's job once it has a transcript)
    is enough precision for a fallback."""
    spans: List[Tuple[int, str]] = []
    pos = 0
    for part in _SENTENCE_SPLIT_RE.split(script_text):
        if not part:
            continue
        start = script_text.find(part, pos)
        if start == -1:
            start = pos
        spans.append((start, part))
        pos = start + len(part)
    return spans


def _locate(anchor: str, script_text: str, sentences: List[Tuple[int, str]]) -> Optional[int]:
    """Where `anchor` belongs in `script_text`: an exact case-insensitive
    substring first, else the start of the closest-matching sentence."""
    anchor = (anchor or "").strip()
    if not anchor:
        return None
    idx = script_text.lower().find(anchor.lower())
    if idx != -1:
        return idx
    if not sentences:
        return None
    texts = [s for _, s in sentences]
    close = difflib.get_close_matches(anchor, texts, n=1, cutoff=0.6)
    if not close:
        return None
    matched = close[0]
    for start, s in sentences:
        if s == matched:
            return start
    return None


def to_directive_script(script_text: str, visual_plan: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """The script with `[kind: arg]` directives (and `# heading` lines)
    spliced in ahead of each beat's `anchor`.

    Returns `(annotated_text, skipped_beats)`. A beat whose anchor cannot be
    located (exactly, or by the sentence-level fuzzy fallback) or whose
    `kind` is unrecognised is skipped rather than guessed at, and returned so
    the caller can log it instead of silently losing a planned visual.
    """
    script_text = script_text or ""
    beats = (visual_plan or {}).get("beats") if isinstance(visual_plan, dict) else None
    if not isinstance(beats, list):
        beats = []

    sentences = _sentence_spans(script_text)

    insertions: List[Tuple[int, str]] = []
    skipped: List[Dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        directive_text = _directive_for(beat)
        if directive_text is None:
            skipped.append({**beat, "_skip_reason": f"unknown kind '{beat.get('kind')}'"})
            continue
        idx = _locate(str(beat.get("anchor") or ""), script_text, sentences)
        if idx is None:
            skipped.append({**beat, "_skip_reason": "anchor not found in script"})
            continue
        insertions.append((idx, directive_text))

    # Descending index order: splicing the later insertions first means the
    # indices of the ones not yet applied (found against the *original* text)
    # are never shifted out from under them.
    insertions.sort(key=lambda pair: pair[0], reverse=True)
    annotated = script_text
    for idx, text in insertions:
        annotated = annotated[:idx] + text + annotated[idx:]

    if skipped:
        logger.warning(
            "buzzedit_script: %d beat(s) could not be placed and were skipped: %s",
            len(skipped),
            ", ".join(str(b.get("kind")) for b in skipped),
        )
    _self_check(annotated, len(insertions))
    return annotated, skipped


def _self_check(annotated_text: str, expected_count: int) -> None:
    """Cheap sanity pass: at least as many directive/heading markers should be
    recognisable in the spliced text as we meant to insert. A mismatch is
    logged, not raised -- the annotated script is still usable either way."""
    found = len(_DIRECTIVE_RE.findall(annotated_text)) + len(_HEADING_RE.findall(annotated_text))
    if found < expected_count:
        logger.warning(
            "buzzedit_script: expected at least %d directive(s)/heading(s) after annotation, found %d.",
            expected_count, found,
        )
