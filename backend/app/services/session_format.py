"""Recording sessions: the Shorts first, then the long video.

For Raat3Baje, Life3Baje and Beyond3Baje every long video is recorded in one
sitting that OPENS with 3-4 Shorts (the creator's call, 2026-10-16): he reads
the Shorts off the teleprompter one after another, then his greeting, then
the long video. So a project carries two scripts:

- the long script (`script/draft.md` and its edit/narration passes), written
  as before, and
- `script/shorts.json` / `script/shorts.md`: the session's Shorts, written by
  the `ShortsWriter` in the "Shorts Scripts" step (output `shorts_set`) from
  the research and the long script -- each a complete, different Short.

`script/recording_script.md` puts the two together in recording order, for
the teleprompter. In production the recording is split where the long
video's greeting is said (app/services/session_split.py): the part before it
becomes one Short project per Short, the part after it is the long video.

The same channel settings also hold how the creator's face is used in the
long video (`face_layout`): "mixed" (the old way -- his face comes back
between the pictures all through) or "face_intro" (his face for the first
`face_intro_seconds`, then pictures and clips only). Both live here as
channel defaults (config `channel_formats`), and a project may override each.
"""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("buzzcaf_ai.session_format")

#: The channels whose long videos are recorded as a session.
SESSION_CHANNELS = ("Raat3Baje", "Life3Baje", "Beyond3Baje")
SESSION_FORMATS = ("shorts_first", "long_only")
SHORTS_COUNTS = (3, 4)
DEFAULT_SHORTS = 3

FACE_LAYOUTS = ("mixed", "face_intro")
DEFAULT_FACE_INTRO_SECONDS = 45   # creator rule 2026-11-23: face only for the first 45 s, then pictures + clips (was 90)
FACE_INTRO_MIN, FACE_INTRO_MAX = 30, 180

SHORTS_JSON = "script/shorts.json"
SHORTS_MD = "script/shorts.md"
RECORDING_SCRIPT = "script/recording_script.md"

#: Long-script assets, best first: what the creator reads for the long part.
LONG_SCRIPT_ASSETS = ("script_final", "narration_optimized", "script")

#: Spoken words per second of a Short (the channels' narration pace).
WORDS_PER_SECOND = 140 / 60.0


def _channel(brand: str) -> str:
    from app.services.writing_style import canonical_channel
    return canonical_channel(brand)


def _defaults_for(channel: str) -> Dict[str, Any]:
    return {
        "shorts_first": channel in SESSION_CHANNELS,
        "shorts_count": DEFAULT_SHORTS,
        # Creator rule 2026-11-23: every channel opens on his face for 45 s, then only
        # pictures and clips ("for all unless I tell"). A channel or project overrides it.
        "face_layout": "face_intro",
        "face_intro_seconds": DEFAULT_FACE_INTRO_SECONDS,
    }


