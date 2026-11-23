"""
The creator's own writing style, per channel: learned from his own words,
handed to every agent that writes for the channel, and checked on what comes
back.

A channel guide (prompts/channels/<Brand>.md) says what a channel is about;
this says how the creator himself writes and talks, which is what makes a
script sound like him rather than like a model. Everything lives under
`knowledge/style/<Channel>/`:

    state.json              the channel's settings: my/agent mode, the selected
                            style and the saved styles' names (plus the default
                            style's own build state)
    styles/<id>/            further saved styles, each with the files below;
                            the channel writes in the selected one (`_dir`)
    samples/*.md            his own writing, pasted or uploaded       "written"
    recordings/<project>.md what he actually SAID in a produced video  "spoken"
    rewrites.json           script line -> what he said instead, per recording
    profile.md              the style guide StyleAnalyst builds from all of it
                            (he may edit it; "Rebuild" replaces it)
    notes.md                his own rules, always included, never overwritten
    fingerprint.json        the measured numbers, rebuilt with the profile

Recordings are speech-to-text: the improvised parts carry misspellings and no
punctuation. They teach phrasing, openings, address and habits; sentence
measurements come from written samples only (from a recording only when there
is no written sample, and then only the lexical numbers).

`style_section(brand)` is the block a writing step gets; `check(text, brand)`
scores a draft against the numbers and says what to change. Nothing here
raises into a workflow: a missing or broken style store means no section.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import threading
import time
from collections import Counter
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from core.paths import KNOWLEDGE_DIR, PROMPTS_DIR

logger = logging.getLogger("buzzcaf_ai.writing_style")

STYLE_DIR = os.path.join(str(KNOWLEDGE_DIR), "style")
# The creator's story brief per channel (`<Channel>.md`), switched on or off per channel.
STANDARDS_DIR = os.path.join(str(PROMPTS_DIR), "standards")
CHANNELS = ("Raat3Baje", "Beyond3Baje", "Khayal3Baje", "Life3Baje", "Originals", "TheTallStoryteller")

#: A draft scoring below this gets one rewrite pass toward the style.
REVISE_BELOW = 75
#: The whole section stays under this (it rides on every writing call).
SECTION_CHARS = 11000
#: What the analyst reads, at most: written samples first, then recordings.
ANALYST_SAMPLE_CHARS = 16000
#: Stage directions (cue lines, speaker labels) as a share of a script's lines:
#: at or under this, the text is continuous narration.
NARRATION_STAGE_SHARE = 0.03
#: First-person words per 1000 from which a sample counts as told by "main".
FIRST_PERSON_PER_1000 = 15.0
#: The host. Every full video opens with `greeting()`, which carries this name.
CREATOR_NAME = "Sudhansu"

# Roman-script function words. Ambiguous ones (to/toh, the, main, me, is, us,
# do) are in neither list, so the English share is not skewed by them.
HINDI_WORDS = frozenset("""
hai hain tha thi ka ki ke ko se mein ne par aur ya bhi toh ye yeh wo woh vo kya kyun kyon
nahi nahin na ek kuch sab jab tab agar lekin magar phir fir hota hoti hote raha rahi rahe
gaya gayi gaye kar karke karna karte karta karti apne apna apni uska uski uske mera meri mere
hum ham aap tum unhe use usse kaise kahan yahan wahan abhi bas bahut sirf jaise waise kyunki
isliye kabhi koi kisi kitna kitni wala wali wale liye saath sath andar bahar upar neeche
""".split())
ENGLISH_WORDS = frozenset("""
the are was were an of and in on it this that with for you we they he she but or so if be
have has had not just really very actually basically like what how why when my your our can
will would does did there their them then than been being which who about into from
""".split())
ADDRESS_WORDS = frozenset("""
aap aapko aapne aapka aapki aapke tum tumhe tumko tumne tumhara tumhari doston dosto yaar
friends guys
""".split())
# "main" is also a spelling of "mein" (in), so it is not counted on its own.
FIRST_PERSON_WORDS = frozenset("maine mujhe mujhse mujhko mera meri mere".split())

# Screenplay layout: a line that is only a [cue] or a (cue), a speaker label
# ("**ARJUN (V.O.)**", "NARRATOR:"), and cues inside a spoken line.
_CUE_LINE_RE = re.compile(r"^\s*[*_>]*\s*[\[(].*[\])]\s*[*_]*\s*$")
_LABEL = r"(?:[A-Z][A-Za-z .'-]{0,30}?\s*\(\s*(?i:v\.?\s*o\.?|o\.?\s*s\.?|o\.?\s*c\.?|cont'?d|voice[- ]?over)[^)]*\)|NARRATOR|NARRATION|HOST|V\.?O\.?)"
_LABEL_ONLY_RE = re.compile(rf"^\s*[*_]*\s*{_LABEL}\s*[*_]*\s*:?\s*[*_]*\s*$")
_LABEL_PREFIX_RE = re.compile(rf"^\s*[*_]*\s*{_LABEL}\s*[*_]*\s*:\s*[*_]*\s*")
_BRACKET_RE = re.compile(r"\[[^\]\n]{0,400}\]")
_PAREN_CUE_RE = re.compile(
    r"\(\s*(?:long\s+)?(?:pause|beat|hold|silence|breath|slow|slower|slowly|fast|faster|normal|whisper|softly)\b"
    r"[^)\n]{0,20}\)", re.IGNORECASE)
_RULE_RE = re.compile(r"^\s*([-*_=]\s*){3,}$")
_GREETING_NOTE_RE = re.compile(r"^\s*(?:[-*]\s*)?\**greeting\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
# A sentence that greets the viewer and introduces the host or the show.
_GREETING_SENTENCE_RE = re.compile(
    r"(?:[^.!?\n]|\.\.\.|…)*\b(?:doston|dosto)\b(?:[^.!?\n]|\.\.\.|…)*"
    r"\b(?:main hoon|mera naam|naam hai|dekh rahe|sun rahe)\b(?:[^.!?\n]|\.\.\.|…)*[.!?]*",
    re.IGNORECASE)

# The lines that belong to a video's opening and nowhere else: "aaj ki kahani
# ... par aadharit hai", the subscribe request, "toh chaliye ... kahani shuru /
# sunte hain". A writer who is shown the opening in every section (and a
# rewrite pass that is shown it for every part) puts them back at the start of
# the section it is writing; they are stripped from everything but the opening.
_INTRO_SENTENCE_RES = (
    re.compile(r"\baaj ki (?:yeh |ye |is )?kahani\b.*?\b(?:aadharit|based|hai|sunte|sunaata|sunata|lekar|laya)\b",
               re.IGNORECASE),
    re.compile(r"\bchannel\b.*?\bsubscribe\b|\bsubscribe\b.*?\bchannel\b", re.IGNORECASE),
    re.compile(r"\b(?:toh |to )?chaliye\b.*?\bkahani\b|\bkahani (?:ko )?(?:shuru|suru) kar", re.IGNORECASE),
    re.compile(r"\b(?:aapke|apke) liye\b.*?\bkahani\b.*?\b(?:lekar|laya|laaya|le kar)\b", re.IGNORECASE),
    re.compile(r"\b(?:yeh|ye) kahani us (?:waqt|samay) ki hai\b", re.IGNORECASE),
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_SENTENCE_RE = re.compile(r"(?<=[.!?।])\s+|\n+")
_DIRECTIVE_RE = re.compile(r"\[\s*[a-z_]+\s*:[^\]]*\]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*#{1,6}\s.*$", re.MULTILINE)
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_NEVER_RE = re.compile(r"^\s*(?:[-*]\s*)?\**never use\**\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


# ---------------------------------------------------------------- the store

def canonical_channel(brand: str) -> str:
    """The style folder for a brand name (same mapping as the channel guides)."""
    lower = (brand or "").lower()
    if "raat" in lower or "after dark" in lower or "afterdark" in lower:
        return "Raat3Baje"
    if "khayal" in lower:
        return "Khayal3Baje"
    if "life" in lower:
        return "Life3Baje"
    if "originals" in lower or "spilled" in lower:
        return "Originals"
    if "beyond" in lower:
        return "Beyond3Baje"
    if "storyteller" in lower or "tallstoryteller" in lower:
        return "TheTallStoryteller"
    return re.sub(r"[^A-Za-z0-9]", "", brand or "") or "General"


#: The style a channel starts with: it lives in the channel folder itself.
#: Further saved styles live in `<Channel>/styles/<id>/`, same layout.
DEFAULT_STYLE = "default"
_STYLE_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def _root(channel: str, *parts: str) -> str:
    """The channel's folder: its settings (mode, the selected style) and its default style."""
    return os.path.join(STYLE_DIR, canonical_channel(channel), *parts)


