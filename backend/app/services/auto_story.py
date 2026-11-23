"""Auto Story (AUTO_STORY_PLAN.md §3.3, §3.4, §3.7): a video made end to end by
the tool, in the creator's voice.

    script (Shorts desk / long-form writers) -> spoken text
      -> narration.wav  (BuzzEdit POST /api/narration/synthesize, converted to his voice)
      -> take.mp4       (integrations.synthetic_take: his face intro + narration over a still)
      -> produce queue  (review_mode none, face_intro layout, vertical for reels)
      -> final file     -> publish (YouTube when signed in and asked; Instagram package always)

Everything that happens is recorded in `project.metadata["auto_story"]`. Before
the project is queued the record is written to the project directly; while the
queue runs it, the live state is kept in memory (the production pipeline saves
the project on its own, and a write from here could overwrite one of its own),
and the final record is written once the queue item has finished.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from core.paths import KNOWLEDGE_DIR

logger = logging.getLogger("buzzcaf_ai.auto_story")

STORE_DIR = os.path.join(KNOWLEDGE_DIR, "auto_story")
KOKORO_PRESETS = ("hf_alpha", "hm_omega", "hf_beta", "hm_psi")   # engine presets: converted to him afterwards
VOICE_DEFAULT = "sudhansu"
LONG_STORY = "long_story"
LONG_STORY_LABEL = "Long story (his face intro, then narration)"
#: The Shorts formats that make a reel (§3.3).
REEL_FORMATS = ("what_if", "anomaly_file", "rules_horror", "ghost_story", "folklore_entity", "horror_incident")
#: Script assets a long project's narration is read from (the newest wins).
#: `recording_script` is never one: it carries the session's Shorts too.
SCRIPT_KEYS = ("narration_optimized", "script_final", "script", "story")

NARRATION_ATTEMPTS = 3
NARRATION_BACKOFF_S = (20.0, 60.0, 180.0)
NARRATION_POLL_S = 5.0
NARRATION_MAX_WAIT_S = 4 * 3600.0
TAKE_ATTEMPTS = 2
ENQUEUE_ATTEMPTS = 3
WATCH_POLL_S = 20.0
LONG_DEFAULT_MINUTES, LONG_MIN_MINUTES, LONG_MAX_MINUTES = 20.0, 3.0, 120.0
WATCH_MAX_S = 24 * 3600.0
NIGHTLY_WAIT_S = 10 * 3600.0

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": False,
    # TheTallStoryteller starts at 0 (the creator's call, like Beyond3Baje):
    # the channel is wired in, but it makes nothing until he turns it on.
    "per_channel": {"Raat3Baje": 1, "Life3Baje": 1, "Beyond3Baje": 0, "TheTallStoryteller": 0},
    "formats": {
        "Raat3Baje": ["rules_horror", "ghost_story", "anomaly_file", "folklore_entity"],
        "Life3Baje": ["mood_reel"],
        "Beyond3Baje": ["what_if", "anomaly_file"],
        "TheTallStoryteller": ["folk_tale", "mystery", "history", "mythology", "comedy"],
    },
    "publish": False,
    #: The creator's switch (2026-10-27, "pause the voice clone, I will record
    #: the voice myself"): nothing is narrated in the cloned voice while it is
    #: on -- run()/make() refuse before writing a script, the nightly skips its
    #: narrated picks, the waiting-for-you pop-up stops offering it. Mood reels
    #: have no voice and keep running.
    "voice_clone_paused": False,
    #: Mood reels with still pictures (a slow push) instead of clips: ~2 min instead of ~25.
    "mood_reel_stills": False,
    #: {brand: path}: the face-intro clip saved on the Story Desk, used when
    #: synthetic_take.face_intro_clip_for(brand) has none.
    "face_intro_clips": {},
    #: {channel: {mood, pace, word_gap_ms, phrase_pause_s, sentence_pause_s,
    #: exaggeration, temperature, cfg_weight, dramatic}} (VOICE_DELIVERY_PLAN.md
    #: S1): only the keys the Story Desk's panel has set for that channel, plus
    #: "mood" and "dramatic". Missing channel -> VOICE_STYLE_DEFAULT.
    "voice_style": {},
    "last_run": "",
    "last": {},
    "rotation": {},
}

#: A channel with no saved voice-and-delivery settings (VOICE_DELIVERY_PLAN.md).
VOICE_STYLE_DEFAULT: Dict[str, Any] = {"mood": "steady", "dramatic": "subtle"}
#: Channels whose narration defaults to the fine-tuned horror clone instead of his plain
#: Chatterbox voice (VOICE_DELIVERY_PLAN.md F8); a voice/style explicitly given (a saved
#: per-channel choice, surfaced as that explicit value) always wins over these.
HORROR_NARRATOR_CHANNELS = ("Raat3Baje", "Beyond3Baje")
HORROR_VOICE_DEFAULT = "sudhansu_horror"
HORROR_VOICE_STYLE_DEFAULT: Dict[str, Any] = {"mood": "horror_narrator"}
#: Per-channel voice-and-mood default, a table rather than one hard-coded
#: horror case (2026-10-23, TheTallStoryteller): Raat3Baje/Beyond3Baje still
#: resolve to the same horror clone and mood as before; a channel absent from
#: this table falls through to VOICE_DEFAULT / VOICE_STYLE_DEFAULT.
CHANNEL_VOICE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    **{ch: {"voice": HORROR_VOICE_DEFAULT, "style": dict(HORROR_VOICE_STYLE_DEFAULT)} for ch in HORROR_NARRATOR_CHANNELS},
    "TheTallStoryteller": {"voice": "sudhansu_story", "style": {"mood": "warm"}},
}
#: Sliders on the Story Desk's "Voice and delivery" panel; (low, high) clamps.
VOICE_STYLE_RANGES: Dict[str, "tuple[float, float]"] = {
    "pace": (0.7, 1.3), "word_gap_ms": (0, 200), "phrase_pause_s": (0.0, 1.0),
    "sentence_pause_s": (0.0, 1.5), "exaggeration": (0.2, 1.2), "temperature": (0.4, 1.0),
    "cfg_weight": (0.0, 1.0),
}
VOICE_STYLE_DRAMATIC = ("off", "subtle", "strong")

#: GET /api/narration/moods's own table (VOICE_DELIVERY_PLAN.md), used when
#: BuzzEdit is unreachable or does not have the route yet.
FALLBACK_MOODS: List[Dict[str, Any]] = [
    {"id": "steady", "label": "Steady storyteller (default)", "description": "Steady storyteller (default)",
     "style": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8, "pace": 0.95,
               "word_gap_ms": 40, "phrase_pause_s": 0.25, "sentence_pause_s": 0.45}},
    {"id": "calm", "label": "Calm, relaxed", "description": "Calm, relaxed",
     "style": {"exaggeration": 0.35, "cfg_weight": 0.35, "temperature": 0.6, "pace": 0.9,
               "word_gap_ms": 60, "phrase_pause_s": 0.35, "sentence_pause_s": 0.6}},
    {"id": "warm", "label": "Warm, conversational", "description": "Warm, conversational",
     "style": {"exaggeration": 0.55, "cfg_weight": 0.5, "temperature": 0.8, "pace": 1.0,
               "word_gap_ms": 20, "phrase_pause_s": 0.15, "sentence_pause_s": 0.3}},
    {"id": "eerie", "label": "Slow and eerie", "description": "Slow and eerie",
     "style": {"exaggeration": 0.4, "cfg_weight": 0.3, "temperature": 0.6, "pace": 0.85,
               "word_gap_ms": 80, "phrase_pause_s": 0.5, "sentence_pause_s": 0.8}},
    {"id": "dramatic", "label": "Dramatic", "description": "Dramatic",
     "style": {"exaggeration": 0.8, "cfg_weight": 0.4, "temperature": 0.8, "pace": 0.95,
               "word_gap_ms": 40, "phrase_pause_s": 0.3, "sentence_pause_s": 0.6}},
    {"id": "intense", "label": "Intense, urgent", "description": "Intense, urgent",
     "style": {"exaggeration": 1.0, "cfg_weight": 0.5, "temperature": 0.8, "pace": 1.05,
               "word_gap_ms": 0, "phrase_pause_s": 0.1, "sentence_pause_s": 0.25}},
]
#: Spoken words/second once a mood's own pace and pauses are applied
#: (REELS_DESK_PLAN.md VR9): horror_narrator is measured (2026-10-24, 390
#: words / 189 s narrated for the failed "Shyam Ke Waqt Ka Nakaam Karobar"
#: reel); every other mood is estimated from its own pace/pause settings
#: until it is measured the same way. `WORDS_PER_SECOND_DEFAULT` covers a
#: mood this table does not name.
WORDS_PER_SECOND_BY_MOOD: Dict[str, float] = {
    "horror_narrator": 2.25,   # 2.06 measured at pace 0.85; 0.93 was 2.35 (est.), slowed to 0.90 2026-10-24
    "eerie": 2.1,              # estimated: as slow as horror_narrator, less pause padding
    "calm": 2.3,               # estimated
    "dramatic": 2.3,           # estimated
    "steady": 2.5,             # estimated (the channel-wide default mood)
    "intense": 2.6,            # estimated
    "warm": 2.6,               # estimated
}
WORDS_PER_SECOND_DEFAULT = 2.5


def words_per_second(channel: str) -> float:
    """Spoken words/second for `channel`'s resolved mood (`voice_style_for`):
    `WORDS_PER_SECOND_BY_MOOD`, or `WORDS_PER_SECOND_DEFAULT` for a mood not
    yet measured or estimated there."""
    mood = str(voice_style_for(channel).get("mood") or "").strip()
    return WORDS_PER_SECOND_BY_MOOD.get(mood, WORDS_PER_SECOND_DEFAULT)


_LENGTH_SECONDS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(second|minute)")


def length_seconds(length: Any) -> Optional[float]:
    """Seconds parsed out of a Shorts Desk length pick -- "1 minute (60
    seconds)", "75 seconds (Short)", "2 minutes" -- or None when `length`
    carries no number (a poem's line-count pick, or nothing at all). The
    last number+unit in the string wins, so an explicit "(N seconds)" aside
    overrides the rounder minute count that introduced it."""
    matches = _LENGTH_SECONDS_RE.findall(str(length or "").lower())
    if not matches:
        return None
    amount, unit = matches[-1]
    return float(amount) * (60.0 if unit.startswith("minute") else 1.0)


def word_budget(channel: str, length: Any) -> Optional[int]:
    """The hard spoken-word budget for a narrated reel/Short's target
    `length` (REELS_DESK_PLAN.md VR9): target seconds x `words_per_second`
    for `channel`'s resolved mood -- 60 s of horror_narrator -> ~124 words.
    None when `length` carries no parseable seconds."""
    seconds = length_seconds(length)
    if not seconds:
        return None
    return max(1, round(seconds * words_per_second(channel)))


#: A 2-3 sentence Hinglish horror sample (Devanagari) with one (dramatic)...(normal)
#: span, for the voice-preview when no text is given.
PREVIEW_SAMPLE_TEXT = (
    "राज अकेला उस पुराने घर में दाखिल हुआ, और दरवाज़ा उसके पीछे अपने आप बंद हो गया। "
    "(dramatic) उसे यकीन हो गया कि कमरे में कोई और भी है, जो उसे देख रहा है। (normal) "
    "बाहर सड़क पर सिर्फ सन्नाटा था।"
)

_sleep = time.sleep
_lock = threading.Lock()


def _noop(_msg: str) -> None:
    return None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# --- settings ---------------------------------------------------------------------

def _settings_path() -> str:
    return os.path.join(STORE_DIR, "settings.json")


def _write_json(path: str, value: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def settings() -> Dict[str, Any]:
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:
        saved = {}
    out = json.loads(json.dumps(DEFAULT_SETTINGS))
    if isinstance(saved, dict):
        for key, value in saved.items():
            if key in ("per_channel", "formats", "rotation", "face_intro_clips", "voice_style") and isinstance(value, dict):
                out[key] = {**out[key], **value}
            elif key in out:
                out[key] = value
    return out


def voice_style_for(channel: str) -> Dict[str, Any]:
    """The channel's saved voice-and-delivery settings (VOICE_DELIVERY_PLAN.md
    S1), or its own default when it has none: CHANNEL_VOICE_DEFAULTS per
    channel (Raat3Baje/Beyond3Baje to the horror_narrator mood, F8;
    TheTallStoryteller to its warm storytelling mood), every other channel to
    VOICE_STYLE_DEFAULT."""
    saved = (settings().get("voice_style") or {}).get(channel)
    if isinstance(saved, dict) and saved:
        return dict(saved)
    default = CHANNEL_VOICE_DEFAULTS.get(channel)
    if default:
        return dict(default["style"])
    return dict(VOICE_STYLE_DEFAULT)


class VoiceClonePaused(RuntimeError):
    """The cloned voice is paused (`voice_clone_paused`): record it yourself."""


def voice_clone_paused() -> bool:
    return bool(settings().get("voice_clone_paused"))


def refuse_if_voice_clone_paused() -> None:
    if voice_clone_paused():
        raise VoiceClonePaused("The cloned voice is paused -- record the narration yourself, "
                               "or turn it back on (auto story setting voice_clone_paused).")


def default_voice_for(channel: str) -> str:
    """The voice a call defaults to when none is given (F8): each channel's
    own voice from CHANNEL_VOICE_DEFAULTS (the fine-tuned horror clone for
    Raat3Baje/Beyond3Baje, the storytelling clone for TheTallStoryteller),
    else the creator's plain voice."""
    default = CHANNEL_VOICE_DEFAULTS.get(channel)
    return default["voice"] if default else VOICE_DEFAULT


