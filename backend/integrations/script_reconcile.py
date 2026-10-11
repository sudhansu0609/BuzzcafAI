"""
Reconcile the written script with what was actually said in the recording.

The script the agents wrote is a plan, not a record: the speaker skips lines,
reorders them, and ad-libs whole passages. Sending the written script to
BuzzEdit as-is goes wrong three ways -- its aligner gives captions the
script's spelling even where different words were spoken, a directive
anchored to a skipped line fires on whatever aligned word is nearest, and an
ad-libbed passage gets no visuals at all.

So the transcript is the truth and the script is a guide. This module aligns
the two and builds a *spoken script*: the transcript's words (taking the
script's spelling only where a word clearly matches), the script's paragraph
and chapter structure where it was followed, and each visual-plan beat placed
at the word where its anchor was actually spoken -- or dropped, with a reason,
if that part of the script never made it into the recording. Long unscripted
runs are returned as `adlib_runs` so the caller can plan visuals for them and
place those with `place_transcript_beat`.

Nothing here touches timing: BuzzEdit re-aligns the returned text to its own
word timings, which is exact because the text *is* its transcript.

Speaker labels (BuzzEdit VOICE_CHANGER_PLAN.md, brief S3): a story character's
line carries their label -- `MAYA (V.O.)` (any name), or an upper-case `MAYA:`
when MAYA is in the project's cast sheet (`speakers`) -- and the label is not a
spoken word. `render(speaker_labels=True)` writes it back on its own line before
the paragraph that character speaks, in the form BuzzEdit's
`asr/script_align.speaker_label` reads, so BuzzEdit converts those lines to the
character's cast voice. The narrator's labels (V.O., Narrator, Host) give no
speaker, and every other upper-case label stays a production note.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from integrations.buzzedit_script import _DIRECTIVE_RE, _HEADING_KINDS, _clean_arg, _directive_for

# A transcript word pairs with a script token inside a differing run only at
# this similarity or above -- stricter than BuzzEdit's own 0.5, because here
# a pairing decides which *spelling* the captions show.
PAIR_MIN_RATIO = 0.6
# A pair with no other pair within this many script tokens (and a matching
# distance in the transcript) is a coincidence -- a lone "hai" or "the" -- not
# evidence that the line was spoken.
SUPPORT_WINDOW = 4
# At least this many consecutive unscripted transcript words is an ad-lib
# passage worth its own paragraph and its own visuals. Shorter runs are Whisper
# mishearing a scripted word, or a filler.
ADLIB_MIN_WORDS = 12
# A beat's anchor counts as spoken when at least this share of its words were.
ANCHOR_SPOKEN_SHARE = 0.5
# A paragraph is reported as skipped below this share of spoken tokens.
PARAGRAPH_SKIPPED_SHARE = 0.2
# Words that say nothing about a topic -- present in every sentence, so they
# never count toward a paraphrase match. Folded at import (see `_STOP_KEYS`).
_STOPWORDS = (
    "hai hain ho hota hoti hote tha thi the ki ka ke ko se me mein main hum ham "
    "ye yeh vo woh wo to bhi aur par pe ek is us jo kya na nahi nahin kar karna "
    "karte kuch sab bas toh ab jab tab agar lekin but and or of to in is it that "
    "this you your we i a an for with be are was not so just apna apne apni "
    "unhe unko hamen humein aap aapka"
)

_MARKDOWN_RE = re.compile(r"[*_`~]+")
_TOKEN_RE = re.compile(r"\S+")
# Delivery cues the writer puts inline for the teleprompter -- "(pause)",
# "(pause 2s)", "[long pause]", "(slow)", "(normal)" -- are never spoken, so
# they must not count as script words. Keep in step with `cueOf` in
# frontend/src/components/Teleprompter.tsx.
_PACING_CUE_RE = re.compile(
    r"[\[(]\s*(?:long\s+)?(?:pause|hold|stop|wait|silence|beat|breath|breathe|slow|slower|slowly|softly|soft|"
    r"gently|dramatic|dramatically|emphasis|emphasi[sz]e|emotional|serious|whisper|fast|faster|quick|quickly|"
    r"excited|energetic|rapid|normal|regular)\b[^\])]{0,20}[\])]",
    re.IGNORECASE,
)
_HEADING_LINE_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
# A `LABEL:` at the start of a script line ("**V.O. (Narrator):**",
# "VISUAL:", "TEXT OVERLAY:"). Speaker labels introduce spoken text; every
# other label is a production note the speaker never says.
_LABEL_RE = re.compile(r"^\s*[*_]*\s*([A-Za-z][A-Za-z .()/&'-]{0,40}?)\s*[*_]*\s*:\s*[*_]*\s*(.*)$")
_SPEAKER_LABEL_RE = re.compile(r"\b(v\.?\s*o|narrator|host|speaker|voice|me|anchor|presenter)\b", re.IGNORECASE)
# A character's screenplay cue, `MAYA (V.O.)` -- alone on its line (the speech
# follows) or with ": text" -- and the narrator's own names, as BuzzEdit's
# `asr/script_align.py` reads them (`_CUE_LINE_RE`, `NARRATOR_LABELS`).
_VO_MARK = r"(?:V\.?\s*O\.?|O\.?\s*S\.?|O\.?\s*C\.?|CONT'?D\.?)"
_CUE_LINE_RE = re.compile(
    r"^\s*[*_]*\s*([A-Za-z][A-Za-z0-9 .'&-]{0,40}?)\s*\(\s*(" + _VO_MARK + r")\s*\)\s*[*_]*\s*"
    r"(?::\s*[*_]*\s*(.*))?$", re.IGNORECASE)
_VO_MARK_RE = re.compile(r"(?<![A-Za-z])" + _VO_MARK + r"(?![A-Za-z])", re.IGNORECASE)
_NARRATOR_NAMES = frozenset({"", "narrator", "host", "me", "anchor", "presenter", "speaker", "voice",
                             "voiceover", "voice-over", "voice over", "sutradhar"})
#: A speaker label alone on its line, as `Reconciliation.render(speaker_labels=True)`
#: writes it ("MAYA:", "MAYA (V.O.)"): never a spoken word (`story_visuals` times
#: shots by counting the words of the rendered text).
LABEL_LINE_RE = re.compile(
    r"^[ \t]*(?:[A-Za-z][A-Za-z0-9 .'&-]{0,40}?[ \t]*\([ \t]*(?i:" + _VO_MARK + r")[ \t]*\)"
    r"|[A-Z][A-Z0-9 .'&-]{0,40}?:)[ \t]*$", re.MULTILINE)
_NOTE_LABEL_RE = re.compile(
    r"\b(visual|text|overlay|sfx|sound|music|b-?roll|graphic|camera|shot|note|on-?screen|cut|"
    r"transition|lower third|caption|title|scene|thumbnail|edit|fx|bgm|cta|duration|tone|brand|language)\b",
    re.IGNORECASE)
# A whole line in brackets that is not a BuzzEdit directive ("[Visual: ...]").
_BRACKET_LINE_RE = re.compile(r"^\s*[*_]*\s*[\[(].*[\])]\s*[*_]*\s*$")
_HORIZONTAL_RULE_RE = re.compile(r"^\s*([-*_=]\s*){3,}$")
_STRIP_RE = re.compile(r"[^\wऀ-ॿ]+", re.UNICODE)

# A line that opens with an emoji (a "🎭 Tone: ..." style meta line living
# outside a markdown heading, so `_HEADING_LINE_RE` never sees it and
# `_LABEL_RE` cannot match it either -- its first character is not `[A-Za-z]`).
_EMOJI_LEAD_RE = re.compile(
    r"^\s*[*_]*\s*[\U0001F300-\U0001FAFF☀-➿⬀-⯿←-⇿]"
)
# Latin-script word (letter-led, digits allowed after -- brand names like
# "Life3Baje" are exactly the kind of term this vocabulary exists for), at
# least 3 characters, for the transcription vocabulary.
_VOCAB_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


_VOWELS_RE = re.compile(r"[aeiouy]+")
_ASPIRATE_RE = re.compile(r"([bcdgkpt])h")


def _fold(token: str) -> str:
    """A sound-alike key, so two romanisations of one Hindi word meet.

    The script is everyday Hinglish ("sabke", "sapne", "bade", "brand"); the
    transcript is a letter-by-letter transliteration ("sabake", "sapane",
    "ba.de", "braind"). They differ almost entirely in vowels, so the key is
    the word's first letter plus its consonant skeleton, with the usual
    spelling variants folded (ph/f, w/v, q/k, aspirates, doubled letters).
    Devanagari is left alone -- it is already one spelling per sound.
    """
    core = _STRIP_RE.sub("", (token or "").lower()).replace("_", "")
    if not core or re.search(r"[ऀ-ॿ]", core):
        return core
    core = core.replace("chh", "C").replace("ch", "C").replace("sh", "s").replace("ph", "f")
    core = re.sub(r"c(?=[eiy])", "s", core).replace("ck", "k").replace("c", "k").replace("C", "c")
    core = core.replace("w", "v").replace("q", "k").replace("x", "ks").replace("z", "j")
    core = _ASPIRATE_RE.sub(r"\1", core)
    core = core[0] + _VOWELS_RE.sub("", core[1:])
    return re.sub(r"(.)\1+", r"\1", core)


_STOP_KEYS = {_fold(w) for w in _STOPWORDS.split()}


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


# Fields (priority order) a placed beat's short preview is read from -- shown
# to the window-planning prompt (`integrations/visual_windows.py`) as "already
# covered here", so it does not plan a second beat for the same moment.
_HINT_FIELDS = ("text", "image_prompt", "video_prompt", "place", "subtext")


def _placed_hint(beat: Dict[str, Any]) -> str:
    for key in _HINT_FIELDS:
        value = beat.get(key)
        if value:
            return str(value)[:140]
    return ""


@dataclass
class _Paragraph:
    index: int
    heading: Optional[str]
    first_token: int
    tokens: List[str]
    # The story character who speaks it (None = the narrator) and the label
    # `render(speaker_labels=True)` writes before it.
    speaker: Optional[str] = None
    label: Optional[str] = None


@dataclass
class _Parsed:
    tokens: List[str] = field(default_factory=list)
    token_paragraph: List[int] = field(default_factory=list)
    paragraphs: List[_Paragraph] = field(default_factory=list)
    # Directives written inline in the script: (kind, arg, token index).
    inline: List[Tuple[str, str, int]] = field(default_factory=list)


def _heading_text(raw: str) -> Optional[str]:
    """`## [SCENE 01: THE HOOK]` -> `THE HOOK`; emoji and brackets dropped."""
    text = _MARKDOWN_RE.sub("", raw).strip().strip("[]").strip()
    text = re.sub(r"^(scene|chapter|part|section)\s*\d*\s*[:.\-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s:,'&?!.-]", "", text).strip(" -:")
    return text or None


def _speaker_name(raw: str) -> Optional[str]:
    """A label's speaker: "MAYA (V.O.)" -> "MAYA", "V.O. (Narrator)" -> None
    (the narrator). The same reading as BuzzEdit's `asr/script_align._speaker_name`."""
    name = _VO_MARK_RE.sub(" ", _MARKDOWN_RE.sub("", raw or ""))
    name = re.sub(r"\(\s*\)", " ", name)
    outside = re.sub(r"\([^)]*\)", " ", name)
    inside = " ".join(re.findall(r"\(([^)]*)\)", name))
    name = outside if outside.strip(" .-/&'") else inside
    name = re.sub(r"\s+", " ", name).strip(" .-/&'")
    return None if name.casefold() in _NARRATOR_NAMES else name


