"""The creator's own B-roll clips (docs/OWN_FOOTAGE_PLAN.md, 2026-10-29).

A project in own-footage mode (`metadata["footage_mode"] == "own"`) is edited
from clips he filmed himself: no generated or stock pictures. This module
keeps the footage folder, reads every clip once (duration, size, sound, a
shot tag from the file name, and what it shows -- three frames sent to the
local vision model in one call) and caches that per file, and plans against
the script's shots (`shot_spans`) and the own-footage window rules
(`planner_section`, `finalize_beats`).
"""
from __future__ import annotations

import base64
import difflib
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

from core.models.project import Project

logger = logging.getLogger(__name__)

VIDEO_EXTS = (".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_FRAME_POINTS = (0.10, 0.50, 0.90)
VISION_TIMEOUT_S = 240

#: Catalog kinds that draw a generated picture: never in an own-footage plan.
GENERATED_KINDS = {"broll_image", "broll_video", "canvas_card", "callout", "stick_scene", "paper_collage"}
OWN_CLIP = "own_clip"

_SHOT_RE = re.compile(r"(?:^|[^a-z0-9])(?:shot|scene|sh|s)[\s_\-]*0*(\d{1,3})(?![0-9])", re.IGNORECASE)


# ───────────────────────── settings and paths ─────────────────────────

def footage_dir(project: Project) -> str:
    custom = str(project.metadata.get("footage_dir") or "").strip()
    path = custom or os.path.join(project.get_project_dir(), "production", "footage")
    os.makedirs(path, exist_ok=True)
    return path


def catalog_path(project: Project) -> str:
    return os.path.join(project.get_project_dir(), "production", "footage_catalog.json")


def is_own(project: Project) -> bool:
    return str(project.metadata.get("footage_mode") or "") == "own"


def set_footage(project_id: str, dir: Optional[str] = None, mode: Optional[str] = None) -> Dict[str, Any]:
    project = Project.load(project_id)
    if dir is not None:
        folder = str(dir).strip()
        if folder:
            if not os.path.isdir(folder):
                raise ValueError(f"Folder not found: {folder}")
            project.metadata["footage_dir"] = folder
        else:
            project.metadata.pop("footage_dir", None)
    if mode is not None:
        if mode not in ("own", ""):
            raise ValueError("mode must be 'own' or ''")
        project.metadata["footage_mode"] = mode
    project.save()
    return settings(project)


def settings(project: Project) -> Dict[str, Any]:
    return {"footage_dir": footage_dir(project), "footage_mode": str(project.metadata.get("footage_mode") or ""),
            "custom_dir": bool(project.metadata.get("footage_dir"))}


def parse_shot(name: str) -> Optional[int]:
    """The script shot a file name pins it to: shot06, s6, sh-6, scene2 -> the number."""
    stem = os.path.splitext(os.path.basename(name or ""))[0]
    m = _SHOT_RE.search(stem)
    return int(m.group(1)) if m else None


def _slug(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "clip"


# ───────────────────────── reading one clip ─────────────────────────

def _probe(path: str) -> Dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
                          "-of", "json", path], capture_output=True, text=True, timeout=60, creationflags=_NO_WINDOW)
    data = json.loads(out.stdout or "{}")
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"duration": round(float((data.get("format") or {}).get("duration") or 0.0), 2),
            "width": int(video.get("width") or 0), "height": int(video.get("height") or 0),
            "has_audio": any(s.get("codec_type") == "audio" for s in streams)}


def frames_dir(project: Project) -> str:
    path = os.path.join(project.get_project_dir(), "production", "footage_frames")
    os.makedirs(path, exist_ok=True)
    return path