def moods() -> List[Dict[str, Any]]:
    """Mood presets for narration: BuzzEdit's GET /api/narration/moods, or
    the plan's own table when BuzzEdit is unreachable or does not have the
    route yet."""
    try:
        from integrations.buzzedit_client import BuzzEditClient
        resp = BuzzEditClient()._get("/api/narration/moods", timeout=(3, 10))
        if resp.status_code < 400:
            data = resp.json()
            rows = data.get("moods") if isinstance(data, dict) else data
            if isinstance(rows, list) and rows:
                return rows
    except Exception as exc:  # noqa: BLE001 - BuzzEdit down or route missing: the fallback table
        logger.debug("narration moods unavailable: %s", exc)
    return json.loads(json.dumps(FALLBACK_MOODS))


def channel_formats(channel: str) -> List[str]:
    """The formats auto story can make for a channel: its Shorts formats and the long story."""
    from app.services import mood_reel, shorts_desk
    extra = [mood_reel.KEY] if channel in mood_reel.CHANNELS else []
    return list(shorts_desk.FORMATS.get(channel, {})) + extra + [LONG_STORY]


def set_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import shorts_desk
    with _lock:
        current = settings()
        patch = patch or {}
        for key in ("enabled", "publish", "mood_reel_stills", "voice_clone_paused"):
            if key in patch:
                current[key] = bool(patch[key])
        if isinstance(patch.get("per_channel"), dict):
            for ch, n in patch["per_channel"].items():
                if ch in shorts_desk.FORMATS:
                    try:
                        current["per_channel"][ch] = max(0, min(5, int(n)))
                    except (TypeError, ValueError):
                        pass
        if isinstance(patch.get("formats"), dict):
            for ch, keys in patch["formats"].items():
                if ch in shorts_desk.FORMATS and isinstance(keys, list):
                    allowed = channel_formats(ch)
                    current["formats"][ch] = [k for k in keys if k in allowed]
        if isinstance(patch.get("face_intro_clips"), dict):
            for brand, path in patch["face_intro_clips"].items():
                path = str(path or "").strip().strip('"')
                if path:
                    current["face_intro_clips"][str(brand)] = path
                else:
                    current["face_intro_clips"].pop(str(brand), None)
        if isinstance(patch.get("voice_style"), dict):
            for ch, style in patch["voice_style"].items():
                if ch not in shorts_desk.FORMATS or not isinstance(style, dict):
                    continue
                clean: Dict[str, Any] = {}
                mood = str(style.get("mood") or "").strip()
                if mood:
                    clean["mood"] = mood
                if style.get("dramatic") in VOICE_STYLE_DRAMATIC:
                    clean["dramatic"] = style["dramatic"]
                for key, (lo, hi) in VOICE_STYLE_RANGES.items():
                    if style.get(key) is not None:
                        try:
                            clean[key] = max(lo, min(hi, float(style[key])))
                        except (TypeError, ValueError):
                            pass
                current["voice_style"][str(ch)] = clean
        for key in ("last_run", "last", "rotation"):
            if key in patch:
                current[key] = patch[key]
        _write_json(_settings_path(), current)
        return current


# --- the record ---------------------------------------------------------------------

_live: Dict[str, Dict[str, Any]] = {}
_watchers: Dict[str, threading.Thread] = {}


def _load(project_id: str):
    from core.models.project import Project
    return Project.load(project_id)


def _write_record(project_id: str, rec: Dict[str, Any]) -> None:
    project = _load(project_id)
    rec["updated_at"] = _now()
    project.metadata["auto_story"] = rec
    project.save()


def _step(rec: Dict[str, Any], state: str, message: str, progress: Callable[[str], None]) -> None:
    # The master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): every phase of
    # a run (script, narration, take, queued/plan/render/package) calls
    # `_step` right before it starts, so this is where the whole chain --
    # `run`, `_run_reel`, `make`, `make_mood_reel` -- holds between phases.
    from app.services import master_control
    master_control.wait_if_paused(f"auto_story: {state}", progress)
    rec["state"] = state
    rec["updated_at"] = _now()
    rec.setdefault("steps", []).append({"at": _now(), "state": state, "message": message[:300]})
    rec["steps"] = rec["steps"][-60:]
    try:
        progress(message)
    except Exception:  # noqa: BLE001 - a progress callback never stops the run
        pass


def record(project_id: str) -> Optional[Dict[str, Any]]:
    """The project's auto-story record, with the live state and its queue item when it has one."""
    try:
        project = _load(project_id)
    except (ValueError, FileNotFoundError):
        return None
    rec = dict(project.metadata.get("auto_story") or {})
    if project_id in _live:
        rec.update(_live[project_id])
    if not rec:
        return None
    rec["project_id"] = project_id
    rec.setdefault("name", project.name)
    rec.setdefault("brand", project.brand)
    try:
        from app.services import produce_queue
        item = produce_queue.latest_item_for(project_id)
        if item:
            rec["queue"] = {k: item.get(k) for k in ("id", "status", "error", "resume_from", "attempts", "updated_at")}
    except Exception:  # noqa: BLE001
        pass
    watcher = _watchers.get(project_id)
    rec["watching"] = bool(watcher and watcher.is_alive())
    return rec


def list_records() -> List[Dict[str, Any]]:
    """Every project with an auto-story record, newest first."""
    import core.paths
    root = str(core.paths.PROJECTS_DIR)
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return out
    for pid in os.listdir(root):
        path = os.path.join(root, pid, "project.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        rec = (data.get("metadata") or {}).get("auto_story")
        if not isinstance(rec, dict):
            continue
        rec = {**rec, **_live.get(pid, {})}
        # The "Needs you" list (Dashboard) and the Story Desk's own Approve /
        # Reject show a cover (or the video itself) and the caption without a
        # second round trip; read once here, from whatever package exists.
        cover = rec.get("cover")
        caption = None
        pdir = rec.get("package_dir")
        if pdir:
            if not cover:
                candidate = os.path.join(pdir, "cover.jpg")
                cover = candidate if os.path.isfile(candidate) else None
            try:
                with open(os.path.join(pdir, "caption.txt"), encoding="utf-8") as f:
                    caption = f.read().strip()
            except OSError:
                pass
        out.append({
            "project_id": pid, "name": data.get("name"), "brand": data.get("brand"),
            "state": rec.get("state"), "format": rec.get("format"), "orientation": rec.get("orientation"),
            "final": rec.get("final"), "posted": rec.get("posted") or {}, "error": rec.get("error"),
            "package_dir": rec.get("package_dir"), "started_at": rec.get("started_at"),
            "updated_at": rec.get("updated_at"), "review": rec.get("review"), "cover": cover, "caption": caption,
            "archived": bool(rec.get("archived") or data.get("status") == "archived"),
        })
    out.sort(key=lambda r: str(r.get("started_at") or r.get("updated_at") or ""), reverse=True)
    return out


# --- script -------------------------------------------------------------------------

def _script_text(project) -> str:
    pdir = project.get_project_dir()
    short = os.path.join(pdir, "script", "short_script.md")
    if project.metadata.get("orientation") == "vertical" and os.path.isfile(short):
        path = short
    else:
        candidates = []
        for key in SCRIPT_KEYS:
            rel = (project.assets or {}).get(key)
            if rel:
                full = os.path.join(pdir, rel)
                if os.path.isfile(full):
                    candidates.append(full)
        if not candidates and os.path.isfile(short):
            candidates.append(short)
        if not candidates:
            raise RuntimeError("The project has no script to narrate.")
        path = max(candidates, key=os.path.getmtime)
    with open(path, encoding="utf-8") as f:
        return f.read()


#: A writer's note left in the script where a model restarted its own text,
#: e.g. `(The text continues from: "...last sentence...")` (2026-10-26).
_SEAM_RE = re.compile(r"^\s*[\(\[]\s*(?:the\s+)?text\s+continues\s+from\s*:?\s*[\"“']?(.*?)[\"”']?\s*[\)\]]\s*$",
                      re.IGNORECASE | re.MULTILINE)
_MODEL_NOTE_RE = re.compile(r"^\s*[\(\[]\s*(?:note|continued|continuing|section\s+\d+|end of section|"
                            r"rest of the script|to be continued)\b[^\n]*[\)\]]\s*$", re.IGNORECASE | re.MULTILINE)
#: Anything else in square brackets -- `[VIS1: ...]`, `[FADE TO BLACK.]`, a
#: `[number]` placeholder -- is for the editor, never for the voice.
_BRACKET_CUE_RE = re.compile(r"\[[^\]\n]*\]")
#: A short delivery cue in brackets is the same cue the engine takes in parentheses.
_BRACKET_DELIVERY_RE = re.compile(r"\[\s*((?:long |short )?pause|beat|slow|fast|whisper|soft)\s*\]", re.IGNORECASE)
_EMPHASIS_RE = re.compile(r"(\*{1,2}|_{2})(\S(?:.*?\S)?)\1")


def _norm_para(p: str) -> str:
    return re.sub(r"\W+", " ", p).strip().lower()


def fix_script_seams(text: str) -> str:
    """Content repairs a script file can keep: where a model restarted its
    text (`(The text continues from: "X")`), the older continuation after X
    is dropped and the newer one kept; other model notes and paragraphs said
    twice word for word are removed."""
    import difflib
    while True:
        m = _SEAM_RE.search(text)
        if not m:
            break
        before, after = text[:m.start()], text[m.end():]
        anchor = _norm_para(m.group(1))
        cut = None
        if anchor:
            # Find the sentence the note points back to (the model's quote is
            # close, not exact: "kamera" for "camera").
            best = 0.0
            for s in re.finditer(r"[^.!?\n]+[.!?]*", before):
                ratio = difflib.SequenceMatcher(None, anchor, _norm_para(s.group(0))).ratio()
                if ratio > best:
                    best, cut = ratio, s.end()
            if best < 0.75:
                cut = None
        text = (before[:cut] + "\n\n" + after.lstrip()) if cut is not None else (before + after)
    text = _MODEL_NOTE_RE.sub("", text)
    seen, out = set(), []
    for para in re.split(r"\n\s*\n", text):
        key = _norm_para(para)
        if len(key) > 100 and key in seen:
            continue
        seen.add(key)
        out.append(para.strip("\n"))
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)).strip()