def speaker_name(raw: str) -> Optional[str]:
    """A label's speaker as the script spells it, "(V.O.)" marks dropped:
    "MAYA (V.O.)" -> "MAYA"; None for the narrator."""
    return _speaker_name(str(raw or ""))


def speaker_key(name: str) -> str:
    """How a speaker's name is compared: "(V.O.)" marks, markdown and case
    dropped ("" for the narrator). "Maya", "MAYA" and "MAYA (V.O.)" meet."""
    return (_speaker_name(str(name or "")) or "").casefold()


def _cast_keys(speakers: Optional[Sequence[str]]) -> frozenset:
    """The cast's names as label keys: "(V.O.)" marks and case dropped."""
    keys = set()
    for name in speakers or ():
        key = _speaker_name(str(name or ""))
        if key:
            keys.add(key.casefold())
    return frozenset(keys)


def _line_label(line: str, cast: frozenset) -> Optional[Tuple[Optional[str], Optional[str], str]]:
    """`(speaker, label, rest)` when a speaker's label opens `line`, else None.

    The narrator's label (V.O., Narrator, Host, ...) gives `(None, None, rest)`.
    A character's gives their name and the label `render` writes back: the cue
    `NAME (V.O.)` as the script has it, or `NAME:` for an upper-case cast name.
    Production-note labels (VISUAL:, TEXT OVERLAY:, SOUND:, MUSIC: ...) and
    upper-case labels that name nobody in the cast are not speakers."""
    cue = _CUE_LINE_RE.match(line)
    if cue:
        speaker = _speaker_name(cue.group(1))
        rest = (cue.group(3) or "").strip()
        if speaker is None:
            return None, None, rest
        return speaker, f"{speaker} ({cue.group(2).strip()})", rest
    label = _LABEL_RE.match(line)
    if not label:
        return None
    name, rest = label.group(1), label.group(2)
    if _SPEAKER_LABEL_RE.search(name):
        return None, None, rest
    if name.isupper() and not _NOTE_LABEL_RE.search(name):
        speaker = _speaker_name(name)
        if speaker and speaker.casefold() in cast:
            return speaker, f"{speaker}:", rest
    return None