def extract_frames(path: str, duration: float, out_dir: str, stem: str) -> List[str]:
    """Three jpgs at 10/50/90% of the clip (the 50% one is kept as the thumbnail)."""
    frames: List[str] = []
    for i, point in enumerate(_FRAME_POINTS):
        target = os.path.join(out_dir, f"{stem}_{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.0, duration * point):.2f}", "-i", path,
                        "-frames:v", "1", "-vf", "scale='min(768,iw)':-2", "-q:v", "4", target],
                       capture_output=True, timeout=60, creationflags=_NO_WINDOW)
        if os.path.isfile(target):
            frames.append(target)
    return frames


_VISION_PROMPT = (
    "These are three frames (start, middle, end) of one short video clip. Describe what the clip shows. "
    "Reply with JSON only: {\"what\": \"one plain sentence\", \"place\": \"where\", \"action\": \"what happens\", "
    "\"mood\": \"a word or two\", \"people\": \"who is visible, or none\"}.")


def _describe(frames: Sequence[str]) -> Dict[str, Any]:
    """One call to the local LM Studio model with vision, all frames together."""
    from integrations import llm

    cfg = llm.load_config()
    base = str(cfg.get("lm_studio_url") or "http://127.0.0.1:1234/v1").replace("localhost", "127.0.0.1").rstrip("/")
    content: List[Dict[str, Any]] = [{"type": "text", "text": _VISION_PROMPT}]
    for frame in frames:
        with open(frame, "rb") as fh:
            uri = "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": uri}})
    # Thinking off: Gemma 4 otherwise spends the whole budget reasoning and
    # answers with empty content (measured 2026-10-29).
    payload = {"model": cfg.get("lm_studio_model"), "messages": [{"role": "user", "content": content}],
               "temperature": 0.2, "max_tokens": 400, "reasoning_effort": "none"}
    with llm.llm_job("planning", "footage"):
        resp = requests.post(f"{base}/chat/completions", json=payload, timeout=VISION_TIMEOUT_S)
    if resp.status_code != 200:
        raise RuntimeError(f"LM Studio vision call returned {resp.status_code}: {resp.text[:300]}")
    text = resp.json()["choices"][0]["message"]["content"]
    try:
        data = json.loads(llm.clean_json_response(text))
    except (ValueError, TypeError):
        data = {"what": str(text).strip()[:300]}
    return {k: str((data or {}).get(k) or "").strip() for k in ("what", "place", "action", "mood", "people")}