def _clean(entry: Dict[str, Any], base: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    if "shorts_first" in entry and entry["shorts_first"] is not None:
        out["shorts_first"] = bool(entry["shorts_first"])
    if entry.get("shorts_count") is not None:
        try:
            count = int(entry["shorts_count"])
        except (TypeError, ValueError):
            count = DEFAULT_SHORTS
        out["shorts_count"] = min(max(SHORTS_COUNTS), max(min(SHORTS_COUNTS), count))
    if entry.get("face_layout") in FACE_LAYOUTS:
        out["face_layout"] = entry["face_layout"]
    if entry.get("face_intro_seconds") is not None:
        out["face_intro_seconds"] = clamp_intro(entry["face_intro_seconds"])
    return out


def clamp_intro(value: Any) -> int:
    try:
        seconds = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_FACE_INTRO_SECONDS
    # 0 is "no face at all" (2026-10-23, a narrated channel's own default --
    # TheTallStoryteller): the same sentinel buzzedit_settings.face_intro_seconds()
    # already honours at render time. Anything else stays 30-180 s.
    if seconds <= 0:
        return 0
    return max(FACE_INTRO_MIN, min(FACE_INTRO_MAX, seconds))


def channel_defaults(brand: str) -> Dict[str, Any]:
    """The channel's session and face defaults (config `channel_formats`)."""
    channel = _channel(brand)
    try:
        from integrations.llm import load_config
        saved = (load_config().get("channel_formats") or {}).get(channel) or {}
    except Exception:  # noqa: BLE001 - unreadable settings: the built-in defaults
        saved = {}
    return _clean(saved if isinstance(saved, dict) else {}, _defaults_for(channel))


def all_channel_defaults() -> Dict[str, Dict[str, Any]]:
    return {ch: channel_defaults(ch) for ch in SESSION_CHANNELS}


def set_channel_defaults(brand: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    """Save part of a channel's defaults; unknown keys and bad values are
    ignored (a bad face layout keeps the saved one)."""
    from integrations.llm import load_config, save_config
    channel = _channel(brand)
    cfg = load_config()
    table = dict(cfg.get("channel_formats") or {})
    merged = _clean({**(table.get(channel) or {}), **(patch or {})}, _defaults_for(channel))
    table[channel] = merged
    cfg["channel_formats"] = table
    save_config(cfg)
    return merged


# --- one project ----------------------------------------------------------------

def _meta(project: Any) -> Dict[str, Any]:
    return getattr(project, "metadata", None) or {}


def is_session_short(project: Any) -> bool:
    """A Short cut out of a session recording (it has no session of its own)."""
    return bool(_meta(project).get("session_parent"))


def is_shorts_first(project: Any) -> bool:
    """Whether this project's recording opens with its Shorts: the project's
    own choice (`session_format`), else the channel's default. Shorts
    themselves never are."""
    meta = _meta(project)
    if is_session_short(project) or getattr(project, "workflow_name", "") == "shorts_ready":
        return False
    own = meta.get("session_format")
    if own in SESSION_FORMATS:
        return own == "shorts_first"
    if _channel(getattr(project, "brand", "")) not in SESSION_CHANNELS:
        return False
    return bool(channel_defaults(project.brand)["shorts_first"])


def shorts_count(project: Any) -> int:
    own = _meta(project).get("session_shorts_count")
    if own in SHORTS_COUNTS:
        return int(own)
    return int(channel_defaults(getattr(project, "brand", ""))["shorts_count"])


def face_layout(brand: str, video_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{"face_layout", "face_intro_seconds", "source"} for a channel, with a
    project's `video_settings` over it."""
    base = channel_defaults(brand)
    out = {"face_layout": base["face_layout"], "face_intro_seconds": base["face_intro_seconds"], "source": "channel"}
    vs = video_settings or {}
    if vs.get("face_layout") in FACE_LAYOUTS:
        out["face_layout"] = vs["face_layout"]
        out["source"] = "project"
    if vs.get("face_intro_seconds") is not None:
        out["face_intro_seconds"] = clamp_intro(vs["face_intro_seconds"])
    return out


def project_view(project: Any) -> Dict[str, Any]:
    """Everything the Projects page shows about the session."""
    meta = _meta(project)
    own = meta.get("session_format")
    return {
        "session_format": "shorts_first" if is_shorts_first(project) else "long_only",
        "session_format_source": "project" if own in SESSION_FORMATS else "channel",
        "shorts_count": shorts_count(project),
        "channel_defaults": channel_defaults(getattr(project, "brand", "")),
        "shorts": load_shorts(project),
        "split_at_s": meta.get("session_split_s"),
        "split": meta.get("session_split"),
        "parent": meta.get("session_parent"),
        "face": face_layout(getattr(project, "brand", ""), meta.get("video_settings")),
        "eligible": _channel(getattr(project, "brand", "")) in SESSION_CHANNELS and not is_session_short(project)
                    and getattr(project, "workflow_name", "") != "shorts_ready",
    }


# --- the Shorts step ----------------------------------------------------------------

_ANGLES = {
    "Raat3Baje": (
        "Each Short is ONE thing from this episode's world, complete in itself: an alleged real encounter or "
        "incident from the research, one rule of the entity or the place and what happens to whoever breaks it, "
        "one chilling real detail (a ritual, a register, a local belief), or one scene from the first half of the "
        "story. Indian folklore only. Never the long story's twist or ending -- the long video keeps that."),
    "Beyond3Baje": (
        "Each Short is ONE striking detail of this episode's case, entity or place, complete in itself: the moment "
        "of the encounter (DATE + PLACE + WHO, when documented), one witness's claim, one document or contradiction, "
        "or the strangest unexplained detail. Outside India only. Keep CLAIMED vs DOCUMENTED apart in the words "
        "themselves. Never the long video's final answer."),
    "Life3Baje": (
        "Each Short is ONE honest moment from this episode, complete in itself: a real number and what it means, "
        "a failure and what it taught, a decision and why, or a behind-the-scenes truth -- first person, warm, "
        "specific to what he is actually building. Never generic motivation or advice."),
}

SHORTS_TASK = """
### This step: the session's {n} Shorts (recorded FIRST, before the long video)
The creator records this whole session in one sitting: these {n} Shorts first, one after another, then his
greeting and the long video. Write the {n} Shorts now, from the research and the long script above.

What each Short is:
{angle}

Rules for every Short:
1. Self-contained: a viewer who never sees the long video still gets a hook, a build and a payoff.
2. Each Short has its OWN angle -- {n} different moments, details or incidents; never the same one twice,
   and never a summary or trailer of the whole long video.
3. Line one is the hook: the most specific, unsettling or surprising detail, said straight away. NO greeting
   (no "Hello doston", no name, no channel name), no "aaj main aapko", no subscribe request at the start.
4. Length: {lo}-{hi} spoken words (about 45-75 seconds). Short sentences that are easy to say in one breath.
5. The last line lands it -- an unresolved, chilling or thought-provoking line -- and then at most ONE short
   line that points to the full video (in his own words, e.g. "Poori kahani channel par hai.").
6. Facts only from the research: folklore as folklore ("kehte hain..."), alleged as alleged. Never invent a
   date, a place, a witness or a document.
7. Written in the creator's own style when it is given above (manner only; his greeting is NOT used in a Short).
   If he writes continuous narration, write plain spoken paragraphs: no [VISUAL]/[SOUND] cues, no speaker
   labels, no (pause) marks. Otherwise a few (pause)/(beat) cues where delivery truly changes.
8. Hinglish in Roman script, like the long video.

Also for each Short: a scroll-stopping `title` (<= 60 characters), `on_screen_text` for the first 2 seconds
(<= 6 words), a 2-3 line `caption` that ends with a question, and 8-12 `hashtags` (include #shorts, mix
Hindi/English and broad/niche).

### Output (strict JSON only, nothing else)
{{"shorts": [{{"title": "...", "angle": "which moment / detail / incident this Short is built on",
              "hook_line": "the first spoken line", "script": "the full spoken script",
              "on_screen_text": "...", "caption": "...", "hashtags": ["#shorts", "..."],
              "estimated_seconds": 60}}]}}
Exactly {n} items in "shorts".
"""


def shorts_task(project: Any) -> str:
    n = shorts_count(project)
    channel = _channel(project.brand)
    lo, hi = 110, 175
    return SHORTS_TASK.format(n=n, angle=_ANGLES.get(channel, _ANGLES["Raat3Baje"]), lo=lo, hi=hi)


def _parse_json(raw: Any) -> Optional[Any]:
    from integrations.llm import clean_json_response
    text = clean_json_response(str(raw or ""))
    try:
        return json.loads(text, strict=False)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1], strict=False)
            except ValueError:
                return None
    return None


def _salvage_items(raw: Any) -> List[Dict[str, Any]]:
    """Every complete `{...}` object inside the reply's "shorts" list, read one by one.
    A local model's long reply (3-4 full Short scripts) is often cut off before the
    closing brackets, or breaks on one bad character in the last item; the whole reply
    used to be discarded and the step failed (2026-10-23: two adaptations stuck at
    Shorts Scripts with complete Shorts in the reply)."""
    from integrations.llm import clean_json_response
    text = clean_json_response(str(raw or ""))
    key = text.find('"shorts"')
    pos = text.find("[", key if key >= 0 else 0)
    if pos < 0:
        return []
    decoder = json.JSONDecoder(strict=False)
    items: List[Dict[str, Any]] = []
    i = pos + 1
    while True:
        start = text.find("{", i)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            break                      # the cut-off (or broken) item: keep what came before
        if isinstance(obj, dict):
            items.append(obj)
        i = end
    return items


def parse_shorts(raw: Any) -> List[Dict[str, Any]]:
    """The Shorts in a writer's reply, cleaned; [] when there are none."""
    data = _parse_json(raw)
    items = data.get("shorts") if isinstance(data, dict) else data if isinstance(data, list) else None
    if not items:
        items = _salvage_items(raw)
    if not items:
        # Unescaped quotes inside a Hinglish script ("log ise "Judge ka ghar" kehte") break
        # strict JSON from the first item on; the Shorts desk repairs the same way.
        try:
            import json_repair
            from integrations.llm import clean_json_response
            fixed = json_repair.loads(clean_json_response(str(raw or "")))
            items = fixed.get("shorts") if isinstance(fixed, dict) else fixed if isinstance(fixed, list) else None
        except Exception:  # noqa: BLE001 - no repair possible: the step reports it
            items = None
    out: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        script = str(item.get("script") or "").strip()
        if not script:
            continue
        hashtags = item.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = hashtags.split()
        tags = [h if str(h).startswith("#") else f"#{h}" for h in (str(x).strip() for x in hashtags) if h]
        if "#shorts" not in {t.lower() for t in tags}:
            tags.insert(0, "#shorts")
        out.append({
            "title": str(item.get("title") or "").strip()[:100],
            "angle": str(item.get("angle") or "").strip(),
            "hook_line": str(item.get("hook_line") or "").strip(),
            "script": script,
            "on_screen_text": str(item.get("on_screen_text") or "").strip(),
            "caption": str(item.get("caption") or "").strip(),
            "hashtags": tags[:15],
            "estimated_seconds": _seconds(item.get("estimated_seconds"), script),
        })
    return out


def _seconds(value: Any, script: str) -> int:
    try:
        seconds = int(float(value))
        if 10 <= seconds <= 180:
            return seconds
    except (TypeError, ValueError):
        pass
    from app.services.writing_style import narration_words
    return int(round(narration_words(script) / WORDS_PER_SECOND))


def strip_greeting(script: str) -> str:
    """A Short never opens with the long video's greeting: a greeting the
    writer put in anyway is removed (with the opening lines around it)."""
    try:
        from app.services.writing_style import strip_repeated_intro
        cleaned, _ = strip_repeated_intro(script, keep_first=False)
        return cleaned.strip() or script.strip()
    except Exception:  # noqa: BLE001
        return script.strip()


def shorts_markdown(project: Any, shorts: List[Dict[str, Any]]) -> str:
    parts = [f"# Shorts for this session -- {project.name}", ""]
    for k, s in enumerate(shorts, 1):
        parts += [f"## SHORT {k} of {len(shorts)} -- {s['title'] or 'Untitled'}", ""]
        if s.get("angle"):
            parts += [f"> Angle: {s['angle']}", ""]
        parts += [s["script"], ""]
        meta = []
        if s.get("on_screen_text"):
            meta.append(f"On screen: {s['on_screen_text']}")
        if s.get("caption"):
            meta.append(f"Caption: {s['caption']}")
        if s.get("hashtags"):
            meta.append("Hashtags: " + " ".join(s["hashtags"]))
        if meta:
            parts += ["> " + "\n> ".join(meta), ""]
    return "\n".join(parts).strip() + "\n"


def save_shorts(project: Any, shorts: List[Dict[str, Any]]) -> str:
    """Write shorts.json and shorts.md; returns the Markdown file's relative path."""
    pdir = project.get_project_dir()
    os.makedirs(os.path.join(pdir, "script"), exist_ok=True)
    with open(os.path.join(pdir, SHORTS_JSON), "w", encoding="utf-8") as f:
        json.dump({"shorts": shorts}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(pdir, SHORTS_MD), "w", encoding="utf-8") as f:
        f.write(shorts_markdown(project, shorts))
    project.assets["shorts_json"] = SHORTS_JSON
    return SHORTS_MD


def load_shorts(project: Any) -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(project.get_project_dir(), SHORTS_JSON), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, AttributeError):
        return []
    items = data.get("shorts") if isinstance(data, dict) else None
    return [s for s in items or [] if isinstance(s, dict) and str(s.get("script") or "").strip()]