def _read_line(line: str, cast: frozenset) -> Tuple[Optional[Tuple[Optional[str], Optional[str]]], str]:
    """`(label, spoken)` for one script line: `label` = (speaker, label text)
    when a speaker's label opens it (speaker None = the narrator), else None;
    `spoken` = the part that is actually said ("" for a production note)."""
    if not line.strip() or _HORIZONTAL_RULE_RE.match(line):
        return None, ""
    if _BRACKET_LINE_RE.match(line) and not _DIRECTIVE_RE.fullmatch(_MARKDOWN_RE.sub("", line).strip()):
        return None, ""
    found = _line_label(line, cast)
    if found is not None:
        return (found[0], found[1]), found[2]
    label = _LABEL_RE.match(line)
    if label:
        name = label.group(1)
        if _NOTE_LABEL_RE.search(name) or name.isupper():
            return None, ""
    return None, line


def _spoken_part(line: str, speakers: Optional[Sequence[str]] = None) -> str:
    """The part of a script line that is actually said, or "" for a
    production note (a stage direction, a visual cue, a rule). A label is
    never said: the narrator's labelled line is his text, and so is a story
    character's -- an upper-case `NAME:` line when NAME is in `speakers` (the
    cast's names, compared case-insensitively), or a `NAME (V.O.)` line."""
    return _read_line(line, _cast_keys(speakers))[1]