def _root_state(channel: str) -> Dict[str, Any]:
    try:
        with open(_root(channel, "state.json"), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def active_style(channel: str) -> str:
    """The id of the style the channel writes in now."""
    chosen = _root_state(channel).get("style")
    if (isinstance(chosen, str) and chosen != DEFAULT_STYLE and _STYLE_ID_RE.match(chosen)
            and os.path.isdir(_root(channel, "styles", chosen))):
        return chosen
    return DEFAULT_STYLE


def _style_base(channel: str, style_id: str) -> str:
    return _root(channel) if style_id == DEFAULT_STYLE else _root(channel, "styles", style_id)


def _dir(channel: str, *parts: str) -> str:
    """A path inside the channel's SELECTED style: everything below -- samples,
    profile, notes, numbers -- reads and writes the style that is in use."""
    return os.path.join(_style_base(channel, active_style(channel)), *parts)


#: A channel with nothing of its own yet -- no sample, recording, guide or rules --
#: writes in another channel's style until it has some (2026-10-24: TheTallStoryteller
#: had none, so its scripts got no style section, no score and the screenplay layout,
#: and "not my style" was the result). Config `style_borrow` {channel: from} overrides.
STYLE_BORROW: Dict[str, str] = {"TheTallStoryteller": "Raat3Baje"}


def _has_own_style(channel: str) -> bool:
    if _read(_dir(channel, "profile.md")).strip() or _read(_dir(channel, "notes.md")).strip():
        return True
    return any(_count(_style_base(channel, active_style(channel)), folder) for folder in _STYLE_FOLDERS)


def style_source(brand: str) -> str:
    """The channel whose style a brand writes in: its own, or -- while it has none --
    the one `STYLE_BORROW` (or config `style_borrow`) names. Reads only: samples,
    recordings and rules added for the brand still go to its own folder."""
    channel = canonical_channel(brand)
    if _has_own_style(channel):
        return channel
    borrow = dict(STYLE_BORROW)
    try:
        from integrations.llm import load_config
        borrow.update({str(k): str(v) for k, v in (load_config().get("style_borrow") or {}).items() if v})
    except Exception:  # noqa: BLE001
        pass
    if not borrow.get(channel):
        return channel
    source = canonical_channel(borrow[channel])
    return source if source != channel and _has_own_style(source) else channel


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)