def long_script_text(project: Any) -> str:
    """The newest long script (final > narration > draft), or ''."""
    for key in LONG_SCRIPT_ASSETS:
        rel = project.assets.get(key)
        if not rel:
            continue
        path = os.path.join(project.get_project_dir(), rel)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
    return ""


_TOP_HEADING_RE = re.compile(r"\A\s*#\s+[^\n]*\n+")


def recording_script(project: Any) -> Optional[str]:
    """The session in recording order: the Shorts, then the long video."""
    shorts = load_shorts(project)
    long_text = long_script_text(project)
    if not shorts or not long_text:
        return None
    n = len(shorts)
    parts = [f"# Recording session -- {project.name}", "",
             f"## Record first: the {n} Shorts, one after another (3 seconds of silence after each)", ""]
    for k, s in enumerate(shorts, 1):
        parts += [f"### SHORT {k} of {n} -- {s.get('title') or 'Untitled'}", "", s["script"].strip(), "", "(pause 3s)", ""]
    parts += ["---", "", f"## Then the long video -- {project.name}", "",
              _TOP_HEADING_RE.sub("", long_text, count=1).strip(), ""]
    return "\n".join(parts).strip() + "\n"


def refresh_recording_script(project: Any) -> Optional[str]:
    """Rewrite script/recording_script.md from the Shorts and the newest long
    script; returns its relative path, or None when either is missing. The
    caller saves the project (its assets map gains `recording_script`)."""
    if not is_shorts_first(project):
        return None
    text = recording_script(project)
    if not text:
        return None
    with open(os.path.join(project.get_project_dir(), RECORDING_SCRIPT), "w", encoding="utf-8") as f:
        f.write(text)
    project.assets["recording_script"] = RECORDING_SCRIPT
    return RECORDING_SCRIPT