def clean_for_voice(text: str) -> str:
    """What the voice engine may read: the script's content repairs, then no
    bracketed editor cues and no markdown marks (2026-10-26: `[VIS1: ...]`
    and `**...**` were being read out)."""
    text = fix_script_seams(text)
    text = _BRACKET_DELIVERY_RE.sub(lambda m: f"({m.group(1).lower()})", text)
    text = _BRACKET_CUE_RE.sub(" ", text)
    text = _EMPHASIS_RE.sub(r"\2", text).replace("**", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def spoken_script(project, drop_greeting: bool) -> str:
    from app.services import writing_style
    text = clean_for_voice(writing_style.spoken_text(_script_text(project)))
    if drop_greeting:
        # §4: the greeting opens a long video once, and his face intro says it.
        text, _ = writing_style.strip_repeated_intro(text, keep_first=False)
    text = text.strip()
    if not text:
        raise RuntimeError("The script has no spoken words.")
    return text


# --- narration (BuzzEdit §3.1) ------------------------------------------------------------

def _narration_post(body: Dict[str, Any]) -> Dict[str, Any]:
    from app.api.produce_api import ComfyUIUnavailableError, ensure_buzzedit_running
    try:
        ensure_buzzedit_running(timeout=180.0)
    except ComfyUIUnavailableError:
        pass  # narration does not need ComfyUI
    from integrations.buzzedit_client import BuzzEditClient
    resp = BuzzEditClient()._post("/api/narration/synthesize", body, timeout=(5, 120))
    if resp.status_code >= 400:
        raise RuntimeError(f"BuzzEdit narration refused ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def _narration_job(job_id: str) -> Dict[str, Any]:
    from integrations.buzzedit_client import BuzzEditClient
    resp = BuzzEditClient()._get(f"/api/narration/jobs/{job_id}", timeout=(5, 30))
    if resp.status_code >= 400:
        raise RuntimeError(f"BuzzEdit narration job {job_id}: {resp.status_code} {resp.text[:300]}")
    return resp.json()


def _narrate_once(body: Dict[str, Any], progress: Callable[[str], None]) -> Dict[str, Any]:
    job = _narration_post(body)
    job_id = job.get("job_id")
    deadline = time.time() + NARRATION_MAX_WAIT_S
    misses = 0
    while job.get("state") not in ("done", "failed"):
        if not job_id:
            raise RuntimeError(f"BuzzEdit returned no narration job id: {str(job)[:200]}")
        if time.time() > deadline:
            raise RuntimeError("The narration did not finish in time.")
        _sleep(NARRATION_POLL_S)
        try:
            job = _narration_job(job_id)
            misses = 0
            if job.get("message"):
                progress(f"Narration: {job['message']}")
        except Exception as exc:  # noqa: BLE001 - BuzzEdit busy or restarting: keep polling
            misses += 1
            if misses >= 30:
                raise RuntimeError(f"Lost the narration job: {exc}")
    if job.get("state") == "failed":
        raise RuntimeError(f"Narration failed: {job.get('message') or 'no detail'}")
    result = job.get("result") or {}
    wav = result.get("wav")
    if not wav or not os.path.isfile(wav):
        raise RuntimeError(f"The narration file is not on disk: {wav}")
    return result



#: A directed text is kept only when it still says at least this fraction of
#: the script's own words, in order (2026-10-24, Fable review #12): the old
#: length-only check let the voice say a different text than the script.
NARRATION_FIDELITY_MIN = 0.85
NARRATION_DIRECT_MAX_CHARS = 12000
_direct_lock = threading.Lock()


#: Devanagari consonants -> the Roman letters Hinglish spells them with.
_DEVA_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "ch", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
}
_DEVA_NUKTA = {"क": "k", "ख": "kh", "ग": "g", "ज": "j", "ड": "d", "ढ": "dh", "फ": "ph"}   # बड़े = "bade"


def _skeleton(word: str) -> str:
    """A word's consonant skeleton, the same for its Devanagari and its Roman
    Hinglish spelling ("नाखून" and "nakhun" -> "nkhn"). The fidelity check compared
    the Devanagari directed text with the Roman script word for word, matched
    nothing, and sent the Roman text to the voice engine -- Hindi read like an
    English speaker, no a/aa difference (creator, 2026-10-24)."""
    w = word.casefold()
    if re.search(r"[ऀ-ॿ]", w):
        out = []
        chars = list(w)
        for i, c in enumerate(chars):
            if c in _DEVA_CONSONANTS:
                nukta = i + 1 < len(chars) and chars[i + 1] == "़"
                out.append(_DEVA_NUKTA.get(c, _DEVA_CONSONANTS[c]) if nukta else _DEVA_CONSONANTS[c])
            elif c in "ंँ":          # anusvara / chandrabindu: a nasal
                out.append("n")
        w = "".join(out)
    else:
        w = (w.replace("chh", "ch").replace("w", "v").replace("f", "ph").replace("z", "j")
             .replace("q", "k").replace("x", "ks"))
        w = re.sub(r"[aeiou]", "", w)
    w = re.sub(r"(.)\1+", r"\1", w)                # doubled letters spelled either way
    s = w.replace("h", "")                         # aspiration is spelled inconsistently in Hinglish
    return s or w or "_"


def _content_words(text: str) -> List[str]:
    """Normalised words for the fidelity check: consonant skeletons, so the
    Devanagari directed text and the Roman Hinglish script compare as the same
    words (`_skeleton`)."""
    # `\w` alone splits Devanagari at its vowel signs and virama ("क्या" -> "क", "य").
    return [_skeleton(w) for w in re.findall(r"[\wऀ-ॿ]+", text or "", re.UNICODE)]


def _in_order_overlap(original: List[str], directed: List[str]) -> float:
    """The fraction of `original`'s words found in `directed`, in the same
    order (a simple in-order subsequence match, not an exact match -- the
    director is allowed to add cues and pauses between the script's words)."""
    if not original:
        return 1.0
    # A real alignment, not a greedy scan: one near-miss used to jump the scan far
    # ahead and lose every word after it.
    import difflib
    sm = difflib.SequenceMatcher(a=original, b=directed, autojunk=False)
    return sum(block.size for block in sm.get_matching_blocks()) / len(original)


#: At most one "(pause)"/"(beat)" cue per this many sentences: the director put one in
#: every sentence or two, and with the horror tempo the reel read "very slow" (creator,
#: 2026-10-24). The ones kept are the latest -- the reveal and the last line.
PAUSE_CUE_EVERY_SENTENCES = 6
_PAUSE_CUE_RE = re.compile(r"\(\s*(?:pause[^)]*|beat)\s*\)", re.IGNORECASE)


def cap_pause_cues(text: str) -> str:
    sentences = max(1, len(re.findall(r"[।.?!]", text or "")))
    keep = max(1, sentences // PAUSE_CUE_EVERY_SENTENCES)
    cues = list(_PAUSE_CUE_RE.finditer(text or ""))
    if len(cues) <= keep:
        return text
    drop = cues[:len(cues) - keep]
    out, last = [], 0
    for m in drop:
        out.append(text[last:m.start()])
        last = m.end()
    out.append(text[last:])
    return re.sub(r"[ 	]{2,}", " ", "".join(out))


_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def devanagari_english_words(text: str, progress: Callable[[str], None] = _noop) -> str:
    """English words left in Latin letters inside the Devanagari narration, written in
    Devanagari the way an Indian speaker says them ("warning" -> "वॉर्निंग"): the voice
    engine reads Latin letters with its Hindi voice and they came out wrong (creator,
    2026-10-24). One model call for the distinct words; cues like (pause) are kept;
    any word the model leaves out stays as it was."""
    cue_spans = [m.span() for m in re.finditer(r"\([^)]*\)", text or "")]

    def in_cue(pos: int) -> bool:
        return any(a <= pos < b for a, b in cue_spans)

    words = sorted({m.group(0) for m in _LATIN_WORD_RE.finditer(text or "") if not in_cue(m.start())})
    if not words:
        return text
    try:
        from app.services.shorts_desk import _agent_json
        progress(f"Writing {len(words)} English word(s) in Devanagari")
        data = _agent_json("NarrationDirector", {
            "task": ("Write each English word in Devanagari exactly as an Indian Hinglish speaker pronounces it "
                     "(warning -> वॉर्निंग, superstition -> सुपरस्टिशन, hospital -> हॉस्पिटल). Return only the map."),
            "words": words, "answer_format": {"map": {"word": "देवनागरी"}}}) or {}
        mapping = {k: str(v).strip() for k, v in (data.get("map") or {}).items()
                   if str(v).strip() and not _LATIN_WORD_RE.search(str(v))}
    except Exception as exc:  # noqa: BLE001 - keep the text as it is
        logger.warning("auto_story: English words not converted to Devanagari (%s)", exc)
        return text
    if not mapping:
        return text

    def swap(m: "re.Match[str]") -> str:
        if in_cue(m.start()):
            return m.group(0)
        return mapping.get(m.group(0)) or mapping.get(m.group(0).lower()) or m.group(0)

    return _LATIN_WORD_RE.sub(swap, text)


def direct_narration(text: str, channel: str, progress: Callable[[str], None] = _noop,
                      dramatic: Optional[str] = None, project=None) -> str:
    """The NarrationDirector pass (2026-10-23): spoken words only, intonation
    cues placed, and Hindi words in Devanagari, which the voice engine reads
    far better than Roman Hinglish. `dramatic` (VOICE_DELIVERY_PLAN.md S3) is
    the channel's own setting when not given explicitly.

    The directed text is kept only when it still says at least
    `NARRATION_FIDELITY_MIN` of the script's own words, in order (2026-10-24,
    Fable review #12) -- otherwise the raw spoken script narrates instead,
    logged here. Either way, when `project` is given, the directed attempt is
    saved to `script/narration_directed.txt` next to the script for review."""
    if dramatic not in VOICE_STYLE_DRAMATIC:
        dramatic = voice_style_for(channel).get("dramatic", "subtle")
    if len(text) * NARRATION_FIDELITY_MIN > NARRATION_DIRECT_MAX_CHARS:
        # Only the first NARRATION_DIRECT_MAX_CHARS are sent, so a longer script
        # can never keep enough of its words to pass the check below: skip the
        # model call (2026-10-26: six long stories each loaded a model onto a GPU
        # the render was using, timed out, and narrated the raw script anyway).
        logger.info("auto_story: %d-character script is too long to direct; narrating the raw script", len(text))
        return text
    out = ""
    try:
        from app.services.shorts_desk import _agent_json
        progress("Directing the narration (cues, Devanagari)")
        # One direction call at a time: several narrations started together
        # otherwise fill every model slot at once.
        with _direct_lock:
            data = _agent_json("NarrationDirector", {"channel": channel, "script": text[:NARRATION_DIRECT_MAX_CHARS],
                                                     "dramatic": dramatic,
                                                     "answer_format": {"text_devanagari": "...", "notes": ["..."]}}) or {}
        out = str(data.get("text_devanagari") or data.get("text") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_story: NarrationDirector failed (%s); using the raw text", exc)
    if project is not None and out:
        try:
            script_dir = os.path.join(project.get_project_dir(), "script")
            os.makedirs(script_dir, exist_ok=True)
            with open(os.path.join(script_dir, "narration_directed.txt"), "w", encoding="utf-8") as f:
                f.write(out)
        except OSError:
            logger.warning("auto_story: could not save narration_directed.txt for review")
    if not out:
        return text
    overlap = _in_order_overlap(_content_words(text), _content_words(out))
    if overlap >= NARRATION_FIDELITY_MIN:
        return cap_pause_cues(devanagari_english_words(out, progress))
    logger.warning("auto_story: NarrationDirector's text keeps only %.0f%% of the script's words in order "
                    "(need %.0f%%); narrating the raw script instead", overlap * 100, NARRATION_FIDELITY_MIN * 100)
    return text

def narrate(project, text: str, voice: str, progress: Callable[[str], None],
            style: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Synthesise `text` (retrying up to NARRATION_ATTEMPTS) and copy the wav to <project>/audio/narration.wav."""
    refuse_if_voice_clone_paused()
    audio_dir = os.path.join(project.get_project_dir(), "audio")
    os.makedirs(audio_dir, exist_ok=True)
    body = {"text": text, "language": "hi", "voice": voice,
            "style": dict(style) if style else {"exaggeration": 0.5, "pace": 1.0},
            # His reference voice is cloned directly by the engine (Chatterbox
            # with audio_prompt); seed-vc on top of it only costs minutes and
            # quality. Conversion is for an engine preset (a Kokoro voice) that
            # must end up sounding like him.
            "convert_to": (VOICE_DEFAULT if voice in KOKORO_PRESETS else None), "out_dir": audio_dir}
    errors: List[str] = []
    for attempt in range(NARRATION_ATTEMPTS):
        try:
            result = _narrate_once(body, progress)
            break
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc)[:300])
            logger.warning("auto_story narration attempt %d failed: %s", attempt + 1, exc)
            if attempt + 1 < NARRATION_ATTEMPTS:
                progress(f"Narration attempt {attempt + 1} failed ({str(exc)[:120]}); retrying")
                _sleep(NARRATION_BACKOFF_S[min(attempt, len(NARRATION_BACKOFF_S) - 1)])
    else:
        raise RuntimeError("Narration failed after %d attempts: %s" % (NARRATION_ATTEMPTS, " | ".join(errors)))
    dest = os.path.join(audio_dir, "narration.wav")
    src = result["wav"]
    if os.path.normcase(os.path.abspath(src)) != os.path.normcase(os.path.abspath(dest)):
        shutil.copy2(src, dest)
    return {"path": "audio/narration.wav", "source": src, "voice": voice,
            **{k: result.get(k) for k in ("seconds", "duration_s", "engine", "converted")},
            "attempts": len(errors) + 1, "at": _now()}


def _style_for_body(channel: str, override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The channel's saved voice style, minus `dramatic` (never sent to
    BuzzEdit), with any explicit per-call override layered on top."""
    style = {k: v for k, v in voice_style_for(channel).items() if k != "dramatic"}
    if isinstance(override, dict):
        mood = str(override.get("mood") or "").strip()
        if mood:
            style["mood"] = mood
        for key, (lo, hi) in VOICE_STYLE_RANGES.items():
            if override.get(key) is not None:
                try:
                    style[key] = max(lo, min(hi, float(override[key])))
                except (TypeError, ValueError):
                    pass
    return style


def voice_preview_start(channel: str, voice: Optional[str] = None, text: Optional[str] = None,
                         style: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Starts a BuzzEdit narration job for a quick preview of a channel's
    voice-and-delivery settings (VOICE_DELIVERY_PLAN.md S1). Returns the job id;
    the caller polls `voice_preview_status` and reads `voice_preview_audio_path`
    once it is done."""
    voice = voice or default_voice_for(channel)
    text = str(text or "").strip() or PREVIEW_SAMPLE_TEXT
    out_dir = os.path.join(STORE_DIR, "voice_previews")
    os.makedirs(out_dir, exist_ok=True)
    body = {"text": text, "language": "hi", "voice": voice, "style": _style_for_body(channel, style),
            "convert_to": (VOICE_DEFAULT if voice in KOKORO_PRESETS else None), "out_dir": out_dir}
    job = _narration_post(body)
    job_id = job.get("job_id")
    if not job_id:
        raise RuntimeError(f"BuzzEdit returned no narration job id: {str(job)[:200]}")
    return {"job_id": job_id, "state": job.get("state")}


def voice_preview_status(job_id: str) -> Dict[str, Any]:
    """The preview job's state, as BuzzEdit reports it."""
    return _narration_job(job_id)


def voice_preview_audio_path(job_id: str) -> str:
    """The preview's wav path, once the job is done."""
    job = _narration_job(job_id)
    if job.get("state") != "done":
        raise RuntimeError(f"The preview is not ready yet (state: {job.get('state')}).")
    wav = (job.get("result") or {}).get("wav")
    if not wav or not os.path.isfile(wav):
        raise RuntimeError(f"The preview file is not on disk: {wav}")
    return wav


def face_intro_clip(synthetic_take, brand: str) -> Optional[str]:
    """The brand's face-intro clip: synthetic_take's (config channel_formats), else the Story Desk's setting."""
    clip = synthetic_take.face_intro_clip_for(brand)
    if clip:
        return clip
    saved = str((settings().get("face_intro_clips") or {}).get(brand) or "")
    return saved if saved and os.path.isfile(saved) else None


def voices() -> List[str]:
    """The voices a narration can use: BuzzEdit's /api/narration/voices when it answers, else his."""
    names: List[str] = []
    try:
        from integrations.buzzedit_client import BuzzEditClient
        resp = BuzzEditClient()._get("/api/narration/voices", timeout=(3, 10))
        if resp.status_code < 400:
            data = resp.json()
            rows = data.get("voices") if isinstance(data, dict) else data
            for v in rows or []:
                name = v if isinstance(v, str) else (v.get("name") or v.get("id")) if isinstance(v, dict) else None
                if name:
                    name = os.path.splitext(os.path.basename(str(name)))[0]
                    if name not in names:
                        names.append(name)
    except Exception as exc:  # noqa: BLE001 - BuzzEdit down: his voice only
        logger.debug("narration voices unavailable: %s", exc)
    if VOICE_DEFAULT in names:
        names.remove(VOICE_DEFAULT)
    return [VOICE_DEFAULT] + names


def package_dir(project_id: str) -> Optional[str]:
    path = os.path.join(_load(project_id).get_project_dir(), "publish", "instagram")
    return path if os.path.isdir(path) else None


# --- run ---------------------------------------------------------------------------

def run(project_id: str, *, voice: str = VOICE_DEFAULT, publish: bool = False,
        orientation: Optional[str] = None, progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Narrate, build the take, queue the production and start the watcher.
    A reel format (or any vertical run that is not the long story) instead
    renders through BuzzEdit's vibe-reel narration mode (`_run_reel`, VR5):
    no take, no production queue, no watcher. Returns the record as it is
    when the project is queued, or the finished record for a reel.

    One video at a time (2026-10-26): the run first waits in line until no
    other video is being made (`video_slot`), its record saying who it waits
    for; from then until its production is queued it holds the slot."""
    from app.services import video_slot
    refuse_if_voice_clone_paused()
    say = progress or _noop
    project = _load(project_id)

    def waiting_for(ahead: Dict[str, Any]) -> None:
        # What `resume_waiting()` needs to put it back in line after a restart.
        rec = dict(project.metadata.get("auto_story") or {})
        rec.update(project_id=project_id, channel=project.brand, state="waiting", error=None,
                   waiting_for=ahead.get("title"), voice=voice, publish=bool(publish),
                   orientation=orientation, waiting_since=rec.get("waiting_since") or _now())
        _write_record(project_id, rec)

    with video_slot.turn(project_id, title=project.name, brand=project.brand, what="voice being made",
                         say=say, on_wait=waiting_for):
        return _run_now(project_id, voice=voice, publish=publish, orientation=orientation,
                        progress=lambda msg: (video_slot.set_doing(project_id, msg), say(msg)))


def _run_now(project_id: str, *, voice: str, publish: bool, orientation: Optional[str],
             progress: Callable[[str], None]) -> Dict[str, Any]:
    from app.services import produce_queue
    say = progress
    project = _load(project_id)
    if produce_queue.active_item_for(project_id):
        raise ValueError("This project is already in the production queue.")
    orientation = orientation or ("vertical" if project.metadata.get("orientation") == "vertical" else "landscape")
    if orientation not in ("vertical", "landscape"):
        raise ValueError(f"Unknown orientation: {orientation!r}")
    old = project.metadata.get("auto_story") or {}
    fmt = project.metadata.get("short_format") or old.get("format")
    rec: Dict[str, Any] = {
        "project_id": project_id, "channel": project.brand, "format": fmt, "length": old.get("length"),
        "voice": voice, "publish": bool(publish), "orientation": orientation, "state": "starting",
        "started_at": _now(), "steps": [], "error": None, "posted": {}, "final": None,
    }
    if fmt in REEL_FORMATS or (orientation == "vertical" and fmt != LONG_STORY):
        return _run_reel(project_id, project, rec, voice=voice, say=say)
    try:
        from integrations import synthetic_take  # lazy: a missing module is a clear error here

        clip = face_intro_clip(synthetic_take, project.brand)
        _step(rec, "script", "Reading the script", say)
        text = spoken_script(project, drop_greeting=bool(clip) and orientation == "landscape")
        script_hash = hashlib.sha1(f"{voice}|{text}".encode("utf-8")).hexdigest()[:16]
        previous = project.metadata.get("narration") or {}
        reusable = (previous.get("script_hash") == script_hash and previous.get("wav")
                    and os.path.isfile(str(previous.get("wav"))))
        if reusable:
            # The same script in the same voice is already narrated (a re-run
            # after a production fix, 2026-10-23): no second synthesis.
            rec["words"] = previous.get("words") or len(text.split())
            _step(rec, "narration", "Reusing the narration already made for this script", say)
            narration = dict(previous)
        else:
            text = direct_narration(text, project.brand, say, project=project)
            rec["words"] = len(text.split())
            _step(rec, "narration", f"Narrating {rec['words']} words in the '{voice}' voice", say)
            # Saved after the state change: the Projects page blinks the Voice
            # Recording step only while the record says "narration".
            _write_record(project_id, rec)
            narration = narrate(project, text, voice, say, style=_style_for_body(project.brand))
            narration["script_hash"] = script_hash
            narration["words"] = rec["words"]
        project = _load(project_id)
        project.metadata["narration"] = narration
        project.metadata["auto_story"] = rec
        project.save()

        _step(rec, "take", "Building the take" + (" with his face intro" if clip else " (no face-intro clip)"), say)
        wav = os.path.join(project.get_project_dir(), narration["path"])
        take = None
        take_errors: List[str] = []
        for attempt in range(TAKE_ATTEMPTS):
            try:
                take = synthetic_take.build_take(_load(project_id), wav, orientation=orientation, face_intro_clip=clip)
                break
            except Exception as exc:  # noqa: BLE001
                take_errors.append(str(exc)[:300])
                logger.warning("auto_story take attempt %d failed: %s", attempt + 1, exc)
        if not take or not take.get("path") or not os.path.isfile(take["path"]):
            raise RuntimeError("The take could not be built: " + (" | ".join(take_errors) or str(take)))
        rec["take"] = {k: take.get(k) for k in ("path", "duration_s", "face_intro_s", "orientation")}

        # The take's "face" after the intro is a dark still, so every second the
        # pictures do not cover is black (the first reel, 2026-10-23: 11 s of
        # pictures in 70 s). Pictures must cover everything after the intro:
        # full coverage, 35% clips and 65% stills with Ken Burns (2026-10-26: was
        # half and half; a 30-minute story's ~177 clips took ~13 GPU hours).
        full_pictures = {"target_coverage": 1.0, "video_broll_share": 0.35, "image_broll_share": 0.65}
        settings_override = {"face_layout": "face_intro", "face_intro_seconds": take.get("face_intro_s") or 0,
                             "review_mode": "none", **full_pictures}
        project = _load(project_id)
        project.metadata["recording_path"] = take["path"]
        # produce_api reads the review gate (and the coverage pair) from video_settings, not the override.
        project.metadata["video_settings"] = {**(project.metadata.get("video_settings") or {}), "review_mode": "none",
                                              **full_pictures}
        if orientation == "vertical":
            project.metadata["orientation"] = "vertical"
        else:
            # A synthetic take carries no Shorts in front of the story: never split it as a session.
            project.metadata["session_format"] = "long_only"
        _step(rec, "queued", "Queued for production", say)
        project.metadata["auto_story"] = rec
        project.save()

        item = None
        enqueue_errors: List[str] = []
        for attempt in range(ENQUEUE_ATTEMPTS):
            try:
                item = produce_queue.add(project_id, brand=project.brand, title=project.name,
                                         recording_path=take["path"], settings_override=settings_override,
                                         mode="record_first", precut=True)
                break
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001
                enqueue_errors.append(str(exc)[:300])
                _sleep(5.0)
        if item is None:
            raise RuntimeError("Could not queue the production: " + " | ".join(enqueue_errors))
        rec["queue_item_id"] = item["id"]
        rec["queued_at"] = _now()
        _live[project_id] = dict(rec)
    except Exception as exc:
        rec["error"] = str(exc)[:500]
        _step(rec, "failed", f"Failed: {str(exc)[:200]}", say)
        rec["finished_at"] = _now()
        try:
            _write_record(project_id, rec)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not save the failure record for %s", project_id)
        raise

    watcher = threading.Thread(target=_watch, args=(project_id, item["id"], say),
                               name=f"auto-story-{project_id}", daemon=True)
    _watchers[project_id] = watcher
    watcher.start()
    return dict(rec)


# --- the reel path (REELS_DESK_PLAN.md VR5) -------------------------------------------

#: `_run_reel` retries starting + following the vibe job once before giving up
#: (a transient BuzzEdit hiccup, not a reported failure) -- narration already
#: retries inside `narrate()`.
VIBE_REEL_ATTEMPTS = 2
VIBE_REEL_BACKOFF_S = 10.0
#: A narration past this multiple of the reel's own chosen length only logs a
#: warning on the record (REELS_DESK_PLAN.md VR9): the shot plan is asked for
#: the narration's real duration regardless, so the reel still comes out
#: fully covered -- just longer than asked for. The length is a target, not
#: a cap (creator follow-up, 2026-10-24): relative to the chosen length, only
#: warns past 1.5x it.
NARRATION_OVERRUN_FACTOR = 1.5


def _run_reel(project_id: str, project, rec: Dict[str, Any], *, voice: str,
              say: Callable[[str], None]) -> Dict[str, Any]:
    """VR5: narrate, plan the shots (`story_reel.plan_story_shots`), render
    through BuzzEdit's vibe-reel narration mode and package for Instagram --
    the model is `make_mood_reel`: no take, no production queue, no watcher.
    Returns the finished record; never raises without recording why first."""
    from app.services import story_reel
    from integrations.buzzedit_client import BuzzEditClient
    try:
        _step(rec, "script", "Reading the script", say)
        text = spoken_script(project, drop_greeting=False)
        rec["words"] = len(text.split())
        # The reel's own default param (VOICE_DEFAULT) is channel-blind; a
        # voice given explicitly by the caller still wins over it.
        resolved_voice = voice if voice != VOICE_DEFAULT else default_voice_for(project.brand)
        text = direct_narration(text, project.brand, say, project=project)
        style = _style_for_body(project.brand)
        # Reuse the narration already made for this exact (voice, style, text)
        # -- the same hash `run()` stores (STUDIO_DIRECTOR_PLAN.md enhancement
        # 2): a retry after a restart or a failed render must not re-synthesise
        # a voice track that is already sitting on disk.
        narration_hash = hashlib.sha1(json.dumps(
            {"voice": resolved_voice, "style": style, "text": text},
            sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
        previous = project.metadata.get("narration") or {}
        reusable = bool(previous.get("script_hash") == narration_hash and previous.get("path")
                       and os.path.isfile(os.path.join(project.get_project_dir(), str(previous["path"]))))
        _write_record(project_id, rec)
        if reusable:
            rec["words"] = previous.get("words") or rec["words"]
            _step(rec, "narration", "Reusing the narration already made for this script", say)
            narration = dict(previous)
        else:
            _step(rec, "narration", f"Narrating {rec['words']} words in the '{resolved_voice}' voice", say)
            _write_record(project_id, rec)
            narration = narrate(project, text, resolved_voice, say, style=style)
            narration["script_hash"] = narration_hash
            narration["words"] = rec["words"]
        project = _load(project_id)
        project.metadata["narration"] = narration
        project.metadata["auto_story"] = rec
        project.save()

        seconds = float(narration.get("duration_s") or narration.get("seconds") or 0.0)
        target_seconds = length_seconds(rec.get("length"))
        if target_seconds and seconds > target_seconds * NARRATION_OVERRUN_FACTOR:
            warning = (f"The narration ran {round(seconds)} s, well past the {round(target_seconds)} s "
                       f"target ({rec.get('words')} words); the shot plan below covers the real length.")
            rec.setdefault("warnings", []).append(warning)
            logger.warning("auto_story reel %s: %s", project_id, warning)
        _step(rec, "plan", "Planning the reel's shots", say)
        # Only stick_world reaches the reel planner as a style: the reel's
        # pictures were always photoreal, and still are for every other style.
        reel_style = "stick_world" if (project.metadata.get("video_settings") or {}).get("art_style") == "stick_world" \
            else "real"
        plan = story_reel.plan_story_shots(text, seconds, project.brand, rec.get("format") or "", reel_style)
        rec["world"] = plan.get("world")
        rec["shots"] = len(plan["shots"])
        pdir = project.get_project_dir()
        stage_dir = os.path.abspath(os.path.join(pdir, "production", "vibe_reel"))
        out_dir = os.path.join(pdir, "publish", "instagram")
        os.makedirs(stage_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
        _write_json(os.path.join(pdir, "production", "story_reel_plan.json"), plan)
        project.assets["story_reel_plan"] = "production/story_reel_plan.json"
        project.save()

        wav = os.path.join(pdir, narration["path"])
        body = story_reel.vibe_story_body(stage_dir, "reel", plan, wav, text)
        rec["request"] = {k: body[k] for k in ("art_style", "world", "shots", "character", "ambience")}
        _step(rec, "rendering", "Rendering the story reel in BuzzEdit", say)
        _write_record(project_id, rec)

        client = BuzzEditClient()
        result = None
        vibe_errors: List[str] = []
        for attempt in range(VIBE_REEL_ATTEMPTS):
            try:
                job = client.vibe_reel(body)
                job_id = job.get("job_id")
                if not job_id:
                    raise RuntimeError(f"BuzzEdit returned no vibe reel job id: {str(job)[:200]}")
                rec["vibe_job_id"] = job_id
                # On disk before the (possibly very long) follow starts, so a
                # Studio restart mid-render can find this job again
                # (`resume_watchers`, STUDIO_DIRECTOR_PLAN.md enhancement 2).
                _write_record(project_id, rec)
                result = _follow_vibe_job(client, job_id, rec, say)
                break
            except Exception as exc:  # noqa: BLE001 - one retry on a transient BuzzEdit error
                vibe_errors.append(str(exc)[:300])
                logger.warning("auto_story reel vibe attempt %d failed: %s", attempt + 1, exc)
                if attempt + 1 < VIBE_REEL_ATTEMPTS:
                    say(f"The vibe reel attempt {attempt + 1} failed ({str(exc)[:120]}); retrying")
                    _sleep(VIBE_REEL_BACKOFF_S)
        if result is None:
            raise RuntimeError("The vibe reel failed after %d attempt(s): %s" %
                               (VIBE_REEL_ATTEMPTS, " | ".join(vibe_errors)))
        video = result.get("video")
        if not video or not os.path.isfile(video):
            raise RuntimeError(f"The vibe reel finished with no video file on disk: {result}")

        final = os.path.join(out_dir, "reel.mp4")
        shutil.copy2(video, final)
        nomusic = result.get("video_nomusic")
        if nomusic and os.path.isfile(nomusic):
            shutil.copy2(nomusic, os.path.join(out_dir, "reel_nomusic.mp4"))
        cover = result.get("cover")
        if cover and os.path.isfile(cover):
            shutil.copy2(cover, os.path.join(out_dir, "cover.jpg"))
            rec["cover"] = os.path.join(out_dir, "cover.jpg")

        # The caption comes from the SEO package or the Short package's own
        # caption/hashtags (`_publish_text`, `instagram_package`'s own source);
        # the three deliverables are BuzzEdit's own, copied in above.
        project = _load(project_id)
        text_pkg = _publish_text(project)
        with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(text_pkg["caption"].strip() + "\n")
        rec["final"] = final
        rec["duration_s"] = result.get("duration_s")
        # Instagram only, like a mood reel: a reel is never sent to YouTube.
        rec["posted"] = {"instagram": "packaged", "package_dir": out_dir}
        rec["package_dir"] = out_dir
        # Ask before publishing (STUDIO_DIRECTOR_PLAN.md, Fable review #10):
        # a freshly packaged reel waits for the creator's review by default.
        rec["review"] = rec.get("review") or {"state": "needs_review", "at": _now(), "reason": None}
        _step(rec, "packaged", "Packaged for Instagram", say)
        rec["finished_at"] = _now()
        _write_record(project_id, rec)
    except Exception as exc:
        rec["error"] = str(exc)[:500]
        _step(rec, "failed", f"Failed: {str(exc)[:200]}", say)
        rec["finished_at"] = _now()
        try:
            _write_record(project_id, rec)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not save the reel failure record for %s", project_id)
        raise

    return dict(rec)


#: A record in one of these states is finished -- nothing to resume.
TERMINAL_STATES = ("failed", "packaged", "published")


def _resume_reel_job(project_id: str, rec: Dict[str, Any], vibe_job_id: str) -> None:
    """Re-attach to a vibe-reel job still rendering on BuzzEdit after a
    Studio restart lost the thread that was following it (`resume_watchers`,
    STUDIO_DIRECTOR_PLAN.md enhancement 2): follows it to the end and
    packages the result the way `_run_reel`/`make_mood_reel` would have.
    Runs on its own thread; never raises."""
    from integrations.buzzedit_client import BuzzEditClient
    say = _noop
    _live[project_id] = dict(rec)
    try:
        client = BuzzEditClient()
        result = _follow_vibe_job(client, vibe_job_id, rec, say)
        video = result.get("video")
        if not video or not os.path.isfile(video):
            raise RuntimeError(f"The vibe reel finished with no video file on disk: {result}")
        project = _load(project_id)
        pdir = project.get_project_dir()
        out_dir = os.path.join(pdir, "publish", "instagram")
        os.makedirs(out_dir, exist_ok=True)
        final = os.path.join(out_dir, "reel.mp4")
        shutil.copy2(video, final)
        nomusic = result.get("video_nomusic")
        if nomusic and os.path.isfile(nomusic):
            shutil.copy2(nomusic, os.path.join(out_dir, "reel_nomusic.mp4"))
        cover = result.get("cover")
        if cover and os.path.isfile(cover):
            shutil.copy2(cover, os.path.join(out_dir, "cover.jpg"))
            rec["cover"] = os.path.join(out_dir, "cover.jpg")
        try:
            text_pkg = _publish_text(project)
            with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
                f.write(text_pkg["caption"].strip() + "\n")
        except Exception:  # noqa: BLE001 - the video matters more than the caption
            logger.warning("auto_story resume: could not write the caption for %s", project_id)
        rec["final"] = final
        rec["duration_s"] = result.get("duration_s")
        rec["posted"] = {"instagram": "packaged", "package_dir": out_dir}
        rec["package_dir"] = out_dir
        rec["review"] = rec.get("review") or {"state": "needs_review", "at": _now(), "reason": None}
        _step(rec, "packaged", "Packaged for Instagram (resumed after a Studio restart)", say)
        rec["finished_at"] = _now()
        _write_record(project_id, rec)
    except Exception as exc:  # noqa: BLE001 - never raise out of a resumed thread
        logger.warning("auto_story: resumed reel job for %s failed (%s)", project_id, exc)
        rec["error"] = str(exc)[:500]
        _step(rec, "failed", f"Failed: {str(exc)[:200]}", say)
        rec["finished_at"] = _now()
        try:
            _write_record(project_id, rec)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not save the resumed-reel failure record for %s", project_id)
    finally:
        _live.pop(project_id, None)


def resume_watchers() -> List[str]:
    """After a Studio restart: every unfinished record lost its thread with the
    old process.

    * queued/producing/publishing (the long-story, production-queue path,
      S2's known gap c, 2026-10-23): a watcher is started again for every
      such project whose queue item is still alive, so it still publishes
      and packages when the production ends.
    * every other non-terminal state (script/narration/take/plan/rendering/
      starting -- the reel path, and the long-story path before it is
      queued, STUDIO_DIRECTOR_PLAN.md enhancement 2, Fable review row 8): a
      vibe-reel job BuzzEdit still reports "queued"/"running" gets a fresh
      follower thread (`_resume_reel_job`); anything else (no job id, or
      BuzzEdit no longer has it/reports it done/failed) is marked `failed`
      with "Studio restarted -- press Retry" instead of being left stuck
      forever -- the Story Desk's Retry button re-runs the same project.
    """
    from app.services import produce_queue, video_slot
    resumed: List[str] = []
    waiting: List[Dict[str, Any]] = []
    for rec in list_records():
        pid = rec.get("project_id")
        state = rec.get("state")
        if not pid or state in TERMINAL_STATES:
            continue
        if _watchers.get(pid) and _watchers[pid].is_alive():
            continue
        if state == "waiting":
            # In line for its turn (one video at a time): back in line, in
            # the order it first joined.
            try:
                waiting.append(dict(record(pid) or rec))
            except Exception:  # noqa: BLE001
                waiting.append(dict(rec))
            continue
        if state in ("queued", "producing", "publishing"):
            try:
                item = produce_queue.latest_item_for(pid)
            except Exception:  # noqa: BLE001
                item = None
            if not item:
                continue
            try:
                project = _load(pid)
                _live[pid] = dict(project.metadata.get("auto_story") or {})
            except Exception:  # noqa: BLE001
                continue
            watcher = threading.Thread(target=_watch, args=(pid, item["id"], _noop),
                                       name=f"auto-story-{pid}", daemon=True)
            _watchers[pid] = watcher
            watcher.start()
            resumed.append(pid)
            continue

        # The reel path (or the long-story path before it reached "queued"):
        # no queue item, no watcher thread -- only a vibe job BuzzEdit still
        # reports rendering is worth re-attaching to. `list_records()` is a
        # reduced view (no `vibe_job_id`); the full record carries it.
        try:
            full_rec: Dict[str, Any] = dict(record(pid) or rec)
        except Exception:  # noqa: BLE001
            full_rec = dict(rec)
        vibe_job_id = full_rec.get("vibe_job_id")
        still_rendering = False
        if vibe_job_id:
            try:
                from integrations.buzzedit_client import BuzzEditClient
                job = BuzzEditClient().vibe_reel_job(vibe_job_id)
                still_rendering = job.get("state") in ("queued", "running")
            except Exception:  # noqa: BLE001 - BuzzEdit unreachable or job unknown: not rendering
                still_rendering = False
        if still_rendering:
            watcher = threading.Thread(target=_resume_reel_job, args=(pid, full_rec, vibe_job_id),
                                       name=f"auto-story-resume-{pid}", daemon=True)
            _watchers[pid] = watcher
            watcher.start()
            resumed.append(pid)
            continue

        try:
            full_rec["error"] = full_rec.get("error") or "Studio restarted"
            # Not `_step`: that holds on the master pause, and this runs at
            # startup -- a paused Studio never came up (2026-10-27).
            full_rec["state"] = "failed"
            full_rec.setdefault("steps", []).append({"at": _now(), "state": "failed",
                                                     "message": "Studio restarted -- press Retry"})
            full_rec["finished_at"] = _now()
            _write_record(pid, full_rec)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not mark %s failed after a restart", pid)
    waiting.sort(key=lambda r: str(r.get("waiting_since") or r.get("updated_at") or ""))
    for rec in waiting:
        pid = rec["project_id"]
        try:
            project = _load(pid)
            video_slot.reserve(pid, title=project.name, brand=project.brand)
            start_job("run", run, pid, voice=rec.get("voice") or default_voice_for(project.brand),
                      publish=bool(rec.get("publish")), orientation=rec.get("orientation"))
            resumed.append(pid)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not put %s back in line after a restart", pid)
    if resumed:
        logger.info("auto_story: resumed %d watcher(s): %s", len(resumed), ", ".join(resumed))
    return resumed


def wait(project_id: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Block until the project's watcher has finished (or `timeout`); returns the record."""
    watcher = _watchers.get(project_id)
    if watcher is not None:
        watcher.join(timeout)
    return record(project_id)


# --- the watcher and publishing -------------------------------------------------------------

def _watch(project_id: str, item_id: str, say: Callable[[str], None]) -> None:
    from app.services import produce_queue
    rec = _live.get(project_id) or {}
    try:
        started = time.time()
        last_status = None
        item: Optional[Dict[str, Any]] = None
        while True:
            items = produce_queue.snapshot().get("items") or []
            item = next((i for i in items if i.get("id") == item_id), None)
            status = (item or {}).get("status")
            if item is None or status not in produce_queue.ACTIVE_STATES:
                break
            if status != last_status:
                _step(rec, "producing", f"Production: {status}", say)
                last_status = status
            if time.time() - started > WATCH_MAX_S:
                break
            _sleep(WATCH_POLL_S)
        if item is None:
            raise RuntimeError("The production item left the queue (removed).")
        status = item.get("status")
        if status in produce_queue.ACTIVE_STATES:
            raise RuntimeError(f"Still '{status}' in the production queue after {int(WATCH_MAX_S / 3600)} h.")
        if status != "done":
            raise RuntimeError(f"Production {status}: {item.get('error') or 'no detail'}")
        _step(rec, "publishing", "Production done; publishing", say)
        project = _load(project_id)
        final = _final_path(project)
        if not final:
            raise RuntimeError("The production finished but the final file is not on disk.")
        rec["final"] = final
        # Ask before publishing (STUDIO_DIRECTOR_PLAN.md, Fable review #10):
        # the Instagram package is always made here, but the real upload
        # (Instagram's `post_instagram`) and the YouTube upload both wait for
        # `approve()` -- so this always calls `publish_final` with
        # `publish=False` regardless of what the creator asked for.
        rec["posted"] = publish_final(project, final, publish=False)
        rec["review"] = rec.get("review") or {"state": "needs_review", "at": _now(), "reason": None}
        if rec.get("publish"):
            rec["posted"]["youtube"] = {"skipped": "waiting for your approval before publishing"}
        rec["package_dir"] = rec["posted"].get("package_dir")
        state = "packaged" if rec["posted"].get("instagram") == "packaged" else "failed"
        _step(rec, state, ("Packaged for Instagram" + ("; waiting for your approval to publish to YouTube"
              if rec.get("publish") else "")) if state == "packaged" else "Publishing failed", say)
    except Exception as exc:  # noqa: BLE001 - never raise out of the watcher
        logger.exception("auto_story watcher for %s", project_id)
        rec["error"] = str(exc)[:500]
        _step(rec, "failed", f"Failed: {str(exc)[:200]}", say)
    rec["finished_at"] = _now()
    try:
        _write_record(project_id, rec)
    except Exception:  # noqa: BLE001
        logger.exception("auto_story: could not save the record for %s", project_id)
    _live.pop(project_id, None)


def _final_path(project) -> Optional[str]:
    for key in ("final_output_path", "output_path"):
        path = str(project.metadata.get(key) or "")
        if path and os.path.isfile(path):
            return path
    return None


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _seo(project) -> Optional[Dict[str, Any]]:
    from integrations import youtube_publish as yt
    rel = (project.assets or {}).get("seo_package") or "publish/publish.json"
    try:
        with open(os.path.join(project.get_project_dir(), rel), encoding="utf-8") as f:
            return yt.parse_seo_package(f.read())
    except OSError:
        return None


def _publish_text(project) -> Dict[str, Any]:
    """{title, description, tags, caption, hashtags} from the SEO package, else the Short package."""
    from integrations import youtube_publish as yt
    seo = _seo(project)
    pkg = _read_json(os.path.join(project.get_project_dir(), "publish", "short_package.json")) or {}
    hashtags = [str(h) if str(h).startswith("#") else f"#{h}" for h in (pkg.get("hashtags") or []) if str(h).strip()]
    if seo and seo.get("titles"):
        hashtags = seo.get("hashtags") or hashtags
        description = yt.description_with_hashtags(seo.get("description") or "", hashtags)
        return {"title": seo["titles"][0], "description": description, "tags": seo.get("tags") or [],
                "caption": description, "hashtags": hashtags, "source": "seo_package"}
    title = str(pkg.get("title") or project.name)
    caption = str(pkg.get("caption") or pkg.get("hook_line") or title)
    description = yt.description_with_hashtags(caption, hashtags)
    return {"title": title, "description": description, "tags": [h.lstrip("#") for h in hashtags],
            "caption": description, "hashtags": hashtags, "source": "short_package" if pkg else "project"}


def _signed_in_channel(brand: str) -> Optional[str]:
    from integrations import youtube_publish as yt
    cid = yt.channel_for_brand(brand)
    if not cid:
        return None
    for ch in yt.status().get("channels") or []:
        if ch.get("id") == cid and ch.get("signed_in"):
            return cid
    return None


def _cover_frame(video: str, out: str) -> None:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError("ffmpeg is not on PATH")
    proc = subprocess.run([binary, "-y", "-loglevel", "error", "-ss", "1", "-i", video, "-frames:v", "1",
                           "-q:v", "2", out], capture_output=True, text=True, timeout=120, creationflags=_NO_WINDOW)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError(f"ffmpeg could not take the cover frame: {proc.stderr[-300:]}")


def instagram_package(project, final: str, text: Dict[str, Any]) -> Dict[str, Any]:
    out_dir = os.path.join(project.get_project_dir(), "publish", "instagram")
    os.makedirs(out_dir, exist_ok=True)
    reel = os.path.join(out_dir, "reel.mp4")
    shutil.copy2(final, reel)
    with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
        f.write(text["caption"].strip() + "\n")
    out: Dict[str, Any] = {"dir": out_dir, "reel": reel}
    try:
        _cover_frame(reel, os.path.join(out_dir, "cover.jpg"))
        out["cover"] = os.path.join(out_dir, "cover.jpg")
    except Exception as exc:  # noqa: BLE001 - the package stands without a cover
        out["cover_error"] = str(exc)[:300]
    return out


def _publish_youtube_now(project, final: str) -> Dict[str, Any]:
    """The actual YouTube upload: `publish_final`'s own youtube branch, kept
    as its own function so `approve()` can call it once the creator's
    approval arrives, not just while `publish_final` is on the stack."""
    try:
        text = _publish_text(project)
    except Exception as exc:  # noqa: BLE001
        text = {"title": project.name, "description": project.name, "tags": [], "source": f"fallback ({exc})"}
    cid = _signed_in_channel(project.brand)
    if not cid:
        return {"skipped": f"no signed-in YouTube channel for {project.brand}"}
    try:
        from integrations import youtube_publish as yt
        result = yt.upload(final, channel_id=cid, title=text["title"], description=text["description"],
                           tags=text["tags"])
        return {"channel_id": cid, **{k: result.get(k) for k in ("video_id", "url", "privacy")},
                "at": _now(), "text_from": text.get("source")}
    except Exception as exc:  # noqa: BLE001
        return {"channel_id": cid, "error": str(exc)[:300]}


def publish_final(project, final: str, *, publish: bool) -> Dict[str, Any]:
    """§3.4: the Instagram package always; YouTube only when asked and signed
    in. `_watch` always calls this with `publish=False` now (ask before
    publishing, STUDIO_DIRECTOR_PLAN.md) and `approve()` performs the real
    upload once the creator approves. Never raises."""
    posted: Dict[str, Any] = {}
    try:
        text = _publish_text(project)
    except Exception as exc:  # noqa: BLE001
        text = {"title": project.name, "description": project.name, "tags": [], "caption": project.name,
                "hashtags": [], "source": f"fallback ({exc})"}
    try:
        pkg = instagram_package(project, final, text)
        posted["instagram"] = "packaged"
        posted["package_dir"] = pkg["dir"]
        if pkg.get("cover_error"):
            posted["instagram_cover_error"] = pkg["cover_error"]
        if (project.metadata.get("orientation") != "vertical"):
            posted["instagram_note"] = "landscape video: not a reel as it is"
    except Exception as exc:  # noqa: BLE001
        posted["instagram"] = {"error": str(exc)[:300]}
    if not publish:
        posted["youtube"] = {"skipped": "publish is off"}
        return posted
    posted["youtube"] = _publish_youtube_now(project, final)
    return posted


# --- the approval gate (STUDIO_DIRECTOR_PLAN.md: ask before publishing; Fable review #10) ---

def _decisions_log_path() -> str:
    """knowledge/decisions/log.jsonl, next to `STORE_DIR` (so a test sandbox
    that moves `STORE_DIR` gets an isolated log too)."""
    return os.path.join(os.path.dirname(STORE_DIR), "decisions", "log.jsonl")


def _log_decision(rec: Dict[str, Any], action: str, reason: Optional[str] = None) -> None:
    """One line of `{at, project_id, channel, format, action, reason}` for
    the Studio Director to learn from later (enhancement 3)."""
    path = _decisions_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = {"at": _now(), "project_id": rec.get("project_id"), "channel": rec.get("channel") or rec.get("brand"),
              "format": rec.get("format"), "action": action, "reason": reason}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def approve(project_id: str) -> Dict[str, Any]:
    """Approves a packaged/finished record for publishing: the Instagram
    scheduler, `post_instagram(force=False)` and the YouTube auto-publish
    path all wait for this. When the record asked for YouTube (`publish`)
    and it has not uploaded yet, this is what actually sends it."""
    project = _load(project_id)
    rec = dict(project.metadata.get("auto_story") or {})
    if not rec:
        raise ValueError("This project has no auto-story record.")
    rec["review"] = {"state": "approved", "at": _now(), "reason": None}
    final = rec.get("final")
    if rec.get("publish") and final and os.path.isfile(final):
        already = (rec.get("posted") or {}).get("youtube") or {}
        if not already.get("video_id"):
            posted = dict(rec.get("posted") or {})
            posted["youtube"] = _publish_youtube_now(project, final)
            rec["posted"] = posted
            if posted["youtube"].get("video_id"):
                rec["state"] = "published"
    _write_record(project_id, rec)
    return rec


def reject(project_id: str, reason: str = "") -> Dict[str, Any]:
    """Rejects a packaged/finished record; the reason is kept on the record
    and logged for the Studio Director to learn from later."""
    project = _load(project_id)
    rec = dict(project.metadata.get("auto_story") or {})
    if not rec:
        raise ValueError("This project has no auto-story record.")
    rec["review"] = {"state": "rejected", "at": _now(), "reason": str(reason or "").strip()[:500]}
    _write_record(project_id, rec)
    _log_decision(rec, "reject", rec["review"]["reason"])
    return rec


def regenerate(project_id: str, progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Re-runs `make()` with the same channel/format/length/theme as
    `project_id`'s own record -- a fresh attempt; the rejected/old one is
    left exactly as it is."""
    rec = record(project_id) or {}
    channel, fmt = rec.get("channel") or rec.get("brand"), rec.get("format")
    if not channel or not fmt:
        raise ValueError("This project has no auto-story record to regenerate from.")
    return make(channel, fmt, rec.get("length"), voice=rec.get("voice") or VOICE_DEFAULT,
               publish=bool(rec.get("publish")), theme=rec.get("theme"), progress=progress)


def delete_record(project_id: str) -> Dict[str, Any]:
    """Deletes the project directory and its auto-story record."""
    from executive.project import project_manager
    _live.pop(project_id, None)
    project_manager.delete_project(project_id)
    return {"status": "deleted", "project_id": project_id}


def archive_record(project_id: str, archived: bool = True) -> Dict[str, Any]:
    """Sets project archived status for an auto story."""
    from app.services import project_archive
    project_archive.set_archived(project_id, archived)
    project = _load(project_id)
    rec = dict(project.metadata.get("auto_story") or {})
    rec["archived"] = archived
    _write_record(project_id, rec)
    return {**rec, "archived": archived}


# --- posting to Instagram (REELS_DESK_PLAN.md R7) --------------------------------------------

def _instagram_posted(rec: Dict[str, Any]) -> bool:
    """True once `posted.instagram` carries a permalink (a packaging note or
    a failed posting attempt does not count)."""
    ig = (rec.get("posted") or {}).get("instagram")
    return isinstance(ig, dict) and bool(ig.get("permalink"))


def post_instagram(project_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Posts a packaged record's `reel.mp4` (with `caption.txt`) to Instagram.
    Idempotent: a record already posted (a permalink on file) is skipped
    unless `force`. Raises only when there is no package to post, or (unless
    `force`) when it is not approved yet (STUDIO_DIRECTOR_PLAN.md: ask before
    publishing, Fable review #10); an actual posting failure is recorded on
    `posted.instagram` instead, never raised."""
    from integrations import instagram_publish as ig

    project = _load(project_id)
    rec = dict(project.metadata.get("auto_story") or {})
    posted = dict(rec.get("posted") or {})
    if _instagram_posted(rec) and not force:
        return posted["instagram"]
    pdir = package_dir(project_id)
    video = os.path.join(pdir, "reel.mp4") if pdir else ""
    if not pdir or not os.path.isfile(video):
        raise ValueError("This project has no Instagram package yet.")
    if not force and (rec.get("review") or {}).get("state") != "approved":
        raise ValueError("This project is not approved for publishing yet.")
    fmt = rec.get("format")
    account = ig.account_for(project.brand, fmt)
    if not account:
        where = f"{project.brand}/{fmt}" if fmt else project.brand
        posted["instagram"] = {"error": f"No Instagram account is routed for {where}. "
                               f"Add a route under Settings -> Instagram.", "at": _now()}
        rec["posted"] = posted
        _write_record(project_id, rec)
        return posted["instagram"]
    try:
        with open(os.path.join(pdir, "caption.txt"), encoding="utf-8") as f:
            caption = f.read().strip()
    except OSError:
        caption = project.name
    conf = ig.account_settings(account)
    if conf.get("caption_suffix"):
        caption = (caption + "\n\n" + conf["caption_suffix"]).strip()
    caption = ig.trim_caption(caption)
    # `_cover_frame` always takes the cover at the 1 s mark; when there is no
    # cover the upload falls back to Instagram's own default frame.
    thumb_offset_ms = 1000 if os.path.isfile(os.path.join(pdir, "cover.jpg")) else None
    try:
        result = ig.publish_reel(account, video, caption, thumb_offset_ms=thumb_offset_ms)
        posted["instagram"] = {"permalink": result.get("permalink", ""), "media_id": result["media_id"], "at": _now()}
        logger.info("auto_story: posted %s to Instagram via %s (%s).", project_id, account,
                    posted["instagram"]["permalink"])
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        posted["instagram"] = {"error": str(exc)[:300], "at": _now()}
        logger.warning("auto_story: posting %s to Instagram via %s failed: %s", project_id, account, exc)
    rec["posted"] = posted
    _write_record(project_id, rec)
    return posted["instagram"]


# --- make ------------------------------------------------------------------------------

def _set_style(project_id: str, style: Optional[str]) -> None:
    if not style:
        return
    from integrations.art_style import ART_STYLES
    if style not in ART_STYLES:
        raise ValueError(f"Unknown art style: {style!r}")
    project = _load(project_id)
    project.metadata["video_settings"] = {**(project.metadata.get("video_settings") or {}), "art_style": style}
    project.save()


#: A channel's default medium when its format names none (STICK_WORLD_PLAN.md).
CHANNEL_ART_STYLE_DEFAULTS: Dict[str, str] = {"TheTallStoryteller": "stick_world"}


def _format_art_style(channel: str, fmt: str) -> Optional[str]:
    """A format's own default medium (Story Desk FORMATS rows,
    STICK_WORLD_PLAN.md SW3 -- e.g. Beyond3Baje's `what_if`/`anomaly_file`/
    `case_file`/`unsolved` and every TheTallStoryteller format default to
    `stick_world`), used by `make()` when the request names none."""
    from app.services import shorts_desk
    own = shorts_desk.FORMATS.get(channel, {}).get(fmt, {}).get("art_style") if fmt else None
    # TheTallStoryteller's genre formats (folk_tale, mystery, history, ...)
    # are not Story Desk rows, so the channel itself carries the default.
    return own or CHANNEL_ART_STYLE_DEFAULTS.get(channel)


def _make_long(channel: str, length: Any, say: Callable[[str], None]) -> str:
    from app.services import longform_nightly as lf
    conf = lf.settings()
    try:
        minutes = float(length) if length not in (None, "") else LONG_DEFAULT_MINUTES
    except (TypeError, ValueError):
        raise ValueError(f"A long story's length is a number of minutes, not {length!r}.")
    minutes = max(LONG_MIN_MINUTES, min(LONG_MAX_MINUTES, minutes))
    nf = lf.next_format(channel)
    instructions = "\n\n".join(x for x in ((conf["instructions"].get(channel) or "").strip(), nf[1] if nf else "") if x)
    say("Planning the story")
    chosen = None
    try:
        chosen = lf.plan(channel, minutes, instructions, [], say)
    except Exception as exc:  # noqa: BLE001 - fall back to the creator's own list, as the nightly does
        say(f"The strategist could not plan ({str(exc)[:120]}); using the top vault / Idea Dump topic")
        topic = lf._fallback_topic(channel, [])
        if topic:
            chosen = {"topic": topic, "plan": {}}
    if not chosen:
        raise RuntimeError("No topic in the vault or the Idea Dump for a long story.")
    say("Researching and writing the script")
    built = lf.build(channel, chosen["topic"], minutes, say, plan=chosen.get("plan") or {},
                     instructions=instructions, episode_format=nf[0] if nf else "")
    return built["project_id"]


def _make_short(channel: str, fmt: str, length: Any, say: Callable[[str], None]) -> str:
    from app.services import shorts_desk
    if fmt not in shorts_desk.FORMATS.get(channel, {}):
        raise ValueError(f"{fmt!r} is not a {channel} format.")
    filters = {"length": str(length)} if length else {}
    say("Finding a story")
    found = shorts_desk.find(channel, fmt, filters, count=3, progress=say)
    cands = found.get("candidates") or []
    if not cands:
        raise RuntimeError(found.get("error") or "The search found nothing to build.")
    say(f"Writing the script: {cands[0].get('best_title') or cands[0].get('title')}")
    return shorts_desk.build(channel, fmt, cands[0])["id"]


def make(channel: str, fmt: str, length: Any = None, *, voice: str = VOICE_DEFAULT, publish: bool = False,
         style: Optional[str] = None, theme: Optional[str] = None,
         progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Create the project and its script with the existing writers, then run() it.
    Returns the record (its `project_id` is the new project). `theme` only
    reaches a mood reel (REELS_DESK_PLAN.md §6): it has no voice and never
    touches the production queue, so `voice`/`publish` do not apply to it."""
    say = progress or _noop
    from app.services import mood_reel
    if fmt != mood_reel.KEY:
        refuse_if_voice_clone_paused()   # before a script is written for nothing
    from app.services import master_control
    master_control.wait_if_paused("auto_story: start", say)
    from app.api.produce_api import ensure_buzzedit_running
    ensure_buzzedit_running(timeout=180.0)
    wait_for_reel_slot(say)
    if fmt == mood_reel.KEY:
        return make_mood_reel(channel, length, style=style, theme=theme, progress=progress)
    if fmt == LONG_STORY:
        project_id = _make_long(channel, length, say)
        orientation = "landscape"
    else:
        # Raat3Baje / Beyond3Baje story and anomaly reels are one minute (creator, 2026-10-23).
        # Resolved here (not just passed to `_make_short`) so the record below, and the word
        # budget `_run_reel` reads from it later (REELS_DESK_PLAN.md VR9), see the real target
        # even when the caller named none.
        length = length or STORY_REEL_LENGTH
        project_id = _make_short(channel, fmt, length, say)
        orientation = "vertical"
    if not style:
        # A long story's chosen format (rotation picks it inside _make_long)
        # is read back from its own metadata; a short's is just `fmt`.
        format_key = fmt
        if fmt == LONG_STORY:
            format_key = _load(project_id).metadata.get("episode_format") or ""
        style = _format_art_style(channel, format_key)
    _set_style(project_id, style)
    project = _load(project_id)
    project.metadata["auto_story"] = {"project_id": project_id, "channel": channel, "format": fmt,
                                      "length": length, "state": "scripted", "started_at": _now()}
    project.save()
    return run(project_id, voice=voice, publish=publish, orientation=orientation, progress=progress)


REEL_SLOT_WAIT_S = 2 * 3600.0
#: The writer's target for a narrated reel when the caller names none.
STORY_REEL_LENGTH = "1 minute (60 seconds)"


def wait_for_reel_slot(say: Callable[[str], None] = _noop) -> None:
    """Hold a new reel until BuzzEdit has finished the one it is rendering: its first
    steps (poem search, script, plan, narration) load the LLM or the TTS, which starved
    ComfyUI mid-clip when two reels overlapped (2026-10-23 batch: 3 clip timeouts)."""
    from integrations.buzzedit_client import BuzzEditClient
    client = BuzzEditClient()
    deadline = time.time() + REEL_SLOT_WAIT_S
    told = False
    while client.vibe_reel_busy() and time.time() < deadline:
        if not told:
            say("Waiting for BuzzEdit to finish the reel it is rendering")
            told = True
        _sleep(30.0)


# --- mood reel (REELS_DESK_PLAN.md §6, VR2) ------------------------------------------------

def _new_mood_project(channel: str, theme: str):
    """A fresh vertical project for a mood reel (the Shorts desk's workflow)."""
    from app.services.shorts_desk import WORKFLOW
    from executive.project import project_manager
    for attempt in range(5):
        try:
            return project_manager.create_project(name=f"Mood reel {theme} {uuid.uuid4().hex[:4]}", brand=channel,
                                                  workflow_name=WORKFLOW)
        except ValueError:
            continue
    raise RuntimeError("Could not create a unique project id.")


#: A BuzzEdit vibe-reel render has no fixed ceiling (a still or two can still
#: take minutes each): the wait ends only on a reported failure or this long
#: with no change in its progress or message.
VIBE_POLL_S = 5.0
# A clip BuzzEdit retries (15 min each, up to 3 tries) reports no progress meanwhile.
VIBE_STALL_S = 75 * 60.0
#: A BuzzEdit restart answers connection errors / 404 for a few seconds until it is
#: back up; tolerated the same way `_narrate_once` tolerates a lost connection
#: (STUDIO_DIRECTOR_PLAN.md enhancement 2, Fable review row 7) before giving up.
VIBE_FOLLOW_MISS_S = 10 * 60.0


def _follow_vibe_job(client, job_id: str, rec: Dict[str, Any], say: Callable[[str], None]) -> Dict[str, Any]:
    """Follow `GET /api/reels/jobs/{id}` until it is done or failed. Returns the
    job's `result` (`{video, cover, duration_s, shots, failures}`).

    Tolerates a BuzzEdit restart: a connection error or a 404 (the job's own
    record is briefly unreachable while it comes back up) is polled through
    for up to `VIBE_FOLLOW_MISS_S`, not raised on the first miss -- the job's
    own disk record (`runtime/job_store.py`) survives the restart and answers
    again once BuzzEdit is back, already marked failed ("BuzzEdit restarted")
    if it was lost for good. `_run_reel`'s own retry loop (`VIBE_REEL_ATTEMPTS`)
    re-submits the same body once should this still end in a raise."""
    from app.services import master_control

    last_seen = None
    last_change = time.time()
    unreachable_since: Optional[float] = None
    while True:
        try:
            job = client.vibe_reel_job(job_id)
        except Exception as exc:  # noqa: BLE001 - a restart's own downtime, not a failure yet
            now = time.time()
            unreachable_since = unreachable_since or now
            if now - unreachable_since > VIBE_FOLLOW_MISS_S:
                raise RuntimeError(
                    f"BuzzEdit stopped answering about the vibe reel job {job_id}: {exc}") from exc
            logger.warning("auto_story: vibe reel job poll for %s failed (%s); trying again.", job_id, exc)
            _sleep(VIBE_POLL_S)
            continue
        unreachable_since = None
        state = job.get("state")
        if state == "failed":
            raise RuntimeError(f"BuzzEdit's vibe reel failed: {job.get('error') or job.get('message') or 'no detail'}")
        if state == "done":
            return job.get("result") or {}
        # Master pause (Part 1): BuzzEdit holds the job between shots rather
        # than failing it, so no progress for as long as the pause lasts is
        # expected, not a stall -- the clock resets while it is on.
        if master_control.is_paused() or (client.master_state() or {}).get("paused"):
            last_change = time.time()
            _sleep(VIBE_POLL_S)
            continue
        seen = (job.get("progress"), job.get("message"))
        if seen != last_seen:
            last_seen = seen
            last_change = time.time()
            _step(rec, "rendering", f"Rendering: {job['message']}" if job.get("message") else "Rendering", say)
        elif time.time() - last_change > VIBE_STALL_S:
            raise RuntimeError(f"BuzzEdit's vibe reel has shown no progress for {int(VIBE_STALL_S // 60)} minutes.")
        _sleep(VIBE_POLL_S)


def make_mood_reel(channel: str, length: Any = None, *, style: Optional[str] = None, theme: Optional[str] = None,
                   progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Real lines -> project -> shot plan -> BuzzEdit's vibe-reel renderer
    (`POST /api/reels/vibe`), followed to the end -> the Instagram package.
    No narration, no take, no production queue. Returns the final record.
    A reel is a video too: it waits its turn in `video_slot` and holds the
    slot until it is packaged."""
    from app.services import video_slot
    say = progress or _noop
    key = f"mood-reel-{channel}-{uuid.uuid4().hex[:6]}"
    with video_slot.turn(key, title=f"{channel} mood reel", brand=channel, what="mood reel", say=say):
        return _make_mood_reel_now(channel, length, style=style, theme=theme,
                                   progress=lambda msg: (video_slot.set_doing(key, msg), say(msg)))


def _make_mood_reel_now(channel: str, length: Any = None, *, style: Optional[str] = None,
                        theme: Optional[str] = None,
                        progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    from app.services import mood_reel
    from integrations import art_style
    from integrations.buzzedit_client import BuzzEditClient
    say = progress or _noop
    if channel not in mood_reel.CHANNELS:
        raise ValueError(f"A mood reel is a {', '.join(mood_reel.CHANNELS)} format, not {channel}.")
    style = art_style.normalise(style) if style else "real"
    if style not in mood_reel.STYLES:
        raise ValueError(f"A mood reel is 'real', 'painterly' or 'illustrated', not {style!r}.")
    seconds = mood_reel.parse_seconds(length)
    theme = mood_reel.pick_theme(theme)
    mood = mood_reel.THEMES[theme]["mood"]
    found = mood_reel.find_lines(channel, mood, say)
    lines = found["lines"]
    poet = found.get("poet", "")
    # Hinglish on screen (2026-10-23 night rules, VR7): the fetched lines are
    # Devanagari; the cards show the transliteration instead (`roman` script,
    # one LLM call), and `caption.txt` carries both. A line already in Roman
    # (or a failed transliteration) comes back unchanged from this call.
    hinglish_lines, _translit_ok = mood_reel.transliterate_lines(lines)

    project = _new_mood_project(channel, theme)
    project_id = project.id
    pdir = project.get_project_dir()
    rec: Dict[str, Any] = {
        "project_id": project_id, "channel": channel, "format": mood_reel.KEY, "length": length,
        "seconds": seconds, "mood": mood, "theme": theme, "style": style,
        "orientation": "vertical", "state": "starting", "started_at": _now(), "steps": [], "error": None,
        "posted": {}, "final": None, "lines": lines, "poet": poet,
        "source": {k: found.get(k) for k in ("title", "source_url", "rights", "poet_died", "format", "score")},
    }
    try:
        _step(rec, "script", f"{len(lines)} lines by {poet or 'unknown'} ({theme})", say)
        # BuzzEdit renders into its own staging folder (shots/, assets/,
        # vibe_reel.json); only the finished deliverables are copied into the
        # Instagram package, the way `instagram_package()` copies a normal
        # production's final file in.
        stage_dir = os.path.abspath(os.path.join(pdir, "production", "vibe_reel"))
        out_dir = os.path.join(pdir, "publish", "instagram")
        os.makedirs(stage_dir, exist_ok=True)
        os.makedirs(out_dir, exist_ok=True)
        pkg = mood_reel.package(lines, poet, hinglish_lines=hinglish_lines)
        _write_json(os.path.join(pdir, "publish", "short_package.json"), pkg)
        project = _load(project_id)
        project.name = (lines[0][:80] if lines else project.name)
        project.current_step = "Mood reel"
        project.assets["short_package"] = "publish/short_package.json"
        project.metadata.update({"orientation": "vertical", "short_format": mood_reel.KEY, "short_channel": channel,
                                 "auto_story": rec})
        project.save()

        _step(rec, "plan", f"Planning {round(seconds)} s of scenes ({theme})", say)
        plan = mood_reel.plan_shots(lines, theme, mood, seconds, style, channel, poet,
                                    display_lines=hinglish_lines)
        _write_json(os.path.join(pdir, "production", "mood_reel_plan.json"), plan)
        # No AI music bed (2026-10-24, VR8): the creator adds his own song in
        # the Instagram app, over the ambience `vibe_body` still asks for --
        # `mood_reel.music_for()` is kept but no longer called here.
        rec["world"] = plan.get("world")
        rec["shots"] = len(plan["shots"])
        rec["music"] = None
        project = _load(project_id)
        project.assets["mood_reel_plan"] = "production/mood_reel_plan.json"
        project.metadata["auto_story"] = rec
        project.save()

        body = mood_reel.vibe_body(stage_dir, "reel", style, theme, plan)
        rec["request"] = {k: body[k] for k in ("art_style", "world", "shots", "lines", "credit", "music",
                                               "ambience")}
        _step(rec, "rendering", "Rendering the vibe reel in BuzzEdit", say)
        _write_record(project_id, rec)
        client = BuzzEditClient()
        job = client.vibe_reel(body)
        job_id = job.get("job_id")
        if not job_id:
            raise RuntimeError(f"BuzzEdit returned no vibe reel job id: {str(job)[:200]}")
        rec["vibe_job_id"] = job_id
        result = _follow_vibe_job(client, job_id, rec, say)
        video = result.get("video")
        if not video or not os.path.isfile(video):
            raise RuntimeError(f"The vibe reel finished with no video file on disk: {result}")

        final = os.path.join(out_dir, "reel.mp4")
        shutil.copy2(video, final)
        nomusic = result.get("video_nomusic")
        if nomusic and os.path.isfile(nomusic):
            shutil.copy2(nomusic, os.path.join(out_dir, "reel_nomusic.mp4"))
        cover = result.get("cover")
        if cover and os.path.isfile(cover):
            shutil.copy2(cover, os.path.join(out_dir, "cover.jpg"))
            rec["cover"] = os.path.join(out_dir, "cover.jpg")

        caption = pkg["caption"].strip() + ("\n\n" + " ".join(pkg["hashtags"]) if pkg.get("hashtags") else "")
        with open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8") as f:
            f.write(caption.strip() + "\n")
        _write_json(os.path.join(out_dir, "short_package.json"), pkg)
        rec["final"] = final
        rec["duration_s"] = result.get("duration_s")
        rec["posted"] = {"instagram": "packaged", "package_dir": out_dir}
        rec["package_dir"] = out_dir
        # Ask before publishing (STUDIO_DIRECTOR_PLAN.md, Fable review #10):
        # a freshly packaged reel waits for the creator's review by default.
        rec["review"] = rec.get("review") or {"state": "needs_review", "at": _now(), "reason": None}
        _step(rec, "packaged", "Packaged for Instagram", say)
        rec["finished_at"] = _now()
        _write_record(project_id, rec)
    except Exception as exc:
        rec["error"] = str(exc)[:500]
        _step(rec, "failed", f"Failed: {str(exc)[:200]}", say)
        rec["finished_at"] = _now()
        try:
            _write_record(project_id, rec)
        except Exception:  # noqa: BLE001
            logger.exception("auto_story: could not save the mood reel failure record for %s", project_id)
        raise

    return dict(rec)


# --- jobs ----------------------------------------------------------------------------------

_jobs: Dict[str, Dict[str, Any]] = {}


def start_job(kind: str, fn, *args, **kwargs) -> Dict[str, Any]:
    """Run `fn(*args, progress=..., **kwargs)` in the background; for run/make the
    job stays running until the production is published (or fails)."""
    from integrations import idle_offload
    job_id = uuid.uuid4().hex[:12]
    job = {"job_id": job_id, "kind": kind, "state": "running", "message": "Starting", "result": None,
           "error": None, "project_id": None, "started_at": _now()}
    _jobs[job_id] = job

    def progress(msg: str) -> None:
        job["message"] = msg

    def body() -> None:
        try:
            with idle_offload.busy():
                result = fn(*args, progress=progress, **kwargs)
            pid = (result or {}).get("project_id") if isinstance(result, dict) else None
            job["project_id"] = pid
            if pid and pid in _watchers:
                result = wait(pid) or result
            job["result"] = result
            failed = isinstance(result, dict) and result.get("state") == "failed"
            job.update(state="failed" if failed else "done",
                       error=(result.get("error") if failed else None),
                       message=(result.get("error") or "Failed") if failed else "Done")
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            logger.exception("auto_story %s job failed", kind)
            job.update(state="failed", error=str(exc)[:300], message="Failed")
        finally:
            job["finished_at"] = _now()
            idle_offload.offload_now(f"auto story {kind} finished")

    threading.Thread(target=body, name=f"auto-story-{kind}-{job_id}", daemon=True).start()
    return job


def job(job_id: str) -> Optional[Dict[str, Any]]:
    return _jobs.get(job_id)


# --- nightly (§3.7) ------------------------------------------------------------------------

def _picks(conf: Dict[str, Any]) -> List[Dict[str, str]]:
    """Tonight's (channel, format) list: the StoryProducer's pick when it gives a
    valid one, else each channel's formats in turn."""
    wanted: Dict[str, int] = {}
    allowed: Dict[str, List[str]] = {}
    for ch, n in (conf.get("per_channel") or {}).items():
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        valid = [f for f in (conf.get("formats") or {}).get(ch) or [] if f in channel_formats(ch)]
        if n > 0 and valid:
            wanted[ch] = n
            allowed[ch] = valid
    if not wanted:
        return []
    picks: List[Dict[str, str]] = []
    try:
        from app.services import shorts_desk
        answer = shorts_desk._agent_json("StoryProducer", {
            "task": "pick_auto_stories", "count_per_channel": wanted, "formats": allowed,
            "recent": [{k: r.get(k) for k in ("brand", "format", "name", "state")} for r in list_records()[:20]],
            "answer_shape": {"picks": [{"channel": "<channel>", "format": "<one of formats[channel]>"}], "note": "..."},
        }) or {}
        counts: Dict[str, int] = {}
        for p in answer.get("picks") or []:
            if not isinstance(p, dict):
                continue
            ch, fmt = p.get("channel"), p.get("format")
            if ch in allowed and fmt in allowed[ch] and counts.get(ch, 0) < wanted[ch]:
                picks.append({"channel": ch, "format": fmt, "by": "StoryProducer"})
                counts[ch] = counts.get(ch, 0) + 1
    except Exception as exc:  # noqa: BLE001 - round-robin below
        logger.info("StoryProducer pick unavailable: %s", exc)
    rotation = dict(conf.get("rotation") or {})
    for ch, n in wanted.items():
        have = sum(1 for p in picks if p["channel"] == ch)
        for _ in range(n - have):
            i = int(rotation.get(ch, 0) or 0)
            picks.append({"channel": ch, "format": allowed[ch][i % len(allowed[ch])], "by": "rotation"})
            rotation[ch] = i + 1
    set_settings({"rotation": rotation})
    return picks


def run_all(progress: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """The nightly task: make() per pick, one at a time (one GPU), waiting for each production."""
    say = progress or _noop
    conf = settings()
    set_settings({"last_run": datetime.now().date().isoformat()})  # claim today before making anything
    made: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    started = time.time()
    from app.services import mood_reel
    for pick in _picks(conf):
        ch, fmt = pick["channel"], pick["format"]
        if fmt != mood_reel.KEY and conf.get("voice_clone_paused"):
            say(f"{ch}: {fmt} skipped -- the cloned voice is paused")
            continue
        try:
            rec = make(ch, fmt, voice=default_voice_for(ch), publish=bool(conf.get("publish")),
                       progress=lambda m, ch=ch: say(f"{ch}: {m}"))
            pid = rec.get("project_id")
            remaining = max(60.0, NIGHTLY_WAIT_S - (time.time() - started))
            rec = wait(pid, remaining) or rec
            entry = {"channel": ch, "format": fmt, "project_id": pid, "name": rec.get("name"),
                     "state": rec.get("state"), "final": rec.get("final"), "posted": rec.get("posted") or {}}
            (failed if rec.get("state") == "failed" else made).append(
                {**entry, **({"error": rec.get("error")} if rec.get("state") == "failed" else {})})
        except Exception as exc:  # noqa: BLE001
            logger.exception("auto_story nightly %s/%s", ch, fmt)
            failed.append({"channel": ch, "format": fmt, "error": str(exc)[:300]})
    summary = (f"Made {len(made)}" + (f", {len(failed)} failed" if failed else "")) if (made or failed) else         "Nothing to make (no channel has a count and a format)."
    last = {"ran_at": _now(), "summary": summary, "made": made, "failed": failed}
    set_settings({"last_run": datetime.now().date().isoformat(), "last": last})
    return {"task": "auto_story", **last}


# --- Instagram scheduler (REELS_DESK_PLAN.md R7) ----------------------------------------
#
# The same "check once a minute" shape as shorts_desk.start_scheduler. `enabled`,
# `post_times` and `last_fired` belong to the named *account* (several channel/format
# routes -- e.g. Life3Baje/mood_reel -> khayal3bajefeels -- can share one), so the
# tick walks accounts, not channels: nothing posts until an account is both saved
# and turned on.

INSTAGRAM_SCHEDULER_POLL_S = 60.0
_instagram_scheduler: Optional[threading.Thread] = None


def _instagram_due(conf: Dict[str, Any], now: datetime) -> Optional[str]:
    """The post time due right now: `post_time <= now` and not already fired
    today -- not an exact HH:MM match (2026-10-24, Fable review #11), so a
    slot already due is never skipped just because a tick ran late or was
    missed. The earliest such overdue slot, so several missed slots catch up
    one tick at a time, in order."""
    if not conf.get("enabled"):
        return None
    today = now.date().isoformat()
    fired = conf.get("last_fired") or {}
    hm_now = now.strftime("%H:%M")
    due = sorted(str(t) for t in (conf.get("post_times") or []) if str(t) <= hm_now and fired.get(str(t)) != today)
    return due[0] if due else None


def _oldest_unposted_packaged_for_account(account: str) -> Optional[Dict[str, Any]]:
    """The oldest *approved* record (STUDIO_DIRECTOR_PLAN.md: ask before
    publishing, Fable review #10) whose channel (and format) routes to
    `account`, with an Instagram package and no permalink yet, or None."""
    from integrations import instagram_publish as ig
    candidates = [r for r in list_records() if r.get("package_dir") and not _instagram_posted(r)
                  and (r.get("review") or {}).get("state") == "approved"
                  and ig.account_for(r.get("brand") or "", r.get("format")) == account]
    candidates.sort(key=lambda r: str(r.get("started_at") or ""))
    return candidates[0] if candidates else None


def _instagram_tick() -> None:
    from app.services import master_control
    from integrations import instagram_publish as ig
    if master_control.is_paused():
        return  # master pause: nothing new posts; the slot is tried again next tick
    now = datetime.now()
    for account, conf in ig.all_accounts().items():
        slot = _instagram_due(conf, now)
        if not slot:
            continue
        # Marked right away: at most one attempt per slot, win or lose.
        ig.set_account_settings(account, {"last_fired": {slot: now.date().isoformat()}})
        candidate = _oldest_unposted_packaged_for_account(account)
        if not candidate:
            logger.info("instagram scheduler: nothing unposted for %s at %s", account, slot)
            continue
        try:
            post_instagram(candidate["project_id"])
            logger.info("instagram scheduler: posted %s for %s at %s", candidate["project_id"], account, slot)
        except Exception as exc:  # noqa: BLE001 - the next slot (or "Post to Instagram") can retry
            logger.warning("instagram scheduler: posting %s for %s failed: %s", candidate["project_id"], account, exc)


def start_instagram_scheduler() -> None:
    """Checks once a minute; posts at most one reel per channel per post time."""
    global _instagram_scheduler
    if _instagram_scheduler and _instagram_scheduler.is_alive():
        return

    def loop() -> None:
        while True:
            try:
                _instagram_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("instagram scheduler tick failed: %s", exc)
            time.sleep(INSTAGRAM_SCHEDULER_POLL_S)

    _instagram_scheduler = threading.Thread(target=loop, name="instagram-scheduler", daemon=True)
    _instagram_scheduler.start()