def _slug(text: str, limit: int = 60) -> str:
    return (re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")[:limit] or "sample")


def _body(text: str) -> str:
    """A stored sample without its title line and the note under it."""
    lines = text.splitlines()
    while lines and (lines[0].startswith("# ") or lines[0].startswith("> ") or not lines[0].strip()):
        lines.pop(0)
    return "\n".join(lines).strip()


def list_samples(channel: str) -> List[Dict[str, Any]]:
    out = []
    for kind, folder in (("written", "samples"), ("spoken", "recordings")):
        base = _dir(channel, folder)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if not name.endswith((".md", ".txt")):
                continue
            path = os.path.join(base, name)
            text = _read(path)
            first = text.splitlines()[0] if text else ""
            out.append({
                "id": f"{folder}/{name}", "kind": kind,
                "title": first[2:].strip() if first.startswith("# ") else name.rsplit(".", 1)[0],
                "words": len(_WORD_RE.findall(_body(text))),
                "added": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
            })
    return out


def add_sample(channel: str, title: str, text: str) -> Dict[str, Any]:
    """Store one of the creator's own pieces of writing."""
    text = (text or "").strip()
    if len(_WORD_RE.findall(text)) < 40:
        raise ValueError("A sample needs at least 40 words of your own writing to learn from.")
    title = (title or "").strip() or text.splitlines()[0][:60]
    name = f"{time.strftime('%Y%m%d_%H%M%S')}_{_slug(title)}.md"
    _write(_dir(channel, "samples", name), f"# {title}\n\n{text}\n")
    _mark_stale(channel)
    return {"id": f"samples/{name}", "title": title}


def delete_sample(channel: str, sample_id: str) -> bool:
    folder, _, name = (sample_id or "").partition("/")
    if folder not in ("samples", "recordings") or not name or "/" in name or "\\" in name or ".." in name:
        raise ValueError("Unknown sample.")
    path = _dir(channel, folder, name)
    if not os.path.exists(path):
        return False
    os.remove(path)
    if folder == "recordings":
        rewrites = _load_rewrites(channel)
        if rewrites.pop(name.rsplit(".", 1)[0], None) is not None:
            _write(_dir(channel, "rewrites.json"), json.dumps(rewrites, ensure_ascii=False, indent=1))
    _mark_stale(channel)
    return True


def _samples_text(channel: str, kind: str) -> List[Tuple[str, str]]:
    folder = "samples" if kind == "written" else "recordings"
    base = _dir(channel, folder)
    if not os.path.isdir(base):
        return []
    names = sorted(os.listdir(base), key=lambda n: os.path.getmtime(os.path.join(base, n)), reverse=True)
    return [(n, _body(_read(os.path.join(base, n)))) for n in names if n.endswith((".md", ".txt"))]


def _load_rewrites(channel: str) -> Dict[str, List[Dict[str, str]]]:
    try:
        data = json.loads(_read(_dir(channel, "rewrites.json")) or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _state(channel: str) -> Dict[str, Any]:
    try:
        return json.loads(_read(_dir(channel, "state.json")) or "{}")
    except ValueError:
        return {}


def _mark_stale(channel: str) -> None:
    state = _state(channel)
    state["stale"] = True
    _write(_dir(channel, "state.json"), json.dumps(state, indent=1))


# ------------------------------------------------------------- the toggle
#
# "mine": agents write in the creator's own style (the section, the score and
# the one rewrite). "agent": they write in the channel guide's voice only, as
# before any of this existed. Set per channel; a project may override it
# (`project.metadata["writing_style"]`), absent meaning "the channel's".

MODES = ("mine", "agent")


def channel_mode(channel: str) -> str:
    mode = _root_state(channel).get("mode")
    return mode if mode in MODES else "mine"


def set_channel_mode(channel: str, mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Writing style must be one of: {', '.join(MODES)}.")
    state = _root_state(channel)
    state["mode"] = mode
    _write(_root(channel, "state.json"), json.dumps(state, indent=1))


# ---------------------------------------------------------- the story standard

def _standard_path(channel: str) -> str:
    return os.path.join(STANDARDS_DIR, f"{canonical_channel(channel)}.md")


def has_standard(channel: str) -> bool:
    return os.path.isfile(_standard_path(channel))


def standard_on(brand: str, project: Any = None) -> bool:
    """On by default whenever the channel has a standard file; channel-level only."""
    if not has_standard(brand):
        return False
    return bool(_root_state(canonical_channel(brand)).get("story_standard", True))


def set_standard(channel: str, on: bool) -> None:
    state = _root_state(channel)
    state["story_standard"] = bool(on)
    _write(_root(channel, "state.json"), json.dumps(state, indent=1))


def standard_section(brand: str, project: Any = None) -> str:
    """The channel's story standard, for every script-writing step; empty when off."""
    try:
        if not standard_on(brand, project):
            return ""
        with open(_standard_path(brand), "r", encoding="utf-8") as fh:
            text = re.sub(r"<!--.*?-->", "", fh.read(), flags=re.S).strip()
        return "\n\n" + text + "\n" if text else ""
    except Exception as exc:  # noqa: BLE001 - a missing file must not stop a step
        logger.warning("Writing style: no story standard for %s (%s).", brand, exc)
        return ""


# ------------------------------------------------------------ saved styles
#
# A channel can keep several styles -- each with its own samples, profile,
# rules and numbers -- and writes in the one that is selected. The first
# ("default") is the channel folder itself; the others sit in `styles/<id>/`.
# Their names and the selection are in the channel's own state.json.

_STYLE_FILES = ("profile.md", "notes.md", "fingerprint.json", "rewrites.json")
_STYLE_FOLDERS = ("samples", "recordings")


def _count(base: str, folder: str) -> int:
    path = os.path.join(base, folder)
    return sum(1 for n in os.listdir(path) if n.endswith((".md", ".txt"))) if os.path.isdir(path) else 0


def list_styles(channel: str) -> List[Dict[str, Any]]:
    """Every saved style of the channel, the default first."""
    channel = canonical_channel(channel)
    root = _root_state(channel)
    names = root.get("styles") if isinstance(root.get("styles"), dict) else {}
    active = active_style(channel)
    ids = [DEFAULT_STYLE]
    folder = _root(channel, "styles")
    if os.path.isdir(folder):
        ids += sorted(n for n in os.listdir(folder) if _STYLE_ID_RE.match(n) and os.path.isdir(os.path.join(folder, n)))
    out = []
    for style_id in ids:
        base = _style_base(channel, style_id)
        try:
            state = json.loads(_read(os.path.join(base, "state.json")) or "{}")
        except ValueError:
            state = {}
        built = bool(_read(os.path.join(base, "profile.md")).strip())
        out.append({
            "id": style_id,
            "name": (root.get("default_name") or "Default") if style_id == DEFAULT_STYLE else (names.get(style_id) or style_id),
            "active": style_id == active,
            "written": _count(base, "samples"), "spoken": _count(base, "recordings"),
            "built_at": state.get("built_at") if built else None,
        })
    return out


def _style_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    if not name:
        raise ValueError("Give the style a name.")
    if len(name) > 60:
        raise ValueError("A style name is at most 60 characters.")
    return name


def _known_style(channel: str, style_id: str) -> str:
    if style_id != DEFAULT_STYLE and not (_STYLE_ID_RE.match(style_id or "")
                                          and os.path.isdir(_root(channel, "styles", style_id))):
        raise ValueError("Unknown style.")
    return style_id


def create_style(channel: str, name: str, copy: bool = False) -> Dict[str, Any]:
    """A new saved style, selected at once: empty, or (`copy`) a copy of the
    style in use -- its samples, profile, rules and numbers."""
    channel = canonical_channel(channel)
    name = _style_name(name)
    if any(s["name"].lower() == name.lower() for s in list_styles(channel)):
        raise ValueError(f"{channel} already has a style called \"{name}\".")
    base_id = _slug(name, 32).lower()
    style_id, n = base_id, 2
    while style_id == DEFAULT_STYLE or os.path.exists(_root(channel, "styles", style_id)):
        style_id, n = f"{base_id}_{n}", n + 1
    source, target = _style_base(channel, active_style(channel)), _root(channel, "styles", style_id)
    os.makedirs(target, exist_ok=True)
    if copy:
        for folder in _STYLE_FOLDERS:
            if os.path.isdir(os.path.join(source, folder)):
                shutil.copytree(os.path.join(source, folder), os.path.join(target, folder), dirs_exist_ok=True)
        for file_name in _STYLE_FILES:
            if os.path.exists(os.path.join(source, file_name)):
                shutil.copy2(os.path.join(source, file_name), os.path.join(target, file_name))
        kept = {k: v for k, v in _state(channel).items() if k in ("stale", "built_at", "written", "spoken")}
        _write(os.path.join(target, "state.json"), json.dumps(kept, indent=1))
    root = _root_state(channel)
    root["styles"] = {**(root.get("styles") if isinstance(root.get("styles"), dict) else {}), style_id: name}
    root["style"] = style_id
    _write(_root(channel, "state.json"), json.dumps(root, ensure_ascii=False, indent=1))
    return overview(channel)


def select_style(channel: str, style_id: str) -> Dict[str, Any]:
    """Write in this saved style from now on."""
    channel = canonical_channel(channel)
    root = _root_state(channel)
    root["style"] = _known_style(channel, style_id)
    _write(_root(channel, "state.json"), json.dumps(root, ensure_ascii=False, indent=1))
    return overview(channel)


def rename_style(channel: str, style_id: str, name: str) -> Dict[str, Any]:
    channel = canonical_channel(channel)
    name = _style_name(name)
    _known_style(channel, style_id)
    if any(s["name"].lower() == name.lower() and s["id"] != style_id for s in list_styles(channel)):
        raise ValueError(f"{channel} already has a style called \"{name}\".")
    root = _root_state(channel)
    if style_id == DEFAULT_STYLE:
        root["default_name"] = name
    else:
        root["styles"] = {**(root.get("styles") if isinstance(root.get("styles"), dict) else {}), style_id: name}
    _write(_root(channel, "state.json"), json.dumps(root, ensure_ascii=False, indent=1))
    return overview(channel)


def delete_style(channel: str, style_id: str) -> Dict[str, Any]:
    """Remove a saved style and everything in it. The default style stays."""
    channel = canonical_channel(channel)
    if style_id == DEFAULT_STYLE:
        raise ValueError("The default style cannot be deleted; remove its samples instead.")
    _known_style(channel, style_id)
    shutil.rmtree(_root(channel, "styles", style_id), ignore_errors=True)
    root = _root_state(channel)
    if isinstance(root.get("styles"), dict):
        root["styles"].pop(style_id, None)
    if root.get("style") == style_id:
        root["style"] = DEFAULT_STYLE
    _write(_root(channel, "state.json"), json.dumps(root, ensure_ascii=False, indent=1))
    return overview(channel)


def mode_for(brand: str, project: Any = None) -> str:
    """The mode a piece of writing uses: the project's choice, else the channel's."""
    metadata = getattr(project, "metadata", None) or {}
    chosen = metadata.get("writing_style")
    return chosen if chosen in MODES else channel_mode(canonical_channel(brand))


def uses_my_style(brand: str, project: Any = None) -> bool:
    return mode_for(brand, project) == "mine"


# ---------------------------------------------------------- the recordings

def spoken_text(rendered_script: str) -> str:
    """The words of a rendered directive script, without directives or headings."""
    text = _HEADING_RE.sub("", _DIRECTIVE_RE.sub("", rendered_script or ""))
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def narration_text(script: str) -> str:
    """Only the words that are said: a script without headings, [cue] and
    (cue) lines, speaker labels, and the cues inside a spoken line."""
    out: List[str] = []
    for line in (script or "").replace("\r\n", "\n").split("\n"):
        if (_HEADING_RE.match(line) or _CUE_LINE_RE.match(line) or _LABEL_ONLY_RE.match(line)
                or _RULE_RE.match(line)):
            out.append("")
            continue
        line = _PAREN_CUE_RE.sub(" ", _BRACKET_RE.sub(" ", _LABEL_PREFIX_RE.sub("", line)))
        out.append(line.replace("**", "").replace("__", ""))
    text = re.sub(r"[ \t]+", " ", "\n".join(out))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def narration_words(script: str) -> int:
    """How many words of a script are actually said."""
    return len(narration_text(script).split())


def stage_share(script: str) -> float:
    """The share of a script's lines that are stage directions: cue lines,
    speaker labels, or spoken lines carrying a [cue] or a (pause)."""
    lines = [l for l in (script or "").splitlines() if l.strip() and not _HEADING_RE.match(l)]
    if not lines:
        return 0.0
    staged = sum(1 for l in lines if _CUE_LINE_RE.match(l) or _LABEL_ONLY_RE.match(l) or _LABEL_PREFIX_RE.match(l)
                 or _BRACKET_RE.search(l) or _PAREN_CUE_RE.search(l))
    return round(staged / len(lines), 3)


# -------------------------------------------------------------- the greeting

def spoken_channel_name(brand: str) -> str:
    """The channel's name as it is said: "Raat3Baje" -> "Raat 3 Baje",
    "TheTallStoryteller" -> "The Tall Storyteller" (the letter-digit split plus
    a camelCase word split, since 2026-10-23 for the first multi-word channel
    name with no digit in it; no existing channel name has an internal
    lowercase-to-uppercase transition, so this only ever adds a space here)."""
    return re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])|(?<=[a-z])(?=[A-Z])", " ", canonical_channel(brand))


def greeting(brand: str) -> str:
    """The line every full video opens with (the creator's rule, 2026-10-06):
    his name and the channel's. A `Greeting: ...` line in his notes replaces it."""
    channel = canonical_channel(brand)
    own = _GREETING_NOTE_RE.search(_read(_dir(channel, "notes.md")))
    if own and own.group(1).strip().strip("\"'` "):
        return own.group(1).strip().strip("\"'` ")
    return f"Hello doston, mera naam hai {CREATOR_NAME} aur aap dekh rahe hain {spoken_channel_name(channel)}."


def _flat(text: str) -> str:
    return " ".join(w.lower() for w in _WORD_RE.findall(text))


def _is_greeting(sentence: str) -> bool:
    return bool(_GREETING_SENTENCE_RE.search(sentence)) and not _HEADING_RE.match(sentence)


def _is_intro_line(sentence: str) -> bool:
    return any(r.search(sentence) for r in _INTRO_SENTENCE_RES)


def strip_repeated_intro(script: str, keep_first: bool = True) -> Tuple[str, int]:
    """The greeting and the opening lines once, at the start, and nowhere else.

    A sectioned script (and a rewrite in parts) shows the writer the opening
    for every piece, and a small model re-opens the video in the middle of the
    story: "Hello doston, mera naam hai ..." five times in a 25-minute script.
    Every greeting sentence after the first (or every one at all, with
    `keep_first=False`: a middle section or part) is removed, together with the
    opening lines that came with it in the same paragraph (the "aaj ki kahani
    ... par aadharit hai" line, the subscribe request, "toh chaliye ..."). A
    paragraph emptied this way disappears. Returns the text and how many
    greetings were removed."""
    if not (script or "").strip():
        return script, 0
    out: List[str] = []
    removed = 0
    seen = not keep_first
    # After a removed greeting, the opening lines that follow it are dropped
    # too -- in the same paragraph, or at the head of the next one when the
    # greeting stood on a line of its own. The first story sentence ends it.
    drop_intro = False
    for para in script.split("\n\n"):
        lines = []
        for line in para.split("\n"):
            if _HEADING_RE.match(line) or not line.strip():
                lines.append(line)
                continue
            sentences = _SENTENCE_SPLIT_RE.split(line)
            kept = []
            touched = False
            for sent in sentences:
                if _is_greeting(sent):
                    if seen:
                        removed += 1
                        drop_intro = touched = True
                        continue
                    seen = True
                    kept.append(sent)
                    continue
                if drop_intro and _is_intro_line(sent):
                    touched = True
                    continue
                drop_intro = False
                kept.append(sent)
            if not touched:
                lines.append(line)
            elif " ".join(kept).strip():
                lines.append(" ".join(kept).strip())
        text = "\n".join(lines)
        if text.strip():
            out.append(text)
    if not removed:
        return script, 0
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(out)), removed


def sample_copy_ratio(text: str, brand: str, n: int = 8) -> Tuple[float, List[str]]:
    """How much of `text` is lifted word for word from his written samples:
    the share of its `n`-word runs that appear in a sample (his fixed greeting
    excluded), and a few of the copied runs. A writer shown his examples
    "for manner only" sometimes retells them instead; this catches it."""
    channel = canonical_channel(brand)
    samples = [t for _, t in _samples_text(channel, "written")]
    if not samples or not (text or "").strip():
        return 0.0, []
    skip = _flat(greeting(channel))

    def runs(t: str):
        w = _flat(narration_text(t)).split()
        return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}

    mine = {r for r in runs(text) if r not in skip}
    if not mine:
        return 0.0, []
    theirs = set()
    for sample in samples:
        theirs |= runs(sample)
    hit = sorted(mine & theirs)
    return len(hit) / len(mine), hit[:5]