def _same_speaker(a: Optional[str], b: Optional[str]) -> bool:
    return (a or "").casefold() == (b or "").casefold()


def _parse_script(text: str, speakers: Optional[Sequence[str]] = None) -> _Parsed:
    """Spoken tokens, their paragraphs and headings, and inline directives.

    A speaker's label holds for the lines after it in its block and starts a
    new paragraph when the speaker changes (a character's line, or the
    narrator after one); a label alone in its block speaks the next block, as
    in BuzzEdit's `asr/script_align.parse_script`. `speakers` = the cast's
    names, whose upper-case `NAME:` lines are their dialogue."""
    parsed = _Parsed()
    cast = _cast_keys(speakers)
    pending_heading: Optional[str] = None
    pending_label: Optional[Tuple[Optional[str], Optional[str]]] = None
    blocks = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n").strip())
    for block in blocks:
        runs: List[Tuple[Optional[str], Optional[str], List[str]]] = []
        speaker, label = pending_label or (None, None)
        pending_label = None
        spoken_lines: List[str] = []
        labelled = False
        for line in block.split("\n"):
            heading = _HEADING_LINE_RE.match(line)
            if heading:
                pending_heading = _heading_text(heading.group(1))
                continue
            found, spoken = _read_line(line, cast)
            if found is not None:
                labelled = True
                if not _same_speaker(found[0], speaker):
                    if spoken_lines:
                        runs.append((speaker, label, spoken_lines))
                        spoken_lines = []
                    speaker, label = found
            if spoken:
                spoken_lines.append(spoken)
        runs.append((speaker, label, spoken_lines))
        if labelled and not spoken_lines:
            pending_label = (speaker, label)
        for run_speaker, run_label, lines in runs:
            body = _PACING_CUE_RE.sub(" ", _MARKDOWN_RE.sub("", "\n".join(lines))).strip()
            if not body:
                continue
            tokens: List[str] = []
            cursor = 0
            for match in _DIRECTIVE_RE.finditer(body):
                tokens.extend(_TOKEN_RE.findall(body[cursor:match.start()]))
                inner = match.group(0)[1:-1]
                kind, _, arg = inner.partition(":")
                parsed.inline.append((kind.strip().lower(), arg.strip(), len(parsed.tokens) + len(tokens)))
                cursor = match.end()
            tokens.extend(_TOKEN_RE.findall(body[cursor:]))
            if not tokens:
                continue
            paragraph = _Paragraph(index=len(parsed.paragraphs), heading=pending_heading,
                                   first_token=len(parsed.tokens), tokens=tokens,
                                   speaker=run_speaker, label=run_label)
            pending_heading = None
            parsed.paragraphs.append(paragraph)
            parsed.tokens.extend(tokens)
            parsed.token_paragraph.extend([paragraph.index] * len(tokens))
    return parsed


def _speakers_of(parsed: _Parsed) -> List[str]:
    out: List[str] = []
    for paragraph in parsed.paragraphs:
        if paragraph.speaker and not any(_same_speaker(paragraph.speaker, s) for s in out):
            out.append(paragraph.speaker)
    return out