# --- the long script of a session -------------------------------------------------------

def long_script_direction(project: Any) -> str:
    """For the long script of a session: the greeting opens it, since the
    recording is split there."""
    if not is_shorts_first(project):
        return ""
    return ("\n\n### Recorded after its Shorts\n"
            "The creator records this video's Shorts first and then this long video, in one recording, which is "
            "split where his greeting is said. So his greeting is the very FIRST line of this script -- a cold "
            "open, if any, comes right after it -- and the script never mentions the Shorts.\n")


def greeting_first(script: str, brand: str) -> "tuple[str, bool]":
    """The long script of a session with the greeting as its first spoken
    line (a cold open the writer put before it moves after it): the
    recording is split at the greeting, so nothing of the long video may be
    said before it. Returns (script, moved)."""
    from app.services.writing_style import greeting, narration_words
    line = greeting(brand)
    at = script.find(line)
    if at <= 0 or narration_words(_TOP_HEADING_RE.sub("", script[:at], count=1)) == 0:
        return script, False
    rest = (script[:at] + script[at + len(line):]).strip("\n")
    lines = rest.split("\n")
    first = next((k for k, l in enumerate(lines) if l.strip() and not l.lstrip().startswith("#")), len(lines))
    return "\n".join(lines[:first] + [line, ""] + lines[first:]).rstrip() + "\n", True


# --- face-first long videos -----------------------------------------------------------

def face_intro_direction(project: Any) -> str:
    """For a long video that opens on the creator's face: the writer opens
    the script as him talking straight to the viewer for that long."""
    face = face_layout(getattr(project, "brand", ""), _meta(project).get("video_settings"))
    if face["face_layout"] != "face_intro":
        return ""
    seconds = int(face["face_intro_seconds"])
    words = int(round(seconds * WORDS_PER_SECOND))
    return (
        f"\n\n### The opening is on the creator's face (the first ~{seconds} seconds)\n"
        f"This video shows only the creator, talking to the viewer, for its first ~{seconds} seconds (about "
        f"{words} spoken words); after that it is pictures and clips only, to the end. So the opening is written "
        f"to be SAID to camera: his greeting, then the hook and why this story or subject matters to the viewer, "
        f"spoken directly to them. The story or the subject itself starts right after that opening -- where the "
        f"pictures take over -- and is written to be seen: concrete places, people, objects and moments.\n")
