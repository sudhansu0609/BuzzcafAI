"""Splitting a session recording: the Shorts at its start, the long video after.

A shorts-first project (app/services/session_format.py) is recorded in one
sitting: 3-4 Shorts, then the creator's greeting, then the long video. Once
BuzzEdit has transcribed and cut the recording, its kept words say where
everything is:

1. **The long video starts at the greeting** -- "Hello doston, mera naam hai
   Sudhansu aur aap dekh rahe hain <channel>" -- which a Short never has. It
   is found in the kept words (fuzzy: the recogniser spells names its own
   way). `session_split_s` on the project (seconds into the recording) wins
   over the search, for a session where the greeting was changed or garbled.
2. **Each Short** starts where its script's first words are said (the
   Shorts' scripts in script/shorts.json); a Short whose opening cannot be
   found starts after the longest silence instead, since the creator stops
   between Shorts.
3. **The Shorts are cut out of the long edit** on BuzzEdit
   (`program/cut`, a manual cut that survives a re-cut), so the long video is
   planned and rendered from the greeting on.
4. **Each Short becomes its own project** (workflow `shorts_ready`, a
   vertical render) with its script, title, caption and hashtags, and its
   piece of the recording (cut with ffmpeg, next to the recording) queued for
   production after the long video.

Everything is recorded in `project.metadata["session_split"]`; running it
again on the same BuzzEdit project only re-checks the cut.
"""

import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("buzzcaf_ai.session_split")

#: Share of the greeting's key words a stretch of the recording must contain.
GREETING_MIN_SCORE = 0.55
#: A greeting this close to the start means nothing was recorded before it.
MIN_LONG_START_S = 12.0
#: A piece with less speech than this is a false start, not a Short.
SHORT_MIN_SPEECH_S = 8.0
#: How much of the recording is kept around a Short's first and last word.
PAD_BEFORE_S = 0.35
PAD_AFTER_S = 0.7
#: Room left before the greeting when the Shorts are cut off the long edit.
CUT_LEAD_S = 0.25
#: A Short's opening counts as found at this share of its first words.
PHRASE_MIN_SCORE = 0.5
PHRASE_WORDS = 12
#: Words of the greeting that say nothing on their own.
_COMMON = {"hai", "hain", "aur", "aap", "ka", "ki", "ke", "se", "the"}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

_TOKEN_RE = re.compile(r"[a-z0-9ऀ-ॿ]+")


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _word_token(w: Dict[str, Any]) -> str:
    toks = _tokens(str(w.get("word") or w.get("text") or ""))
    return "".join(toks)


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.78