def _read_clip(project: Project, path: str, previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    stat = os.stat(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    sig = {"size": stat.st_size, "mtime": int(stat.st_mtime)}
    if previous and previous.get("sig") == sig and previous.get("description") and not previous.get("error"):
        return previous
    clip: Dict[str, Any] = {"id": _slug(stem), "name": os.path.basename(path), "path": os.path.abspath(path).replace("\\", "/"),
                            "shot": parse_shot(path), "sig": sig, "description": None, "error": None}
    try:
        clip.update(_probe(path))
        frames = extract_frames(path, float(clip["duration"]), frames_dir(project), clip["id"])
        if not frames:
            raise RuntimeError("no frames could be read")
        clip["description"] = _describe(frames)
        # The 50% frame is the thumbnail (kept); the others were scratch.
        keep = min(1, len(frames) - 1)
        for i, frame in enumerate(frames):
            if i != keep:
                os.remove(frame)
        clip["frame"] = os.path.basename(frames[keep])
    except Exception as exc:  # noqa: BLE001 - one bad clip never fails the catalog
        logger.warning("footage: could not read %s (%s)", path, exc)
        clip["error"] = str(exc)[:200]
    return clip


# ───────────────────────── the catalog ─────────────────────────

def load_catalog(project: Project) -> List[Dict[str, Any]]:
    try:
        with open(catalog_path(project), "r", encoding="utf-8") as fh:
            return (json.load(fh) or {}).get("clips") or []
    except (OSError, ValueError):
        return []


def _save_catalog(project: Project, clips: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(catalog_path(project)), exist_ok=True)
    with open(catalog_path(project), "w", encoding="utf-8") as fh:
        json.dump({"updated_at": datetime.now().isoformat(timespec="seconds"), "dir": footage_dir(project),
                   "clips": clips}, fh, indent=2, ensure_ascii=False)


def catalog(project: Project, refresh: bool = False,
            progress: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    """Every video file in the footage folder, read and cached per file
    (size + mtime). `refresh` re-reads every file; his `note` is always kept."""
    folder = footage_dir(project)
    old = {c.get("path"): c for c in load_catalog(project)}
    files = sorted(os.path.join(folder, n) for n in os.listdir(folder)
                   if n.lower().endswith(VIDEO_EXTS) and os.path.isfile(os.path.join(folder, n)))
    clips: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for n, path in enumerate(files):
        if progress:
            progress(f"Reading clip {n + 1}/{len(files)}: {os.path.basename(path)}")
        key = os.path.abspath(path).replace("\\", "/")
        previous = old.get(key)
        clip = _read_clip(project, path, None if refresh else previous)
        if previous and previous.get("note"):
            clip["note"] = previous["note"]
        seen[clip["id"]] = seen.get(clip["id"], 0) + 1
        if seen[clip["id"]] > 1:
            clip["id"] = f"{clip['id']}-{seen[clip['id']]}"
        clips.append(clip)
    _save_catalog(project, clips)
    return clips


def set_note(project_id: str, clip_id: str, text: str) -> Dict[str, Any]:
    project = Project.load(project_id)
    clips = load_catalog(project)
    for clip in clips:
        if clip.get("id") == clip_id:
            if text.strip():
                clip["note"] = text.strip()
            else:
                clip.pop("note", None)
            _save_catalog(project, clips)
            return clip
    raise KeyError(clip_id)


def describe_text(clip: Dict[str, Any]) -> str:
    """The note he wrote wins; else the model's reading."""
    if clip.get("note"):
        return str(clip["note"])
    d = clip.get("description") or {}
    return "; ".join(str(d[k]) for k in ("what", "action", "place") if d.get(k)) if isinstance(d, dict) else str(d)


# ───────────────────────── the script's shots ─────────────────────────

_SHOT_HEAD_RE = re.compile(r"^[\s#*_>\-]*(?:shot|scene)\s*0*(\d{1,3})\b", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
_TOKEN_RE = re.compile(r"[\wऀ-ॿ]+")


def shot_lines(script_text: str) -> Dict[int, List[str]]:
    """`{shot: [spoken lines]}` from his script's "Shot N" / "SCENE N" sections:
    the quoted lines, else the plain lines that are not camera notes."""
    out: Dict[int, List[str]] = {}
    current: Optional[int] = None
    for raw in (script_text or "").splitlines():
        head = _SHOT_HEAD_RE.match(raw)
        if head:
            current = int(head.group(1))
            out.setdefault(current, [])
            continue
        if current is None or not raw.strip():
            continue
        quoted = _QUOTE_RE.findall(raw)
        if quoted:
            out[current].extend(q.strip() for q in quoted)
    return out


def _words_of(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _find_line(line_words: List[str], keys: List[str], start: int, n: int = 8) -> Optional[Tuple[int, float]]:
    head = line_words[:n]
    if len(head) < 3:
        return None
    best: Tuple[int, float] = (-1, 0.0)
    for i in range(start, max(start, len(keys) - len(head) + 1)):
        ratio = difflib.SequenceMatcher(None, head, keys[i:i + len(head)]).ratio()
        if ratio > best[1]:
            best = (i, ratio)
            if ratio >= 0.99:
                break
    return best if best[0] >= 0 and best[1] >= 0.6 else None


def shot_spans(script_text: str, kept_words: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """`{shot: {start, end, word_start, word_end}}` -- where each script shot's
    lines are said in the recording (fuzzy match of every line's first words
    against the kept words, in order)."""
    keys = [(_words_of(str(w.get("word") or w.get("text") or "")) or [""])[0] for w in kept_words]
    spans: Dict[int, Dict[str, Any]] = {}
    cursor = 0
    for shot, lines in sorted(shot_lines(script_text).items()):
        first = last = None
        for line in lines:
            lw = _words_of(line)
            found = _find_line(lw, keys, cursor)
            if not found:
                continue
            i, _ratio = found
            end_i = min(len(keys), i + len(lw))
            first = i if first is None else min(first, i)
            last = end_i if last is None else max(last, end_i)
            cursor = i + 1
        if first is not None and last is not None and last > first:
            spans[shot] = {"word_start": first, "word_end": last,
                           "start": float(kept_words[first].get("start") or 0.0),
                           "end": float(kept_words[last - 1].get("end") or 0.0)}
    return spans


def pinned_beats(clips: Sequence[Dict[str, Any]], spans: Dict[int, Dict[str, Any]],
                 kept_words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A clip whose file name carries a shot goes where that shot's lines are said."""
    beats: List[Dict[str, Any]] = []
    for clip in clips:
        span = spans.get(clip.get("shot")) if clip.get("shot") is not None else None
        if not span or clip.get("error"):
            continue
        dur = float(clip.get("duration") or 0.0)
        in_s = 0.5 if dur > 3.0 else 0.0
        seconds = round(max(1.0, min(span["end"] - span["start"], dur - in_s)), 1)
        anchor = " ".join(str(w.get("word") or w.get("text") or "")
                          for w in kept_words[span["word_start"]:min(span["word_end"], span["word_start"] + 6)])
        beats.append({"kind": OWN_CLIP, "clip": clip["id"], "pinned": True, "anchor": anchor,
                      "start": span["start"], "end": span["end"], "word_start": span["word_start"],
                      "video_prompt": describe_text(clip), "path": clip["path"], "in": in_s, "seconds": seconds})
    return beats


# ───────────────────────── planning ─────────────────────────

def planner_section(clips: Sequence[Dict[str, Any]], genre: Optional[str], genre_secondary: Optional[str],
                    pinned: Sequence[Dict[str, Any]] = ()) -> str:
    """The own-footage planner menu: the clips, the rules, and the graphics catalog."""
    from integrations import effect_catalog

    usable = [c for c in clips if not c.get("error")]
    lines = []
    for c in usable:
        lines.append(f"- id `{c['id']}`" + (f" (shot {c['shot']})" if c.get("shot") is not None else "")
                     + f", {float(c.get('duration') or 0):.1f}s: {describe_text(c)}")
    fixed = [f"- {b['clip']} at words {b['word_start']}+ (\"{b['anchor']}\")" for b in pinned]
    return (
        "### OWN FOOTAGE first, AI pictures for ideas\n"
        "This video is cut mainly from the creator's own clips:\n"
        + ("\n".join(lines) or "(no clips)") + "\n\n"
        "Rules:\n"
        "1. For one of his clips write `{\"kind\": \"own_clip\", \"word_start\": N, \"word_end\": N, \"clip\": \"<id>\", "
        "\"in\": 0.5, \"seconds\": 6}`: `in` is where in the clip to start (skip about the first 0.5 s), "
        "`seconds` how long it stays (never past the clip's length). Choose the clip by what is being said; "
        "never invent a clip id.\n"
        "2. His clips come first: wherever a clip fits what is said, use the clip. Generated pictures (broll_image, "
        "broll_video, canvas_card, callout, stick_scene, paper_collage) support his IDEAS -- a concept, a plan, a "
        "feeling, a comparison, a 'what if', a future he imagines -- where no clip fits. Never generate his own real "
        "life as if it were real: not his desk, room, screen, dashboard, notebook, car, violin, face or the people "
        "in it. Keep generated pictures to about a third of the picture time.\n"
        "3. Voice-over stretches are covered back to back (his clips, else an idea picture); direct-to-camera lines "
        "stay on his face (no beat).\n"
        "4. Use each clip once unless more are needed. Clips pinned below are fixed: do not plan over them.\n"
        "5. Graphics from the catalog below, sparse (a statement card, kinetic text, a pill label, a numbered "
        "point, a flow diagram, a timeline, a name title) and only for words he says aloud.\n"
        + ("Pinned (fixed) clips:\n" + "\n".join(fixed) + "\n" if fixed else "")
        + "\n" + effect_catalog.prompt_section(genre, genre_secondary))


#: Most of the picture time stays his own footage (idea pictures, 2026-10-29).
GENERATED_SHARE_MAX = 0.4


def _beat_seconds(beat: Dict[str, Any]) -> float:
    try:
        return float(beat.get("seconds") or 0) or max(0.0, float(beat.get("end") or 0) - float(beat.get("start") or 0))
    except (TypeError, ValueError):
        return 0.0


def _cap_generated(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generated pictures past GENERATED_SHARE_MAX of the picture time are dropped, latest first."""
    pictures = [b for b in beats if b.get("kind") == OWN_CLIP or b.get("kind") in GENERATED_KINDS]
    total = sum(_beat_seconds(b) for b in pictures) or 1.0
    gen = [b for b in pictures if b.get("kind") in GENERATED_KINDS]
    gen_s = sum(_beat_seconds(b) for b in gen)
    drop = set()
    for b in reversed(gen):
        if gen_s / total <= GENERATED_SHARE_MAX:
            break
        drop.add(id(b))
        gen_s -= _beat_seconds(b)
    return [b for b in beats if id(b) not in drop]


def finalize_beats(beats: Sequence[Dict[str, Any]], clips: Sequence[Dict[str, Any]],
                   pinned: Sequence[Dict[str, Any]] = ()) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The own-footage plan: model beats validated (his clip is an `own_clip`
    with a known clip id; an idea picture or a graphic is a catalog kind;
    anything else is dropped), the pinned beats added, idea pictures capped at
    GENERATED_SHARE_MAX of the picture time. Returns (beats, unused clip ids)."""
    from integrations import effect_catalog

    by_id = {c["id"]: c for c in clips if not c.get("error")}
    pinned_ids = {b["clip"] for b in pinned}
    out: List[Dict[str, Any]] = list(pinned)
    for beat in beats:
        kind = effect_catalog.resolve_kind(beat.get("kind"))
        named = str(beat.get("clip") or beat.get("own") or "")
        if kind == OWN_CLIP or (kind in ("broll_video", "broll_image") and named):
            clip = by_id.get(named)
            if clip is None or clip["id"] in pinned_ids:
                continue
            dur = float(clip.get("duration") or 0.0)
            try:
                in_s = max(0.0, float(beat.get("in") or 0.0))
                span = float(beat.get("seconds") or 0.0)
            except (TypeError, ValueError):
                in_s, span = 0.0, 0.0
            in_s = min(in_s, max(0.0, dur - 1.0))
            span = span or (float(beat.get("end") or 0) - float(beat.get("start") or 0)) or 5.0
            beat = dict(beat, kind=OWN_CLIP, clip=clip["id"], path=clip["path"], **{"in": round(in_s, 1)})
            beat["seconds"] = round(max(1.0, min(span, dur - in_s)), 1)
            beat["video_prompt"] = (str(beat.get("video_prompt") or "") or describe_text(clip))[:120]
            beat["prompt"] = beat["video_prompt"]
            out.append(beat)
        elif kind in GENERATED_KINDS:
            # An idea picture (creator, 2026-10-29: "there shall be AI pictures
            # as well, to support my ideas"); its share is capped below.
            out.append(dict(beat))
        elif kind in effect_catalog.BY_KIND or kind == "sfx_cue" or kind in effect_catalog.EXISTING_KINDS:
            beat = dict(beat)
            beat.pop("image_prompt", None)
            out.append(beat)
    out.sort(key=lambda b: float(b.get("start") or 0.0))
    out = _cap_generated(out)
    used = {b["clip"] for b in out if b.get("kind") == OWN_CLIP}
    return out, [c["id"] for c in clips if c["id"] not in used]