def script_speakers(text: str, speakers: Optional[Sequence[str]] = None) -> List[str]:
    """The story characters with lines of their own in `text` (as their labels
    name them), in order of first appearance. `speakers` as in `_parse_script`."""
    return _speakers_of(_parse_script(text, speakers))


def _align(script_keys: List[str], word_keys: List[str]) -> List[Tuple[int, int, bool]]:
    """(script index, word index, exact) pairs, in order on both sides."""
    matcher = difflib.SequenceMatcher(None, script_keys, word_keys, autojunk=False)
    pairs: List[Tuple[int, int, bool]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs.extend((i, j1 + (i - i1), True) for i in range(i1, i2))
        elif tag == "replace":
            i, j = i1, j1
            while i < i2 and j < j2:
                if _ratio(script_keys[i], word_keys[j]) >= PAIR_MIN_RATIO:
                    pairs.append((i, j, False))
                    i += 1
                    j += 1
                    continue
                ahead_i = _ratio(script_keys[i + 1], word_keys[j]) if i + 1 < i2 else 0.0
                ahead_j = _ratio(script_keys[i], word_keys[j + 1]) if j + 1 < j2 else 0.0
                if ahead_i >= PAIR_MIN_RATIO and ahead_i >= ahead_j:
                    i += 1
                elif ahead_j >= PAIR_MIN_RATIO:
                    j += 1
                else:
                    i += 1
                    j += 1
    return pairs


def _supported(pairs: List[Tuple[int, int, bool]]) -> List[Tuple[int, int, bool]]:
    """Drop isolated pairs: a line counts as spoken only where several nearby
    words line up, not where one common word happens to."""
    kept = []
    for n, (i, j, exact) in enumerate(pairs):
        neighbours = pairs[max(0, n - 2):n] + pairs[n + 1:n + 3]
        if any(abs(i2 - i) <= SUPPORT_WINDOW and abs(j2 - j) <= SUPPORT_WINDOW + 2
               for i2, j2, _ in neighbours):
            kept.append((i, j, exact))
    return kept


def _programme_times(words: Sequence[Dict[str, Any]], key: str) -> Optional[List[float]]:
    """Each word's `key` time, a missing one (a dropped sliver) taking the
    time before it; None when fewer than half the words have one."""
    raw = [w.get(key) if isinstance(w, dict) else None for w in words]
    if not raw or sum(1 for t in raw if isinstance(t, (int, float))) < len(raw) / 2:
        return None
    out: List[float] = []
    last = next((float(t) for t in raw if isinstance(t, (int, float))), 0.0)
    for t in raw:
        if isinstance(t, (int, float)):
            last = max(last, float(t)) if out else float(t)
        out.append(last)
    return out


class Reconciliation:
    """One script aligned to one transcript, ready to take beats and render."""

    def __init__(self, script_text: str, transcript_words: Sequence[Dict[str, Any]],
                 speakers: Optional[Sequence[str]] = None):
        spoken = [(str(w.get("word") or w.get("text") or "").strip(), w) for w in transcript_words]
        spoken = [(text, w) for text, w in spoken if text]
        self.words: List[str] = [text for text, _ in spoken]
        # Where each word lands in the edited programme (BuzzEdit's kept words
        # carry `tl_start`/`tl_end`), so a later pass can time the shots it
        # places before them. None when the words carry no programme time.
        self.word_times: Optional[List[float]] = _programme_times(
            [w for _, w in spoken], "tl_start")
        ends = _programme_times([w for _, w in spoken], "tl_end")
        self.duration_s: Optional[float] = max(ends) if ends else None
        # `speakers`: the cast sheet's character names, whose upper-case
        # `NAME:` lines are their dialogue rather than production notes.
        self.parsed = _parse_script(script_text, speakers)
        #: The story characters with labelled lines in the script, in order.
        self.speakers: List[str] = _speakers_of(self.parsed)

        script_keys = [_fold(t) for t in self.parsed.tokens]
        word_keys = [_fold(w) for w in self.words]
        pairs = _supported(_align(script_keys, word_keys)) if script_keys and word_keys else []
        self.script_to_word: Dict[int, int] = {i: j for i, j, _ in pairs}
        self.word_to_script: Dict[int, int] = {j: i for i, j, _ in pairs}

        # Each transcript word's paragraph: the paragraph of its script token,
        # else the one before it. A long unscripted run gets its own id.
        self.adlib_runs: List[Tuple[int, int]] = []
        self.word_paragraph: List[Any] = [None] * len(self.words)
        run_start: Optional[int] = None
        for j in range(len(self.words) + 1):
            unscripted = j < len(self.words) and j not in self.word_to_script
            if unscripted and run_start is None:
                run_start = j
            elif not unscripted and run_start is not None:
                if j - run_start >= ADLIB_MIN_WORDS:
                    self.adlib_runs.append((run_start, j))
                run_start = None
        adlib_of = {j: n for n, (a, b) in enumerate(self.adlib_runs) for j in range(a, b)}
        current: Any = None
        for j in range(len(self.words)):
            if j in adlib_of:
                self.word_paragraph[j] = ("adlib", adlib_of[j])
                continue
            if j in self.word_to_script:
                current = ("script", self.parsed.token_paragraph[self.word_to_script[j]])
            self.word_paragraph[j] = current
        # Leading unscripted words join the first real paragraph.
        first = next((p for p in self.word_paragraph if p is not None), ("script", 0))
        self.word_paragraph = [p if p is not None else first for p in self.word_paragraph]

        self._inserts: Dict[int, List[str]] = {}
        self._headings: Dict[int, str] = {}
        self.placed: List[Dict[str, Any]] = []
        self.dropped: List[Dict[str, Any]] = []
        self.paraphrased = 0

        for paragraph in self.parsed.paragraphs:
            if paragraph.heading:
                j = self._first_spoken(paragraph.first_token, paragraph.first_token + len(paragraph.tokens))
                if j is not None:
                    self._headings.setdefault(j, paragraph.heading)
        for kind, arg, token in self.parsed.inline:
            j = self._first_spoken(token, min(len(self.parsed.tokens), token + 8))
            text = f"[{kind}: {_clean_arg(arg)}] "
            if j is None:
                self.dropped.append({"kind": kind, "anchor": arg, "reason": "its line was not spoken"})
            else:
                self._inserts.setdefault(j, []).append(text)

    # ------------------------------------------------------------ lookups

    def _first_spoken(self, start: int, end: int) -> Optional[int]:
        for i in range(start, end):
            if i in self.script_to_word:
                return self.script_to_word[i]
        return None

    def _find_in_script(self, anchor: str) -> Optional[Tuple[int, int]]:
        keys = [_fold(t) for t in _TOKEN_RE.findall(_MARKDOWN_RE.sub("", anchor))]
        keys = [k for k in keys if k]
        return _find_span(keys, [_fold(t) for t in self.parsed.tokens])

    # ------------------------------------------------------------- beats

    def place_script_beat(self, beat: Dict[str, Any]) -> bool:
        """Place a visual-plan beat written against the script. It lands on the
        word where its anchor was spoken; if the speaker skipped that part of
        the script, the beat is dropped and recorded in `dropped`."""
        kind = str(beat.get("kind") or "").strip().lower()
        anchor = str(beat.get("anchor") or "")
        span = self._find_in_script(anchor)
        if span is None:
            # The plan may quote what was actually said rather than the script.
            return self.place_transcript_beat(beat)
        start, end = span
        spoken = sum(1 for i in range(start, end) if i in self.script_to_word)
        if spoken >= max(1, math.ceil((end - start) * ANCHOR_SPOKEN_SHARE)):
            return self._insert(beat, self._first_spoken(start, end))
        # Not said word for word -- but the speaker may have made the same
        # point in their own words, between the scripted lines either side.
        j = self._paraphrase_position(beat, start, end)
        if j is not None:
            self.paraphrased += 1
            return self._insert(beat, j)
        self.dropped.append({"kind": kind, "anchor": anchor[:120], "reason": "not spoken in the recording"})
        return False

    def _paraphrase_position(self, beat: Dict[str, Any], start: int, end: int) -> Optional[int]:
        """Where the speaker said this beat's idea in other words, or None.

        Searches only between the nearest spoken script lines before and after
        the anchor (that is where a paraphrase of it can be), for the window of
        transcript words sharing the most content words with the anchor and
        the beat's own text. Needs at least two shared words -- one is chance.
        """
        before = [self.script_to_word[i] for i in range(start - 1, -1, -1) if i in self.script_to_word][:1]
        after = [self.script_to_word[i] for i in range(end, len(self.parsed.tokens)) if i in self.script_to_word][:1]
        lo = before[0] + 1 if before else 0
        hi = after[0] if after else len(self.words)
        if hi - lo < 2:
            return None
        source = " ".join(str(beat.get(k) or "") for k in ("anchor", "text", "subtext", "place"))
        wanted = {k for k in (_fold(t) for t in _TOKEN_RE.findall(source)) if len(k) >= 2 and k not in _STOP_KEYS}
        # "Main chahta tha ki main ek poori book likhu": only book and likhu
        # carry the idea, so two shared words is the bar however long it is.
        if len(wanted) < 2:
            return None
        keys = [_fold(w) for w in self.words]

        def matches(key: str) -> set:
            # Same stem counts: "likhu"/"likhane", "karna"/"karenge". A key
            # that folds like a filler ("likhane" and "lekin" are both "lkn")
            # may still extend a wanted stem, but never stand in for one.
            if len(key) < 2:
                return set()
            if key in _STOP_KEYS:
                return {w for w in wanted if key.startswith(w)}
            return {w for w in wanted if key.startswith(w) or w.startswith(key)}

        span = max(8, 2 * (end - start))
        best, best_hits = None, 1
        for pos in range(lo, hi):
            if not matches(keys[pos]):
                continue
            found: set = set()
            for key in keys[pos:min(hi, pos + span)]:
                found |= matches(key)
            if len(found) > best_hits:
                best, best_hits = pos, len(found)
        return best

    def place_transcript_beat(self, beat: Dict[str, Any]) -> bool:
        """Place a beat whose anchor quotes the transcript itself (an ad-lib)."""
        kind = str(beat.get("kind") or "").strip().lower()
        anchor = str(beat.get("anchor") or "")
        keys = [k for k in (_fold(t) for t in _TOKEN_RE.findall(anchor)) if k]
        span = _find_span(keys, [_fold(w) for w in self.words])
        if span is None:
            self.dropped.append({"kind": kind, "anchor": anchor[:120], "reason": "anchor not found in the recording"})
            return False
        return self._insert(beat, span[0])

    def _insert(self, beat: Dict[str, Any], j: Optional[int]) -> bool:
        kind = str(beat.get("kind") or "").strip().lower()
        if j is None:
            self.dropped.append({"kind": kind, "anchor": str(beat.get("anchor") or "")[:120],
                                 "reason": "not spoken in the recording"})
            return False
        if kind in _HEADING_KINDS:
            heading = _clean_arg(beat.get("text") or beat.get("arg") or beat.get("anchor") or "")
            if heading:
                self._headings.setdefault(j, heading)
                self.placed.append({"kind": kind, "at_word": j, "hint": heading[:140]})
                return True
            return False
        directive = _directive_for(beat)
        if directive is None:
            self.dropped.append({"kind": kind, "anchor": str(beat.get("anchor") or "")[:120],
                                 "reason": f"unknown kind '{kind}'"})
            return False
        self._inserts.setdefault(j, []).append(directive)
        self.placed.append({"kind": kind, "at_word": j, "hint": _placed_hint(beat)})
        return True

    # ------------------------------------------------------------ output

    def adlib_texts(self) -> List[str]:
        return [" ".join(self.words[a:b]) for a, b in self.adlib_runs]

    def _label_of(self, word_paragraph: Any) -> Optional[str]:
        """The speaker label of the script paragraph a word belongs to, or None
        (the narrator, an ad-lib)."""
        if isinstance(word_paragraph, tuple) and word_paragraph[0] == "script":
            index = word_paragraph[1]
            if 0 <= index < len(self.parsed.paragraphs):
                return self.parsed.paragraphs[index].label
        return None

    def render(self, speaker_labels: bool = False) -> str:
        """The spoken script: transcript words (script spelling where a word
        clearly matched), paragraphed by the script, with the placed beats.

        With `speaker_labels`, every paragraph a story character speaks starts
        with that character's label on its own line (`MAYA:`, or `MAYA (V.O.)`
        as the script had it): BuzzEdit reads it to convert the character's
        lines to their cast voice and never counts it as a spoken word. The
        narrator's paragraphs carry none. Off by default: the creator's kept
        recording (`writing_style`) wants the spoken words only."""
        paragraphs: List[str] = []
        current: List[str] = []
        label: Optional[str] = None
        previous_paragraph: Any = object()

        def joined(words: List[str], label_line: Optional[str]) -> str:
            text = " ".join(words)
            return f"{label_line}\n{text}" if label_line else text

        for j, word in enumerate(self.words):
            heading = self._headings.get(j)
            if (heading or self.word_paragraph[j] != previous_paragraph) and current:
                paragraphs.append(joined(current, label))
                current = []
            if heading:
                paragraphs.append(f"# {heading}")
            previous_paragraph = self.word_paragraph[j]
            if not current:
                label = self._label_of(previous_paragraph) if speaker_labels else None
            for directive in self._inserts.get(j, []):
                current.append(directive.strip())
            i = self.word_to_script.get(j)
            current.append(self.parsed.tokens[i] if i is not None else word)
        if current:
            paragraphs.append(joined(current, label))
        return "\n\n".join(paragraphs).strip() + "\n"

    def report(self) -> Dict[str, Any]:
        """What the recording did with the script -- for the project record
        and the Studio UI."""
        script_total = len(self.parsed.tokens)
        spoken_total = len(self.script_to_word)
        skipped = []
        for paragraph in self.parsed.paragraphs:
            n = len(paragraph.tokens)
            got = sum(1 for i in range(paragraph.first_token, paragraph.first_token + n)
                      if i in self.script_to_word)
            if n and got / n < PARAGRAPH_SKIPPED_SHARE:
                skipped.append({"index": paragraph.index, "heading": paragraph.heading,
                                "preview": " ".join(paragraph.tokens[:18])})
        adlib_words = sum(b - a for a, b in self.adlib_runs)
        return {
            "script_tokens": script_total,
            "transcript_words": len(self.words),
            "script_spoken_share": round(spoken_total / script_total, 3) if script_total else 0.0,
            "adlib_share": round(adlib_words / len(self.words), 3) if self.words else 0.0,
            "skipped_paragraphs": skipped,
            "adlib_segments": [{"words": b - a, "preview": " ".join(self.words[a:a + 18])}
                               for a, b in self.adlib_runs],
            "beats_placed": len(self.placed),
            "beats_paraphrased": self.paraphrased,
            "beats_dropped": self.dropped,
        }


def clean_spoken_script(text: str, speakers: Optional[Sequence[str]] = None) -> str:
    """Only the words a speaker actually says, for a consumer that must never
    see a stage direction: YAML/front-matter and file-path headers (both are
    headings or "---" rules, dropped below), "---" rules, bracketed scene
    headings and `VISUAL:`/`[Visual: ...]` lines, stage directions in
    parentheses or brackets, and speaker labels ("V.O. (Narrator):", "HOST:")
    stripped down to the text that follows them.

    Built on `_parse_script` -- the same paragraph parser `Reconciliation`
    uses -- plus one extra pass for a meta line `_parse_script` cannot catch
    on its own: an emoji-led line ("🎭 Tone: ...") that is not a markdown
    heading, so neither `_HEADING_LINE_RE` nor `_LABEL_RE` (which requires an
    `[A-Za-z]` first character) ever sees it as a note.

    Headings themselves are dropped, not kept as "# heading" lines -- nobody
    speaks a chapter title. Used to build the transcription vocabulary; not
    fed into `Reconciliation`, whose own `_parse_script` call on the raw
    script already does this same cleaning without losing the inline
    `[kind: arg]` directives clean text like this one has no way to keep.

    `speakers` (the cast's names): their upper-case `NAME:` lines are spoken
    dialogue, kept without the label; a label never reaches this text.
    """
    lines = (text or "").replace("\r\n", "\n").split("\n")
    filtered = [line for line in lines if not _EMOJI_LEAD_RE.match(line)]
    parsed = _parse_script("\n".join(filtered), speakers)
    paragraphs = [" ".join(p.tokens) for p in parsed.paragraphs if p.tokens]
    return "\n\n".join(paragraphs).strip()


def extract_vocabulary(cleaned_text: str, cap: int = 300) -> List[str]:
    """Latin-script words (length >= 3) from a cleaned script, deduplicated
    case-insensitively in first-seen order and capped at `cap` -- a
    transcription vocabulary hint for BuzzEdit's Whisper pass."""
    seen: set = set()
    words: List[str] = []
    for match in _VOCAB_WORD_RE.finditer(cleaned_text or ""):
        word = match.group(0)
        if len(word) < 3:
            continue
        key = word.lower()
        if key in seen:
            continue
        seen.add(key)
        words.append(word)
        if len(words) >= cap:
            break
    return words


def _find_span(needle: List[str], haystack: List[str]) -> Optional[Tuple[int, int]]:
    """Where `needle` sits in `haystack`: an exact run first, else the best
    same-length window scoring at least 0.75."""
    n = len(needle)
    if not n or n > len(haystack):
        return None
    for start in range(len(haystack) - n + 1):
        if haystack[start:start + n] == needle:
            return start, start + n
    target = " ".join(needle)
    best, best_score = None, 0.75
    first_hits = {k for k in needle[:3]}
    for start in range(len(haystack) - n + 1):
        # Cheap prefilter: a real match shares one of the anchor's first words.
        if not first_hits.intersection(haystack[start:start + 3]):
            continue
        score = _ratio(target, " ".join(haystack[start:start + n]))
        if score > best_score:
            best, best_score = (start, start + n), score
    return best