def ensure_greeting(script: str, brand: str) -> Tuple[str, bool]:
    """A full script with his greeting in it, word for word, once. A greeting
    the writer worded differently (or borrowed from a sample: another host,
    another show) is replaced; a script with none gets it as its first line;
    a greeting repeated later in the script is removed with the opening lines
    around it (`strip_repeated_intro`). Returns the script and whether it was
    changed."""
    line = greeting(brand)
    if not (script or "").strip():
        return script, False
    script, removed = strip_repeated_intro(script, keep_first=True)
    if _flat(line) in _flat(narration_text(script)[:6000]):
        return script, removed > 0
    head, rest = script[:4000], script[4000:]
    found = next((m for m in _GREETING_SENTENCE_RE.finditer(head) if not _HEADING_RE.match(m.group(0))), None)
    if found and found.group(0).strip():
        lead = re.match(r"\s*", found.group(0)).group(0)
        return head[:found.start()] + lead + line + head[found.end():] + rest, True
    lines = script.split("\n")
    at = next((k for k, l in enumerate(lines) if l.strip() and not _HEADING_RE.match(l)), len(lines))
    return "\n".join(lines[:at] + [line, ""] + lines[at:]), True


def rewrite_pairs(script_tokens: List[str], words: List[str],
                  script_to_word: Dict[int, int], limit: int = 60) -> List[Dict[str, str]]:
    """Where he said something else than the script: between two aligned
    words, the script's words and the words he spoke instead. Only stretches
    of a few words to a sentence or two -- a skipped paragraph or a long
    improvisation says nothing about how he rephrases a line."""
    pairs: List[Dict[str, str]] = []
    # Words the recogniser got right: the script's own words and everyday ones.
    # An improvised stretch it misheard ("rijistar", "ramadal") is not a
    # rephrasing anyone can learn from.
    known = {w.lower() for t in script_tokens for w in _WORD_RE.findall(t)} | HINDI_WORDS | ENGLISH_WORDS
    matched = sorted(script_to_word.items())
    for (i0, j0), (i1, j1) in zip(matched, matched[1:]):
        gap_s, gap_w = i1 - i0 - 1, j1 - j0 - 1
        if not (2 <= gap_s <= 30 and 2 <= gap_w <= 40 and 0.4 <= gap_w / gap_s <= 2.5):
            continue
        before = " ".join(script_tokens[i0 + 1:i1]).strip()
        after = " ".join(words[j0 + 1:j1]).strip()
        said = [w.lower() for w in _WORD_RE.findall(after)]
        if not said or sum(1 for w in said if w in known) / len(said) < 0.5:
            continue
        # A rephrasing still resembles the line it replaces; a skipped
        # passage lined up against an unrelated ad-lib does not.
        likeness = SequenceMatcher(None, before.lower(), after.lower()).ratio()
        if before and after and before.lower() != after.lower() and likeness >= 0.4:
            pairs.append({"script": before, "said": after})
    pairs.sort(key=lambda p: -len(p["script"]))
    return pairs[:limit]


def save_recording(brand: str, project_id: str, title: str, rendered_script: str,
                   pairs: Optional[List[Dict[str, str]]] = None) -> Optional[str]:
    """Keep what the creator said in a produced video as a spoken sample."""
    text = spoken_text(rendered_script)
    if len(_WORD_RE.findall(text)) < 80:
        return None
    channel = canonical_channel(brand)
    name = _slug(project_id, 120)
    _write(_dir(channel, "recordings", f"{name}.md"),
           f"# {title or project_id}\n> Transcribed from the recording (speech-to-text: spelling is "
           f"approximate, punctuation missing where he improvised).\n\n{text}\n")
    if pairs is not None:
        rewrites = _load_rewrites(channel)
        rewrites[name] = pairs
        _write(_dir(channel, "rewrites.json"), json.dumps(rewrites, ensure_ascii=False, indent=1))
    _mark_stale(channel)
    logger.info("Writing style: kept the recording of %s as a %s sample (%d words, %d rewrites).",
                project_id, channel, len(_WORD_RE.findall(text)), len(pairs or []))
    return name


def harvest_from_reconciliation(project: Any, rec: Any) -> Optional[str]:
    """After a production: keep his spoken words and how he rephrased the script."""
    try:
        pairs = rewrite_pairs(rec.parsed.tokens, rec.words, rec.script_to_word)
        return save_recording(project.brand, project.id, project.name, rec.render(), pairs)
    except Exception as exc:  # noqa: BLE001 - never fails a production
        logger.warning("Writing style: could not keep the recording of %s (%s).",
                       getattr(project, "id", "?"), exc)
        return None


def harvest_projects(channel: str) -> Dict[str, Any]:
    """Learn from every produced video of the channel already on disk: the
    rendered script BuzzEdit got is the recording's own words, and the
    project's script is what he was reading."""
    from core.models.project import Project
    from core.paths import PROJECTS_DIR
    from integrations.script_reconcile import Reconciliation

    want = canonical_channel(channel)
    found, kept = 0, []
    for name in sorted(os.listdir(str(PROJECTS_DIR))):
        rendered_path = os.path.join(str(PROJECTS_DIR), name, "script", "buzzedit_script.md")
        if not os.path.exists(rendered_path):
            continue
        try:
            project = Project.load(name)
        except Exception:  # noqa: BLE001
            continue
        if canonical_channel(project.brand) != want:
            continue
        found += 1
        rendered = _read(rendered_path)
        script_rel = (project.assets or {}).get("script")
        script = _read(os.path.join(project.get_project_dir(), script_rel)) if script_rel else ""
        pairs: Optional[List[Dict[str, str]]] = None
        if script:
            words = [{"word": w} for w in spoken_text(rendered).split()]
            rec = Reconciliation(script, words)
            pairs = rewrite_pairs(rec.parsed.tokens, rec.words, rec.script_to_word)
        if save_recording(project.brand, project.id, project.name, rendered, pairs):
            kept.append(project.name)
    return {"projects_with_recordings": found, "kept": kept}


# --------------------------------------------------------- the fingerprint

def _sentences(text: str) -> List[List[str]]:
    out = []
    for raw in _SENTENCE_RE.split(text):
        words = _WORD_RE.findall(raw)
        if words:
            out.append(words)
    return out