def _start(w: Dict[str, Any]) -> float:
    try:
        return float(w.get("start") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _end(w: Dict[str, Any]) -> float:
    try:
        return float(w.get("end") or w.get("start") or 0.0)
    except (TypeError, ValueError):
        return _start(w)


# --- where the long video starts -----------------------------------------------------

def _identity(key: List[str]) -> List[int]:
    """The greeting's words that say WHO is greeting ("hello", "doston", his
    name) -- not the everyday words a horror Short says too ("raat", "3",
    "baje", "mera", "naam", "dekh")."""
    try:
        from app.services.writing_style import HINDI_WORDS
    except Exception:  # noqa: BLE001
        HINDI_WORDS = frozenset()
    return [k for k, t in enumerate(key) if len(t) >= 5 and t not in HINDI_WORDS and not t.isdigit()]


def find_greeting(words: Sequence[Dict[str, Any]], greeting_text: str) -> Optional[int]:
    """Index of the first word of the first stretch of `words` that says the
    greeting (most of its key words close together, including at least two
    of the words that say who is greeting), or None. "Raat ke 3 baje mera naam
    kisi ne pukara..." in a Short is not the greeting."""
    key = [t for t in dict.fromkeys(_tokens(greeting_text)) if t not in _COMMON]
    if not key or not words:
        return None
    identity = set(_identity(key))
    need_identity = min(2, len(identity))
    toks = [_word_token(w) for w in words]
    # Which key words each spoken word could be, computed once.
    hits = [{k for k, kw in enumerate(key) if _similar(tok, kw)} for tok in toks]
    span = len(_tokens(greeting_text)) + 4
    need = max(2, int(round(GREETING_MIN_SCORE * len(key) + 0.4999)))
    for i in range(len(words)):
        if not hits[i]:
            continue
        found = set()
        for j in range(i, min(len(words), i + span)):
            found |= hits[j]
        if len(found) >= need and len(found & identity) >= need_identity:
            return _greeting_start(words, hits, identity, i, span)
    return None


#: Two words of one greeting follow each other closer than this.
_GREETING_JOIN_S = 0.8


def _greeting_start(words: Sequence[Dict[str, Any]], hits: List[set], identity: set, i: int, span: int) -> int:
    """Where the greeting itself begins in the window found at `i`: its first
    "who" word, walked back over key words said right before it -- never back
    across a pause onto the end of the Short before it."""
    end = min(len(words), i + span)
    j = next((k for k in range(i, end) if hits[k] & identity), i)
    while j > i and hits[j - 1] and _start(words[j]) - _end(words[j - 1]) < _GREETING_JOIN_S:
        j -= 1
    return j


def find_phrase(words: Sequence[Dict[str, Any]], text: str, lo: int, hi: int,
                probe: int = PHRASE_WORDS) -> Tuple[Optional[int], float]:
    """Where in words[lo:hi] the first `probe` words of `text` are said:
    (index, share of them found in order-insensitive window), or (None, 0)."""
    want = _tokens(text)[:probe]
    want = [t for t in want if t not in _COMMON] or want
    if not want or hi <= lo:
        return None, 0.0
    toks = [_word_token(w) for w in words]
    span = probe + 4
    best: Tuple[Optional[int], float] = (None, 0.0)
    for i in range(lo, hi):
        if not any(_similar(toks[i], t) for t in want[:3]):
            continue
        window = toks[i:min(hi, i + span)]
        score = sum(1 for t in want if any(_similar(t, w) for w in window)) / len(want)
        if score > best[1] + 1e-9:
            best = (i, score)
            if score >= 0.95:
                break
    return best


def find_long_start(words: Sequence[Dict[str, Any]], greeting_text: str,
                    manual_s: Optional[float] = None) -> Tuple[Optional[int], str]:
    """(index of the long video's first word, how it was found). `how` is
    "manual", "greeting", or "none" (index None)."""
    if manual_s is not None:
        try:
            at = float(manual_s)
        except (TypeError, ValueError):
            at = None
        if at is not None and at >= 0:
            idx = next((k for k, w in enumerate(words) if _start(w) >= at - 0.05), None)
            return (idx, "manual") if idx is not None else (None, "none")
    idx = find_greeting(words, greeting_text)
    return (idx, "greeting") if idx is not None else (None, "none")


#: Spoken words of the long script, after its greeting, that locate its start.
LONG_OPENING_WORDS = 16
LONG_OPENING_MIN_SCORE = 0.6
#: At most this many words of a misheard greeting are walked back over.
GREETING_MAX_WORDS = 24


def find_long_opening(words: Sequence[Dict[str, Any]], long_script: str, greeting_text: str) -> Optional[int]:
    """Where the long video starts when its greeting was not recognised: the
    best match for the script's first spoken words after the greeting, then
    back over the (misheard) greeting said right before them -- never back
    across a pause. None when the opening is not found either."""
    from app.services.writing_style import narration_text
    text = narration_text(_cue_free(long_script))
    at = text.find(greeting_text)
    after = text[at + len(greeting_text):] if at >= 0 else text
    opening = " ".join(after.split()[:LONG_OPENING_WORDS])
    if not opening.strip():
        return None
    idx, score = find_phrase(words, opening, 0, len(words), probe=LONG_OPENING_WORDS)
    if idx is None or score < LONG_OPENING_MIN_SCORE:
        return None
    j = idx
    while j > 0 and idx - j < GREETING_MAX_WORDS and _start(words[j]) - _end(words[j - 1]) < _GREETING_JOIN_S:
        j -= 1
    return j


_CUE_RE = re.compile(r"^\s*#.*$|\[[^\]]*\]|\((?:pause|long pause|beat|slow|fast|normal)[^)]*\)", re.IGNORECASE | re.MULTILINE)


def _cue_free(script: str) -> str:
    return _CUE_RE.sub(" ", script or "")


# --- the Shorts before it -------------------------------------------------------------

def _speech_seconds(words: Sequence[Dict[str, Any]], i0: int, i1: int) -> float:
    return sum(max(0.0, _end(w) - _start(w)) for w in words[i0:i1 + 1])


def plan_shorts(words: Sequence[Dict[str, Any]], boundary: int, scripts: Sequence[str],
                count: int) -> List[Tuple[int, int, int]]:
    """The Shorts in words[:boundary] as (script index, first word, last word).

    Short k starts where its script's opening is said, in order; one whose
    opening is not found starts after the longest silence still free. With no
    scripts the `count` pieces are cut at the longest silences."""
    if boundary <= 0:
        return []
    n = len(scripts) if scripts else max(1, count)
    starts: List[Optional[int]] = [0] + [None] * (n - 1)
    lo = 1
    for k in range(1, n):
        if not scripts:
            break
        idx, score = find_phrase(words, scripts[k], lo, boundary)
        if idx is not None and score >= PHRASE_MIN_SCORE:
            starts[k] = idx
            lo = idx + 1
    # Fill the rest at the longest silences between words.
    gaps = sorted(((max(0.0, _start(words[i]) - _end(words[i - 1])), i) for i in range(1, boundary)),
                  reverse=True)
    for k in range(1, n):
        if starts[k] is not None:
            continue
        before = max([s for s in starts[:k] if s is not None] or [0])
        after = min([s for s in starts[k + 1:] if s is not None] or [boundary])
        pick = next((i for _, i in gaps if before < i < after and i not in starts), None)
        starts[k] = pick
    found = sorted({s for s in starts if s is not None})
    order = {s: k for k, s in enumerate(starts) if s is not None}
    pieces: List[Tuple[int, int, int]] = []
    for pos, s in enumerate(found):
        last = (found[pos + 1] if pos + 1 < len(found) else boundary) - 1
        if last < s:
            continue
        if _speech_seconds(words, s, last) < SHORT_MIN_SPEECH_S:
            continue
        pieces.append((order.get(s, pos), s, last))
    return pieces


def piece_times(words: Sequence[Dict[str, Any]], piece: Tuple[int, int, int],
                next_start: Optional[float]) -> Tuple[float, float]:
    """A Short's span of the original recording, padded, never into the next."""
    _, s, e = piece
    start = max(0.0, _start(words[s]) - PAD_BEFORE_S)
    end = _end(words[e]) + PAD_AFTER_S
    if next_start is not None:
        end = min(end, max(_end(words[e]) + 0.05, next_start - 0.05))
    return round(start, 3), round(end, 3)


# --- the pieces of the recording -------------------------------------------------------

def ffmpeg_binary() -> Optional[str]:
    return shutil.which("ffmpeg")


def clip_path_for(recording: str, index: int) -> str:
    stem, _ = os.path.splitext(os.path.basename(recording))
    return os.path.join(os.path.dirname(recording), f"{stem}_short{index}.mp4")


def extract_clip(recording: str, start_s: float, end_s: float, out_path: str) -> str:
    """Cut [start_s, end_s] of the recording into its own file (re-encoded, so
    it starts exactly there). Returns the path; raises RuntimeError."""
    binary = ffmpeg_binary()
    if not binary:
        raise RuntimeError("ffmpeg is not on PATH; the Shorts could not be cut out of the recording.")
    duration = max(0.5, end_s - start_s)
    cmd = [binary, "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{start_s:.3f}", "-i", recording, "-t", f"{duration:.3f}",
           "-map", "0:v:0", "-map", "0:a:0?",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffmpeg took too long cutting {os.path.basename(out_path)}.") from exc
    if proc.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg could not cut {os.path.basename(out_path)}: {(proc.stderr or '').strip()[-300:]}")
    return out_path


# --- the long edit ------------------------------------------------------------------------

def cut_before_long(client: Any, buzzedit_project_id: str, words: Sequence[Dict[str, Any]],
                    boundary_src_s: float) -> float:
    """Cut everything the long edit plays before the greeting. Returns the
    programme seconds removed (0 when there is nothing left to cut)."""
    first = next((w for w in words if _start(w) >= boundary_src_s - 0.05 and w.get("tl_start") is not None), None)
    early = [w for w in words if _start(w) < boundary_src_s - 0.05 and w.get("tl_start") is not None]
    if first is None or not early:
        return 0.0
    cut_to = max(0.0, float(first["tl_start"]) - CUT_LEAD_S)
    if cut_to <= 0.05:
        return 0.0
    project = client.get_project(buzzedit_project_id) or {}
    timeline = project.get("timeline") or {}
    try:
        fps = float(timeline.get("fps_num") or 30) / float(timeline.get("fps_den") or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        fps = 30.0
    end_frame = int(round(cut_to * fps))
    if end_frame <= 0:
        return 0.0
    client.cut_program(buzzedit_project_id, 0, end_frame)
    return round(cut_to, 2)


# --- the Short projects ------------------------------------------------------------------

def _slug(text: str, fallback: str) -> str:
    ascii_words = re.findall(r"[A-Za-z0-9]+", text or "")
    slug = " ".join(ascii_words[:6]).strip()
    return slug or fallback


def create_short_project(parent: Any, k: int, n: int, short: Dict[str, Any], clip: str,
                         span: Tuple[float, float]) -> Any:
    """One Short of the session as its own project, ready to produce."""
    from core.models.project import Project, StepExecution
    from executive.project import project_manager

    title = (short.get("title") or f"{parent.name} -- Short {k}").strip()
    project = None
    base = f"Short {_slug(title, f'{parent.id[-6:]} {k}')}"
    for attempt in range(6):
        try:
            project = project_manager.create_project(
                name=base + (f" {attempt + 1}" if attempt else ""), brand=parent.brand, workflow_name="shorts_ready")
            break
        except ValueError:
            continue
    if project is None:
        raise RuntimeError("could not create a unique id for a session Short")

    pdir = project.get_project_dir()
    os.makedirs(os.path.join(pdir, "script"), exist_ok=True)
    os.makedirs(os.path.join(pdir, "publish"), exist_ok=True)
    script = str(short.get("script") or "").strip()
    with open(os.path.join(pdir, "script", "short_script.md"), "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{script}\n" if script else f"# {title}\n")
    hashtags = list(short.get("hashtags") or ["#shorts"])
    package = {
        "title": title, "hook_line": short.get("hook_line", ""), "caption": short.get("caption", ""),
        "hashtags": hashtags, "on_screen_text": short.get("on_screen_text", ""),
        "estimated_seconds": round(span[1] - span[0]),
        "angle": short.get("angle", ""), "session_parent": parent.id,
    }
    with open(os.path.join(pdir, "publish", "short_package.json"), "w", encoding="utf-8") as f:
        json.dump(package, f, ensure_ascii=False, indent=2)
    with open(os.path.join(pdir, "publish", "title.txt"), "w", encoding="utf-8") as f:
        f.write(title + "\n")
    caption = str(short.get("caption") or "").strip()
    with open(os.path.join(pdir, "publish", "description.md"), "w", encoding="utf-8") as f:
        f.write((caption + "\n\n" if caption else "") + " ".join(hashtags) + "\n")
    with open(os.path.join(pdir, "publish", "tags.txt"), "w", encoding="utf-8") as f:
        f.write(", ".join(h.lstrip("#") for h in hashtags) + "\n")

    now = datetime.now().isoformat()
    project.name = title
    project.current_step = "Recorded in the session"
    if script:
        project.assets["script"] = "script/short_script.md"
    project.assets["short_package"] = "publish/short_package.json"
    project.steps_history.append(StepExecution(
        step_name="Short Script", agent_name="ShortsWriter", status="completed", started_at=now,
        completed_at=now, output_files={"script": "script/short_script.md"},
        logs=[f"Short {k} of {n} from the recording session of \"{parent.name}\" "
              f"({span[0]:.1f}-{span[1]:.1f} s of the recording)."]))
    project.metadata.update({
        "session_parent": {"project_id": parent.id, "name": parent.name, "index": k, "count": n,
                           "from_s": span[0], "to_s": span[1]},
        "orientation": "vertical",
        "recording_path": clip,
        "target_duration_minutes": round(max(0.2, (span[1] - span[0]) / 60.0), 1),
        # Recorded on the long video's (landscape) camera: the vertical
        # variant, reframed around his face, is the Short itself.
        "video_settings": {"shorts_clips": 0, "shorts_full": True},
    })
    project.save()
    try:
        from app.services.events import bus
        bus.publish("project_created", {"project_id": project.id, "name": project.name, "brand": project.brand,
                                        "workflow_name": "shorts_ready", "current_step": project.current_step})
    except Exception:  # noqa: BLE001
        pass
    return Project.load(project.id)


# --- the whole split ---------------------------------------------------------------------

class SessionSplitError(RuntimeError):
    """The long video's start could not be found: the creator sets it by hand."""

    #: The production queue does not retry this by itself: another run finds
    #: the same recording and the same missing greeting.
    retryable = False


def split(project: Any, client: Any, log: Callable[[str], None] = lambda m: None) -> Optional[Dict[str, Any]]:
    """Split this project's session recording (see the module docstring).
    Returns the `session_split` record (also saved on the project), or None
    when the project is not a shorts-first session. Raises SessionSplitError
    when the long video's start cannot be found."""
    from app.services import session_format, writing_style

    if not session_format.is_shorts_first(project):
        return None
    bp = project.metadata.get("buzzedit_project_id")
    if not bp:
        return None
    manual = project.metadata.get("session_split_s")
    scripts = session_format.load_shorts(project)
    # A session is one that was planned as one: its Shorts were written, or
    # the creator set the project (or the split point) himself. A project
    # from before sessions -- the channel default alone, no Shorts -- is the
    # long video only, as it always was (its cold open may come before the
    # greeting).
    if not scripts and project.metadata.get("session_format") != "shorts_first" and manual is None:
        log("Session: no Shorts were written for this project, so the whole recording is the long video.")
        return None
    words = sorted(client.get_kept_words(bp) or [], key=_start)
    record = dict(project.metadata.get("session_split") or {})
    done_before = record.get("buzzedit_project_id") == bp and record.get("boundary_s") is not None
    if done_before and (manual is None or float(manual) == float(record.get("manual_s") or -1)):
        # Already split: the Shorts exist; only make sure the cut still holds
        # (a re-cut re-plans the words).
        removed = cut_before_long(client, bp, words, float(record["boundary_s"]))
        if removed:
            log(f"Session: cut the Shorts ({removed:.1f} s) off the long video again.")
            record["programme_cut_s"] = removed
            project.metadata["session_split"] = record
            project.save()
        return record

    boundary, how = find_long_start(words, writing_style.greeting(project.brand), manual)
    if boundary is None and manual is None:
        # The greeting misheard past recognition: where the long script's
        # first lines after it are said, walked back over the greeting.
        boundary = find_long_opening(words, session_format.long_script_text(project), writing_style.greeting(project.brand))
        how = "script" if boundary is not None else how
    if boundary is None:
        raise SessionSplitError(
            "This is a Shorts-first session, but the long video's greeting (\""
            + writing_style.greeting(project.brand) + "\") was not found in the recording. Set "
            "'Long video starts at' (seconds into the recording) on the project, then retry.")
    boundary_s = _start(words[boundary])
    record = {"buzzedit_project_id": bp, "boundary_s": round(boundary_s, 3), "how": how,
              "manual_s": manual, "shorts": [], "warning": None,
              "split_at": datetime.now().isoformat(timespec="seconds")}
    if how == "script":
        log("Session: your greeting was not recognised; the long video starts where its script begins.")
    if boundary_s < MIN_LONG_START_S:
        record["warning"] = (f"The long video starts {boundary_s:.0f} s into the recording: no Shorts were "
                             "recorded before it, so the whole recording is the long video.")
        log("Session: " + record["warning"])
        project.metadata["session_split"] = record
        project.save()
        return record
    log(f"Session: the long video starts at {boundary_s:.1f} s ({'your greeting' if how == 'greeting' else 'set by hand'}).")

    pieces = plan_shorts(words, boundary, [s["script"] for s in scripts], session_format.shorts_count(project))
    recording = str(project.metadata.get("recording_path") or "")
    made: List[Dict[str, Any]] = []
    if not pieces:
        record["warning"] = "Nothing before the greeting was long enough to be a Short."
    elif not recording or not os.path.exists(recording):
        record["warning"] = "The recording file was not found, so the Shorts were not cut out of it."
    else:
        starts = [_start(words[p[1]]) for p in pieces]
        for pos, piece in enumerate(pieces):
            k = pos + 1
            nxt = starts[pos + 1] if pos + 1 < len(pieces) else boundary_s
            span = piece_times(words, piece, nxt)
            short = scripts[piece[0]] if 0 <= piece[0] < len(scripts) else {}
            clip = clip_path_for(recording, k)
            entry: Dict[str, Any] = {"index": k, "title": short.get("title") or f"Short {k}",
                                     "from_s": span[0], "to_s": span[1], "clip": clip, "project_id": None,
                                     "matched_script": bool(short)}
            try:
                log(f"Session: cutting Short {k} ({span[0]:.1f}-{span[1]:.1f} s) out of the recording...")
                extract_clip(recording, span[0], span[1], clip)
                child = create_short_project(project, k, len(pieces), short, clip, span)
                entry["project_id"] = child.id
            except Exception as exc:  # noqa: BLE001 - one Short failing never stops the long video
                logger.warning("Session split (%s): Short %d failed: %s", project.id, k, exc)
                entry["error"] = str(exc)[:300]
            made.append(entry)
        if scripts and len(pieces) != len(scripts):
            record["warning"] = (f"{len(scripts)} Shorts were written but {len(pieces)} were found in the "
                                 "recording; check their titles and scripts.")
    record["shorts"] = made
    record["programme_cut_s"] = cut_before_long(client, bp, words, boundary_s)
    if record["programme_cut_s"]:
        log(f"Session: the Shorts ({record['programme_cut_s']:.1f} s) were cut off the long video.")
    project.metadata["session_split"] = record
    project.save()
    return record