def fingerprint(text: str, spoken: bool = False) -> Dict[str, Any]:
    """The measurable habits of a text. `spoken` (a transcript) keeps only the
    lexical numbers: its sentence breaks are the recogniser's, not his."""
    raw = text or ""
    text = narration_text(spoken_text(raw))
    words = [w.lower() for w in _WORD_RE.findall(text)]
    n = len(words)
    if not n:
        return {"words": 0}
    letters = len(_LETTER_RE.findall(text)) or 1
    hindi = sum(1 for w in words if w in HINDI_WORDS)
    english = sum(1 for w in words if w in ENGLISH_WORDS)
    fp: Dict[str, Any] = {
        "words": n,
        "english_share": round(english / (hindi + english), 3) if hindi + english else None,
        "devanagari_share": round(len(_DEVANAGARI_RE.findall(text)) / letters, 3),
        "address_per_1000": round(1000.0 * sum(1 for w in words if w in ADDRESS_WORDS) / n, 1),
        "first_person_per_1000": round(1000.0 * sum(1 for w in words if w in FIRST_PERSON_WORDS) / n, 1),
        "spoken": spoken,
    }
    if not spoken:
        fp["stage_share"] = stage_share(raw)
        sentences = _sentences(text)
        lengths = sorted(len(s) for s in sentences) or [0]
        count = len(sentences) or 1
        paragraphs = [p for p in re.split(r"\n\s*\n", text) if _WORD_RE.search(p)]
        fp.update({
            "sentences": len(sentences),
            "sentence_avg": round(sum(lengths) / count, 1),
            "sentence_median": lengths[len(lengths) // 2],
            "short_share": round(sum(1 for x in lengths if x <= 6) / count, 3),
            "long_share": round(sum(1 for x in lengths if x >= 20) / count, 3),
            "paragraph_sentences": round(count / max(1, len(paragraphs)), 1),
            "ellipsis_per_100": round(100.0 * len(re.findall(r"\.\.\.|…", text)) / count, 1),
            "question_per_100": round(100.0 * text.count("?") / count, 1),
            "exclaim_per_100": round(100.0 * text.count("!") / count, 1),
            "dialogue_per_100": round(100.0 * len(re.findall(r"[\"“][^\"”]{2,}[\"”]", text)) / count, 1),
            "openers": [w for w, _ in Counter(s[0].lower() for s in sentences).most_common(8)],
        })
    return fp


def _phrases(texts: List[str], top: int = 15) -> List[str]:
    """2-4 word phrases he repeats, not made only of function words. A habit
    shows up across pieces: a phrase must appear in at least two different
    samples (within one sample, repeats are its story -- "arjun ne", "teen
    mahine" -- not him)."""
    counts: Counter = Counter()
    spread: Counter = Counter()
    for text in texts:
        words = [w.lower() for w in _WORD_RE.findall(spoken_text(text))]
        seen = set()
        for size in (4, 3, 2):
            for i in range(len(words) - size + 1):
                gram = words[i:i + size]
                if all(w in HINDI_WORDS or w in ENGLISH_WORDS or len(w) < 3 for w in gram):
                    continue
                key = " ".join(gram)
                counts[key] += 1
                seen.add(key)
        spread.update(seen)
    picked: List[str] = []
    for phrase, count in sorted(counts.items(), key=lambda kv: (-kv[1] * len(kv[0].split()), kv[0])):
        if spread[phrase] < 2:
            continue
        if any(phrase in p or p in phrase for p in picked):
            continue
        picked.append(phrase)
        if len(picked) >= top:
            break
    return picked


def measure(channel: str) -> Dict[str, Any]:
    """The channel's target numbers from his samples."""
    written = [t for _, t in _samples_text(channel, "written")]
    spoken = [t for _, t in _samples_text(channel, "spoken")]
    target: Dict[str, Any] = {}
    if written:
        target = fingerprint("\n\n".join(written))
        target["source"] = "written"
    elif spoken:
        target = fingerprint("\n\n".join(spoken), spoken=True)
        target["source"] = "spoken"
    if spoken and written:
        # How he talks to the viewer shows best in the recordings.
        talk = fingerprint("\n\n".join(spoken), spoken=True)
        target["address_per_1000"] = max(target.get("address_per_1000") or 0, talk["address_per_1000"])
    target["phrases"] = _phrases(written + spoken)
    target["openings"] = [" ".join(_WORD_RE.findall(t)[:45]) for t in spoken[:3]]
    return target


def _fingerprint_file(channel: str) -> Dict[str, Any]:
    try:
        return json.loads(_read(_dir(channel, "fingerprint.json")) or "{}")
    except ValueError:
        return {}


def targets(channel: str) -> Dict[str, Any]:
    """The saved numbers, or freshly measured ones when there are none yet."""
    saved = _fingerprint_file(channel)
    if saved and not _state(channel).get("stale"):
        return saved
    fresh = measure(channel)
    if fresh.get("words"):
        _write(_dir(channel, "fingerprint.json"), json.dumps(fresh, ensure_ascii=False, indent=1))
    return fresh


def never_words(channel: str) -> List[str]:
    """Words he never uses: a `Never use:` line in his notes (always kept) or
    the profile. A profile item that appears in his own samples is the
    analyst's mistake and is dropped, as are descriptions ("formal tone")
    longer than a short phrase."""
    found: List[str] = []
    own = " " + " ".join(w.lower() for _, t in _samples_text(channel, "written") + _samples_text(channel, "spoken")
                         for w in _WORD_RE.findall(t)) + " "
    for source, text in (("notes", _read(_dir(channel, "notes.md"))), ("profile", _read(_dir(channel, "profile.md")))):
        for line in _NEVER_RE.findall(text):
            for item in re.split(r"[,;]", line):
                # `"dosto" (spell it "doston")` is the word, not the remark;
                # "see the last section" is a pointer, not a word.
                item = re.sub(r"\([^)]*\)?", "", item).strip().strip("\"'`*.“” ").lower()
                words = _WORD_RE.findall(item)
                if not item or not words or len(words) > 4 or item in found or words[0] == "see":
                    continue
                if source == "profile" and f" {' '.join(words)} " in own:
                    continue
                found.append(item)
    return found


# -------------------------------------------------------------- the profile

ANALYST_TASK = """Study how ONE creator writes and talks, from his own words below, and write
the style guide other writers will follow to sound exactly like him on the
{channel} channel.

Rules:
- Learn only from the samples. Quote him (short quotes, his exact words) as
  evidence for every point. Never invent a habit you cannot quote.
- "Transcribed from the recording" samples are speech-to-text and full of
  MISHEARD words: "hila doshton" is "Hello doston", "sar karte hain" is
  "shuru karte hain", "naam" where the script says "niyam" is the recogniser,
  not him. Learn his phrasing, rhythm, openings, how he addresses viewers,
  fillers and how he moves a story on -- but NEVER report a misspelling, an
  odd word or a wrong word from a transcript as his habit, and always quote
  transcripts in corrected spelling (what he actually said).
- The "script -> what he said" pairs show how he rewrites a writer's line when
  he says it aloud: these are the most precise evidence of his taste. Name
  the pattern (what he drops, adds, simplifies, reorders).
- Be concrete and checkable ("sentences of 4-10 words, one idea each"), never
  vague ("engaging tone").
- "Written by him" samples are the truth for layout, sentence length,
  paragraphs and point of view; where a transcript disagrees with them, the
  written samples win.
- His greeting is fixed: "{greeting}" Under "How he opens" give it first,
  word for word. A sample may open with another show's or host's name: that
  name is never his. Describe what he does after the greeting (the promise,
  the line that starts the story) and quote those lines without that name.

Write Markdown with exactly these headings:
## His voice in one paragraph
## Format and point of view
(how the script sits on the page -- continuous narration in paragraphs, or
cues and labels; chapter titles; who tells the story: "main" or "woh", which
tense; how dialogue is written)
## Sentence rhythm
## Hinglish: how he mixes Hindi and English
## Words and phrases he really uses
## How he speaks to the viewer
## How he opens
## How he tells a story and builds tension
## How he ends
## How he rewrites a writer's line
## Never
Under "## Never", the first line must be `Never use: word, word, ...` (words,
phrases or constructions that never appear in his writing but a model would
reach for), then bullets for anything else he never does.

### Measured numbers (from his samples)
{numbers}

### Script -> what he said instead (from his recordings)
{pairs}

### His samples
{samples}
"""


def _numbers_text(fp: Dict[str, Any]) -> str:
    keys = ("source", "words", "sentence_avg", "sentence_median", "short_share", "long_share",
            "paragraph_sentences", "english_share", "devanagari_share", "address_per_1000",
            "first_person_per_1000", "stage_share", "ellipsis_per_100", "question_per_100", "exclaim_per_100", "dialogue_per_100", "openers", "phrases")
    return "\n".join(f"- {k}: {fp[k]}" for k in keys if fp.get(k) not in (None, [], ""))


def _pairs_text(channel: str, limit: int) -> str:
    rows: List[str] = []
    for pairs in _load_rewrites(channel).values():
        for p in pairs[: max(1, limit // 3)]:
            rows.append(f"- script: \"{p['script']}\"\n  he said: \"{p['said']}\"")
    return "\n".join(rows[:limit]) or "(none yet)"


def _spread(text: str, room: int) -> str:
    """A long sample cut to `room` characters without losing how it opens or
    how it ends: its start, a passage from the middle and its end."""
    if len(text) <= room:
        return text
    head, mid, end = int(room * 0.45), int(room * 0.25), int(room * 0.28)
    middle = len(text) // 2 - mid // 2
    return (text[:head] + "\n[... cut ...]\n" + text[middle:middle + mid]
            + "\n[... cut ...]\n" + text[-end:])


def needs_rebuild(channel: str) -> bool:
    """His samples changed since the style guide was written (or there is none yet)."""
    channel = canonical_channel(channel)
    if not (_samples_text(channel, "written") or _samples_text(channel, "spoken")):
        return False
    return bool(_state(channel).get("stale")) or not _read(_dir(channel, "profile.md")).strip()


_BUILD_LOCK = threading.Lock()


def ensure_current(brand: str, project: Any = None, llm: Any = None) -> Optional[str]:
    """Before a writing step: rebuild a style guide that is older than his
    samples, so a sample added an hour ago is what the writer follows. Returns
    a line for the step's log, or None when nothing was due. Never raises: a
    guide that cannot be rebuilt is left out and his samples are quoted instead
    (`style_section`)."""
    try:
        if not uses_my_style(brand, project):
            return None
        channel = style_source(brand)
        if not needs_rebuild(channel):
            return None
        with _BUILD_LOCK:
            if not needs_rebuild(channel):
                return None
            try:
                view = build_profile(channel, llm)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Writing style: could not rebuild the %s guide (%s).", channel, exc)
                return (f"The creator's style guide for {channel} is older than his samples and could not be "
                        f"rebuilt ({exc}); writing from his samples directly.")
        kinds = Counter(s["kind"] for s in view.get("samples") or [])
        return (f"The creator's style guide for {channel} was rebuilt from his latest samples "
                f"({kinds.get('written', 0)} written, {kinds.get('spoken', 0)} recorded).")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Writing style: freshness check failed for %s (%s).", brand, exc)
        return None


def build_profile(channel: str, llm: Any = None) -> Dict[str, Any]:
    """Have StyleAnalyst write profile.md from every sample. Returns the state."""
    channel = canonical_channel(channel)
    written = _samples_text(channel, "written")
    spoken = _samples_text(channel, "spoken")
    if not written and not spoken:
        raise ValueError(f"No samples for {channel} yet: add some of your own writing, or learn from your recordings.")
    blocks, used = [], 0
    for kind, items in (("Written by him", written), ("Transcribed from the recording", spoken)):
        for name, text in items:
            room = ANALYST_SAMPLE_CHARS - used
            if room < 400:
                break
            piece = _spread(text, min(room, 9000 if kind.startswith("Written") else 4000))
            blocks.append(f"#### {kind}: {name}\n{piece}")
            used += len(piece)
    fp = measure(channel)
    task = ANALYST_TASK.format(channel=channel, numbers=_numbers_text(fp), greeting=greeting(channel),
                               pairs=_pairs_text(channel, 30), samples="\n\n".join(blocks))
    from core.agent import AgentFactory
    if llm is None:
        # The persona's tier decides the model (every tier is local since
        # 2026-10-21); the normal fallback order applies when it is down.
        from integrations.llm import LLMService
        llm = LLMService()
    profile = str(AgentFactory.get_agent("StyleAnalyst", llm).execute(task) or "").strip()
    profile = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", profile).strip()
    if "##" not in profile or len(profile) < 300:
        raise RuntimeError("The style analyst returned no usable profile; try again or use a stronger model.")
    stamp = time.strftime("%Y-%m-%d %H:%M")
    _write(_dir(channel, "profile.md"),
           f"<!-- Built {stamp} from {len(written)} written and {len(spoken)} recorded samples. "
           f"Edit freely; Rebuild replaces this file. Your own rules go in notes.md. -->\n\n{profile}\n")
    _write(_dir(channel, "fingerprint.json"), json.dumps(fp, ensure_ascii=False, indent=1))
    _write(_dir(channel, "state.json"), json.dumps(
        {**_state(channel), "stale": False, "built_at": stamp, "written": len(written), "spoken": len(spoken)},
        indent=1))
    return overview(channel)


def overview(channel: str) -> Dict[str, Any]:
    channel = canonical_channel(channel)
    state = _state(channel)
    return {
        "channel": channel,
        "samples": list_samples(channel),
        "profile": _read(_dir(channel, "profile.md")),
        "notes": _read(_dir(channel, "notes.md")),
        "fingerprint": targets(channel) if list_samples(channel) else {},
        "rewrites": sum(len(v) for v in _load_rewrites(channel).values()),
        "built_at": state.get("built_at"),
        "stale": bool(state.get("stale")) or not _read(_dir(channel, "profile.md")),
        "mode": channel_mode(channel),
        "story_standard": standard_on(channel),
        "has_standard": has_standard(channel),
        "style": active_style(channel),
        "styles": list_styles(channel),
    }


def save_text(channel: str, which: str, text: str) -> Dict[str, Any]:
    if which not in ("profile", "notes"):
        raise ValueError("Only the profile and your notes can be edited.")
    _write(_dir(channel, f"{which}.md"), (text or "").strip() + "\n")
    return overview(channel)


# -------------------------------------------------------------- the section

def _targets_text(fp: Dict[str, Any], devanagari: bool = False) -> List[str]:
    lines = []
    if fp.get("sentence_avg"):
        lines.append(f"- Sentences: about {fp['sentence_avg']:g} words on average (median {fp['sentence_median']}); "
                     f"{round(100 * fp.get('short_share', 0))}% are 6 words or fewer, "
                     f"{round(100 * fp.get('long_share', 0))}% run to 20 or more.")
    if fp.get("paragraph_sentences"):
        lines.append(f"- Paragraphs: about {fp['paragraph_sentences']:g} sentences each.")
    if fp.get("english_share") is not None:
        lines.append(f"- Language: of the Hindi/English everyday words, about {round(100 * fp['english_share'])}% are English.")
    if fp.get("devanagari_share") is not None:
        lines.append("- Script: " + ("Hindi in Devanagari (the channel's story standard is on; his samples are in Roman "
                                     "letters -- take their manner, not their script). His fixed greeting stays in "
                                     "Roman letters, word for word." if devanagari else
                                     "Hindi in Devanagari." if fp["devanagari_share"] > 0.3 else
                                     "Hinglish in Roman letters -- no Devanagari." if fp["devanagari_share"] < 0.05 else
                                     "mixed Roman and Devanagari, as in his samples."))
    rates = [(fp.get("ellipsis_per_100"), "'...' pauses"), (fp.get("question_per_100"), "questions"),
             (fp.get("exclaim_per_100"), "exclamations"), (fp.get("dialogue_per_100"), "quoted lines of dialogue")]
    rates = [f"{r:g} {label}" for r, label in rates if r is not None]
    if rates:
        lines.append(f"- Per 100 sentences: {', '.join(rates)}.")
    if fp.get("address_per_1000") is not None:
        lines.append(f"- Talks to the viewer ('aap', 'doston', ...) about {fp['address_per_1000']:g} times per 1000 words.")
    if fp.get("source") == "written" and (fp.get("first_person_per_1000") or 0) >= FIRST_PERSON_PER_1000:
        lines.append("- Point of view: first person. The story is told by the person it happened to "
                     f"('main', 'maine', 'mujhe', 'mere' about {fp['first_person_per_1000']:g} times per 1000 words), "
                     "never about a 'woh' seen from outside.")
    if fp.get("openers"):
        lines.append(f"- Sentences he often starts with: {', '.join(fp['openers'][:8])}.")
    if fp.get("phrases"):
        lines.append("- Phrases he really repeats: " + "; ".join(f"\"{p}\"" for p in fp["phrases"][:12]) + ".")
    return lines


def _excerpt(text: str, words: int = 150) -> str:
    """A passage from the middle of a sample (openings are shown apart)."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.split()) >= 25]
    if not paragraphs:
        return " ".join(text.split()[:words])
    middle = paragraphs[len(paragraphs) // 2: len(paragraphs) // 2 + 3]
    return " ".join(" ".join(middle).split()[:words])


def narration_format(brand: str, project: Any = None) -> bool:
    """True when the writing follows his style and his WRITTEN samples are
    continuous narration (no cue lines, no speaker labels): then a script is
    laid out the same way, not as a screenplay. A recording says nothing about
    layout, so a channel with recordings only keeps the cue format."""
    try:
        if not uses_my_style(brand, project):
            return False
        fp = targets(style_source(brand))
        return (fp.get("source") == "written" and fp.get("stage_share") is not None
                and fp["stage_share"] <= NARRATION_STAGE_SHARE)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Writing style: no format for %s (%s).", brand, exc)
        return False


def _format_text(fp: Dict[str, Any]) -> str:
    per = fp.get("paragraph_sentences")
    return (
        "#### Format -- lay the script out exactly as he does\n"
        "He writes continuous narration: full paragraphs told straight to the listener, the way a story is "
        "told aloud.\n"
        "- No screenplay layout: no [VISUAL] / [SOUND] / [MUSIC] cues, no speaker labels (NAME (V.O.), "
        "NARRATOR:), no sluglines, no (pause) / (slow) / (fast) marks, no bold, no bullet lists.\n"
        "- What is seen and heard is told in words inside the narration, never put in brackets.\n"
        "- What people say is told inside the narration, his way: Pawan ne kaha, \"...\".\n"
        + (f"- Paragraphs are long: about {per:g} sentences each, never one line per paragraph.\n" if per else "")
        + "- Every word is in Roman-script Hinglish; no English stage directions or descriptions.\n"
        "This layout overrides anything else in this prompt -- the task, your role, the channel guide -- that "
        "asks for cues, brackets, labels or pause marks."
    )


def rhythm_reminder(brand: str, project: Any = None) -> str:
    """His sentence rhythm in two or three lines, to sit next to the writing
    instruction itself: a small model follows the last thing it reads, and
    left alone it chains clauses into 20-word sentences. Empty in agent style
    or without written samples (a transcript's sentence breaks are not his)."""
    try:
        if not uses_my_style(brand, project):
            return ""
        channel = canonical_channel(brand)
        fp = targets(channel)
        if fp.get("source") != "written" or not fp.get("sentence_avg"):
            return ""
        parts = [f"His rhythm: sentences of about {fp['sentence_avg']:g} words -- about "
                 f"{round(100 * fp.get('short_share', 0))}% are 6 words or fewer and only "
                 f"{round(100 * fp.get('long_share', 0))}% run to 20 or more. One event or thought per sentence, "
                 "then a full stop; do not chain clauses with 'aur', 'lekin', 'toh', 'jaise', 'kyunki' or 'balki'."]
        if (fp.get("question_per_100") or 0) >= 2:
            parts.append(f"About {fp['question_per_100']:g} sentences in 100 are questions.")
        if (fp.get("address_per_1000") or 0) >= 2:
            parts.append(f"He turns to the viewer ('doston', 'aap') about {fp['address_per_1000']:g} times per 1000 words.")
        never = never_words(channel)
        if never:
            parts.append("Never use: " + ", ".join(never[:20]) + ".")
        return " ".join(parts)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Writing style: no rhythm reminder for %s (%s).", brand, exc)
        return ""


def format_override(brand: str, project: Any = None) -> str:
    """A reminder placed after the task description, which may itself ask for
    cues ("marking out long pauses and cues"). Empty unless he writes narration."""
    if not narration_format(brand, project):
        return ""
    return ("\n### Format (overrides the task above)\n"
            "Write continuous narration in the creator's own format (\"Format\" in his writing style above): "
            "full paragraphs in Hinglish told to the listener. No [VISUAL]/[SOUND] cues, no speaker labels, "
            "no (pause)/(slow) marks -- where the task above asks for cues or pause marks, his format wins.\n")


def style_section(brand: str, project: Any = None) -> str:
    """The block a writing step gets: how the creator writes, to match it.
    Empty when the channel (or `project`) is set to the agents' own style, or
    when there is nothing to learn from yet."""
    try:
        if not uses_my_style(brand, project):
            return ""
        own = canonical_channel(brand)
        channel = style_source(own)
        profile = re.sub(r"<!--.*?-->", "", _read(_dir(channel, "profile.md")), flags=re.S).strip()
        notes = _read(_dir(channel, "notes.md")).strip()
        written = _samples_text(channel, "written")
        spoken = _samples_text(channel, "spoken")
        if not (profile or notes or written or spoken):
            return ""
        state = _state(channel)
        if profile and state.get("stale") and len(written) > int(state.get("written") or 0):
            # The guide was written before his newest written samples and may
            # contradict them (it did: fragments and '...' against his long
            # sentences). Until it is rebuilt, his own words are quoted instead.
            profile = ""
        fp = targets(channel)
        show = spoken_channel_name(own)
        parts = [
            "### The Creator's Own Writing Style -- write the way he writes",
            f"Everything below is learned from the creator's own writing and recordings for {channel}. "
            "Match it closely: his rhythm, his words, his Hinglish, how he speaks to the viewer. It overrides "
            "any generic tone above. His fixed lines -- the greeting, the line that starts the story, his "
            "sign-off -- are used word for word. Everything else is manner only: never reuse a story line, "
            "time, place, character, object or image from his quoted examples; write this story's own.",
            "#### His greeting (fixed -- the first words of every full video, word for word, ONCE)\n"
            f"> {greeting(own)}\n"
            f"The host is {CREATOR_NAME} and the show is {show}. An example of his may carry another host's or "
            "show's name: never write that name, and never reword this greeting. It is said once, at the very "
            "start of the video, and never again: no second greeting, no re-introduction of the host, the show or "
            "the story, and no subscribe request inside the story. A section or part that is not the opening "
            "begins inside the story, with no greeting at all.",
        ]
        if channel != own:
            parts.insert(1, f"{own} has no samples of his own yet, so this is his style from {channel}: "
                            f"keep his manner, but write {own}'s own kind of story, not a {channel} episode.")
        if notes:
            parts.append(f"#### His own rules (follow exactly)\n{notes}")
        narration = (fp.get("source") == "written" and fp.get("stage_share") is not None
                     and fp["stage_share"] <= NARRATION_STAGE_SHARE)
        if narration:
            parts.append(_format_text(fp))
        target_lines = _targets_text(fp, devanagari=standard_on(own, project))
        if target_lines:
            parts.append("#### Measured from his writing -- land close to these\n" + "\n".join(target_lines))
        # Raw transcripts carry misheard words ("hila doshton"); once the
        # profile exists it quotes his openings in corrected spelling instead.
        # With written samples of his, a raw transcript adds only its mistakes.
        raw_ok = not profile and not written
        openings = [o for o in fp.get("openings") or [] if o] if raw_ok else []
        if openings:
            parts.append("#### How he opens his videos (from his recordings; spelling approximate)\n"
                         + "\n".join(f"> {o}" for o in openings[:2]))
        # Raw pairs can carry misheard words; the profile quotes them corrected.
        pairs = [p for ps in _load_rewrites(channel).values() for p in ps[:4]][:8] if raw_ok else []
        if pairs:
            parts.append("#### How he changes a writer's line when he says it\n"
                         + "\n".join(f"- script: \"{p['script'][:200]}\" -> he said: \"{p['said'][:200]}\"" for p in pairs))
        excerpts = [(n, _excerpt(t, 220 if profile else 320)) for n, t in written[:2]] or (
            [(n, _excerpt(t, 110)) for n, t in spoken[:1]] if not profile else [])
        if excerpts:
            parts.append("#### In his own words (match the manner, not the content)\n"
                         + "\n\n".join(f"> {e}" for _, e in excerpts if e))
        # Last, so that a long guide is what gets trimmed, not his own words.
        if profile:
            parts.append(f"#### Style guide\n{profile}")
        section = "\n\n".join(parts)
        if len(section) > SECTION_CHARS:
            section = section[:SECTION_CHARS].rsplit("\n", 1)[0] + "\n[... trimmed ...]"
        return "\n\n" + section + "\n"
    except Exception as exc:  # noqa: BLE001 - a broken store must not stop a step
        logger.warning("Writing style: no section for %s (%s).", brand, exc)
        return ""


# ---------------------------------------------------------------- the check

def _closeness_ratio(got: float, want: float) -> float:
    if not want or got <= 0:
        return 1.0 if not want else 0.0
    return max(0.0, 1.0 - abs(math.log(got / want)) / math.log(2.0))


def check(text: str, brand: str, originality: bool = True) -> Optional[Dict[str, Any]]:
    """How close a draft is to his measured style: a 0-100 score and what to
    change, in plain words. None when there is nothing to compare with.
    `originality` also marks down lines copied from his samples (off only
    when measuring one of his own samples against itself)."""
    channel = style_source(brand)
    fp = targets(channel)
    if not fp.get("words"):
        return None
    got = fingerprint(text)
    if got.get("words", 0) < 60:
        return None
    parts: List[Tuple[float, float]] = []
    fixes: List[str] = []
    # The story standard is written in Devanagari: the Roman word lists
    # (English share, address, first person, phrases) do not apply to it.
    standard = standard_on(brand)

    def add(weight: float, score: float, fix: Optional[str]) -> None:
        parts.append((weight, max(0.0, min(1.0, score))))
        if fix and score < 0.75:
            fixes.append(fix)

    if fp.get("sentence_avg") and got.get("sentence_avg"):
        s = _closeness_ratio(got["sentence_avg"], fp["sentence_avg"])
        longer = got["sentence_avg"] > fp["sentence_avg"]
        add(2.0, s, f"Sentences average {got['sentence_avg']:g} words; his average {fp['sentence_avg']:g}. "
                    + ("Break long sentences into short ones, one idea each." if longer else
                       "Let some sentences run on the way he does."))
    if fp.get("short_share") is not None and got.get("short_share") is not None:
        d = got["short_share"] - fp["short_share"]
        add(1.0, 1 - abs(d) / 0.3, f"{round(100 * got['short_share'])}% short sentences (6 words or fewer); "
                                   f"his is {round(100 * fp['short_share'])}%.")
    if not standard and fp.get("english_share") is not None and got.get("english_share") is not None:
        d = got["english_share"] - fp["english_share"]
        add(2.0, 1 - abs(d) / 0.25,
            f"About {round(100 * got['english_share'])}% English in the Hindi/English mix; his is "
            f"{round(100 * fp['english_share'])}%. " + ("Say more of it in everyday Hindi words, as he does."
                                                        if d > 0 else "He uses more everyday English words than this."))
    if fp.get("devanagari_share") is not None:
        want_dev = standard or fp["devanagari_share"] > 0.3
        has_dev = got.get("devanagari_share", 0) > (0.3 if want_dev else 0.05)
        ok = has_dev == want_dev
        add(2.0, 1.0 if ok else 0.0, None if ok else (
            "The story standard asks for Devanagari." if standard else
            "He writes Hindi in Devanagari." if want_dev else "He writes Hinglish in Roman letters: no Devanagari."))
    for key, weight, label in (("ellipsis_per_100", 0.5, "'...' pauses"), ("question_per_100", 0.5, "questions"),
                               ("exclaim_per_100", 0.3, "exclamations")):
        if fp.get(key) is not None and got.get(key) is not None:
            want, have = fp[key], got[key]
            add(weight, 1 - abs(have - want) / max(6.0, want),
                f"{have:g} {label} per 100 sentences; his is {want:g}.")
    if fp.get("address_per_1000") and not standard:
        want, have = fp["address_per_1000"], got.get("address_per_1000", 0)
        if want >= 2:
            add(1.0, min(1.0, have / (0.5 * want)) if have < want else 1 - min(1.0, (have - want) / (2 * want)),
                f"Talks to the viewer {have:g} times per 1000 words; he does about {want:g} ('aap', 'doston').")
    written = fp.get("source") == "written"
    # Layout: he writes narration, the draft is a screenplay. Counted only
    # when broken, so a clean layout earns no credit for a generic voice.
    if written and fp.get("stage_share") is not None and fp["stage_share"] <= NARRATION_STAGE_SHARE:
        staged = stage_share(text)
        if staged > NARRATION_STAGE_SHARE:
            add(3.0, 1 - min(1.0, staged / 0.10),
                f"{round(100 * staged)}% of the lines are stage directions ([VISUAL]/[SOUND] cues, speaker labels, "
                "(pause) marks). He writes continuous narration in full paragraphs: remove every cue, label and "
                "pause mark, and tell what is seen and heard in words inside the narration.")
        if fp.get("paragraph_sentences") and got.get("paragraph_sentences"):
            want, have = fp["paragraph_sentences"], got["paragraph_sentences"]
            if want >= 4 and have < 0.5 * want:
                add(1.0, _closeness_ratio(have, want),
                    f"Paragraphs run about {have:g} sentences; his run about {want:g}. Write full paragraphs, "
                    "not one line at a time.")
    if written and not standard and (fp.get("first_person_per_1000") or 0) >= FIRST_PERSON_PER_1000:
        want, have = fp["first_person_per_1000"], got.get("first_person_per_1000", 0)
        add(1.5, min(1.0, have / (0.5 * want)),
            f"First-person words ('main', 'maine', 'mujhe', 'mere') {have:g} per 1000; his is {want:g}. He tells "
            "the story as the person it happened to: 'main', never 'woh' seen from outside.")
    phrases = [] if standard else (fp.get("phrases") or [])
    if len(phrases) >= 3:
        low = " ".join(_WORD_RE.findall(text.lower()))
        used = [p for p in phrases if p in low]
        add(0.5, min(1.0, len(used) / 2.0),
            "None of his own phrases appear; use one or two where they fit naturally: "
            + "; ".join(f"\"{p}\"" for p in phrases[:6]) + ".")
    never = never_words(channel)
    if never:
        low = " " + " ".join(_WORD_RE.findall(text.lower())) + " "
        hit = [w for w in never if f" {' '.join(_WORD_RE.findall(w))} " in low]
        add(1.5, 0.0 if hit else 1.0, ("Uses words he never uses: " + ", ".join(hit) + ".") if hit else None)
    # The greeting is one line at the start: a draft that greets the viewer
    # again in the middle has copied the opening into the story.
    greetings = sum(1 for sent in _SENTENCE_SPLIT_RE.split(narration_text(text)) if _is_greeting(sent))
    if greetings > 1:
        add(2.0, 0.0, f"Greets the viewer {greetings} times; the greeting is said once, at the start, and never "
                      "again -- remove every later greeting, re-introduction and subscribe request.")
    # His examples are manner, not material: lines lifted from them are a
    # retelling of his story, not this one.
    copied, runs = sample_copy_ratio(text, channel) if originality else (0.0, [])
    if copied > 0.02:
        add(3.0, max(0.0, 1 - copied / 0.15),
            f"About {round(100 * copied)}% of the text is copied word for word from his examples (for instance "
            + "; ".join('"' + r + '"' for r in runs[:3]) + "). Write this story's own lines; his examples show "
            "the manner only.")
    if not parts:
        return None
    score = round(100.0 * sum(w * s for w, s in parts) / sum(w for w, _ in parts))
    return {"score": score, "fixes": fixes, "measured": got,
            "target": {k: v for k, v in fp.items() if k not in ("openings",)}}


REVISE_TASK = """Rewrite the script below so it reads exactly as the creator himself would
write it for {channel}. {keep} Change only the manner, using his style guide
above and these measured differences from his own writing:
{fixes}

His greeting and opening lines belong to the first words of the video only. If the script below
does not begin with his greeting, it is a middle or final part of a longer script: do not add the
greeting, a re-introduction of the host or the story, a subscribe request or a sign-off to it. If it
greets the viewer more than once, keep only the first.

Output the COMPLETE rewritten script as plain Markdown and nothing else.

### Script
{script}
"""

_KEEP_CUES = ("Keep everything it says: every scene, fact, name, line of dialogue, stage direction in "
              "[brackets], heading and its length (within 10%).")
_KEEP_NARRATION = ("Keep everything that happens: every event, fact, name, line of dialogue and heading, and at "
                   "least as many spoken words. Turn every stage direction, cue and speaker label into narration "
                   "(what is seen and heard, told in his words) or drop it: the result is continuous narration "
                   "in full paragraphs, with no brackets, labels or pause marks.")


def revise_task(brand: str, script: str, result: Dict[str, Any], project: Any = None) -> str:
    fixes = "\n".join(f"- {f}" for f in result.get("fixes") or []) or "- Match his rhythm and words more closely."
    return style_section(brand, project) + "\n\n" + REVISE_TASK.format(
        channel=canonical_channel(brand), fixes=fixes, script=script,
        keep=_KEEP_NARRATION if narration_format(brand, project) else _KEEP_CUES)


# --------------------------------------------------- machine-writing tells

#: "X, Y aur Z": a list of exactly three short items (one or two words each).
_TRIAD_ITEM = r"[^\s,.;:!?()\[\]\"]+(?: [^\s,.;:!?()\[\]\"]+)?"
_TRIAD_RE = re.compile(
    rf"(?<![\w,])({_TRIAD_ITEM}), ({_TRIAD_ITEM}),? (?:aur|and|or|ya|tatha|और|या|तथा) ([^\s,.;:!?()\[\]\"]+)",
    re.IGNORECASE)
_CONTRAST_RES = (
    re.compile(r"\bnot (?:just |only |merely |simply )?[^.!?\n,]{1,40},? but\b", re.IGNORECASE),
    re.compile(r"\b(?:sirf|keval|kewal)\b[^.!?\n]{1,60}?\bnahi+n?\b(?:\s+(?:hai|hain|tha|thi|the|ho))?,?\s*"
               r"(?:balki|bulki|balke)\b", re.IGNORECASE),
    re.compile(r"(?:सिर्फ|केवल)[^.!?।\n]{1,60}?नहीं(?:\s+(?:है|हैं|था|थी|थे))?,?\s*बल्कि"),
)
_TRANSITION_RES = (
    re.compile(r"\b(?:moreover|furthermore|additionally|ultimately|nevertheless|in conclusion|in summary|"
               r"to sum up|on the other hand|all in all)\b", re.IGNORECASE),
    re.compile(r"\bek taraf\b[^.!?\n]{0,200}?\b(?:doosri|dusri|duusri) taraf\b", re.IGNORECASE),
    re.compile(r"एक तरफ[^।.!?\n]{0,200}?दूसरी तरफ"),
    re.compile(r"\b(?:antatah|nishkarsh)\b|अंततः|निष्कर्ष", re.IGNORECASE),
)
_TAIL_RES = (
    re.compile(r",\s*which means\b|\bthis means that\b|\bwhich is to say\b", re.IGNORECASE),
    re.compile(r"\bya{1,2}ni\b(?: k[ie]\b)?|\bjiska matlab (?:hai|tha)\b|यानी|यानि|जिसका मतलब", re.IGNORECASE),
)
_HEDGE_RES = (
    re.compile(r"\bit(?: is|'s) (?:important|worth|interesting) to (?:note|mention|remember)\b|"
               r"\bit is worth noting\b|\bit should be noted\b|\bneedless to say\b|\barguably\b|"
               r"\bin many ways\b", re.IGNORECASE),
    re.compile(r"\bdhyan dene yogya\b|\bgaur karne (?:wali|waali) baat\b|\bkehna galat nahi(?:n)? hoga\b|"
               r"\byeh kehna (?:uchit|sahi) hoga\b", re.IGNORECASE),
    re.compile(r"यह ध्यान देने योग्य है|ध्यान देने योग्य|गौर करने वाली बात|कहना गलत नहीं होगा"),
)
_MORAL_RES = (
    re.compile(r"\b(?:ye|yeh|is|iss) kahani (?:humein|hume|hamein|hame|hum(?:e|ein)?) "
               r"(?:sikhati|sikhaati|batati|batlati) hai\b|\bis kahani se (?:humein|hume|hamein) [^.!?\n]{0,40}"
               r"(?:seekh|sikh|sabak)|\bthe moral of\b|\bthis story teaches\b|\bthe lesson (?:here )?is\b",
               re.IGNORECASE),
    re.compile(r"यह कहानी (?:हमें )?सिखाती है|इस कहानी से (?:हमें )?(?:सीख|सबक)"),
)
_EM_DASH_RE = re.compile(r"—|–| -- ")
_CONTRACTION_RE = re.compile(r"\b\w+(?:n't|'s|'re|'ll|'m|'ve|'d)\b", re.IGNORECASE)
_ENGLISH_FUNCTION_WORDS = frozenset("the is was are were of to and that it this with for".split())

#: Each tell's weight in the 0-100 score, and the rate per 1,000 words at
#: which it counts in full (a rate of 0 means "present or not").
_TELL_WEIGHTS = {
    "triad": (15, 6.0), "contrast": (10, 3.0), "stock_transition": (10, 4.0),
    "over_explaining": (10, 4.0), "uniform_length": (15, 0), "no_fragments": (10, 0),
    "no_contractions": (5, 0), "hedge": (10, 2.0), "em_dash": (5, 8.0), "closing_moral": (10, 0),
}


def _tell_matches(text: str, patterns) -> List[str]:
    found: List[str] = []
    for pattern in patterns:
        found.extend(m.group(0).strip() for m in pattern.finditer(text))
    return found


def ai_tells(text: str) -> Dict[str, Any]:
    """How much a script reads like a machine wrote it, measured with regexes
    and simple statistics: 0 = reads human, 100 = machine. Rates are per 1,000
    spoken words. `tells` lists each tell that fired: {kind, count, examples}."""
    spoken = narration_text(text or "")
    words = _WORD_RE.findall(spoken)
    n_words = len(words)
    if not n_words:
        return {"score": 0, "tells": []}
    per_k = 1000.0 / max(n_words, 100)        # a short text is not judged on one hit
    found: Dict[str, Tuple[int, List[str], float]] = {}  # kind -> (count, examples, strength 0-1)

    def rate_tell(kind: str, hits: List[str]) -> None:
        if not hits:
            return
        _, full = _TELL_WEIGHTS[kind]
        strength = min(1.0, len(hits) * per_k / full) if full else 1.0
        found[kind] = (len(hits), hits[:3], strength)

    triads = []
    for m in _TRIAD_RE.finditer(spoken):
        before = spoken[:m.start()].rstrip()
        if not before.endswith(","):          # exactly three, not the tail of a longer list
            triads.append(m.group(0))
    rate_tell("triad", triads)
    rate_tell("contrast", _tell_matches(spoken, _CONTRAST_RES))
    rate_tell("stock_transition", _tell_matches(spoken, _TRANSITION_RES))
    rate_tell("over_explaining", _tell_matches(spoken, _TAIL_RES))
    rate_tell("hedge", _tell_matches(spoken, _HEDGE_RES))
    rate_tell("em_dash", [m.group(0) for m in _EM_DASH_RE.finditer(spoken)])
    rate_tell("closing_moral", _tell_matches(spoken, _MORAL_RES))

    sentences = [s for s in _sentences(spoken)]
    if len(sentences) >= 5:
        lengths = [len(s) for s in sentences]
        mean = sum(lengths) / len(lengths)
        cv = math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths)) / mean if mean else 0.0
        if cv < 0.5:
            strength = 1.0 if cv < 0.35 else (0.5 - cv) / 0.15
            found["uniform_length"] = (len(sentences), [f"sentence length varies little (cv {cv:.2f})"]
                                       + [" ".join(s) for s in sentences[:2]], strength)
        if not any(x < 4 for x in lengths):
            found["no_fragments"] = (len(sentences), [f"0 of {len(sentences)} sentences under 4 words"], 1.0)
    lowered = [w.lower() for w in words]
    english = sum(1 for w in lowered if w in _ENGLISH_FUNCTION_WORDS)
    if n_words >= 80 and english / n_words > 0.15 and not _CONTRACTION_RE.search(spoken):
        found["no_contractions"] = (0, ["English sentences without a single contraction"], 1.0)

    score = sum(_TELL_WEIGHTS[kind][0] * strength for kind, (_, _, strength) in found.items())
    tells = [{"kind": kind, "count": count, "examples": examples}
             for kind, (count, examples, _) in found.items()]
    return {"score": int(round(min(100.0, score))), "tells": tells}
