"""
The "story" visual style: pictures and videos only, told calmly, with the
same characters in every shot.

Set per channel (`visual_style` in `buzzedit_settings.py`; Raat3Baje,
Khayal3Baje and Beyond3Baje by default since 2026-10-02). The render switches
there turn BuzzEdit's own captions, cards, text effects, sound effects and mood
hits off -- but BuzzEdit renders every directive in the script it is handed
whatever those switches say (a `# heading` becomes a chapter-title card, a
`[statement: ...]` a text card), and it never promotes a script's `[broll:]`
still to a `[video:]` clip (`shotplan.balance_video_share` only moves beats its
own model planned). So for this style the Studio does both itself, on the
finished directive script (`apply_to_script`):

1. every directive except `[broll:]`, `[video:]`, `[music:]` and `[sfx:]` (the
   scene's own sounds), and every `# heading` line, is removed;
2. every picture of a character from the cast sheet carries that character's
   fixed look, and every picture the story's world, so the image model draws
   the same people in the same place from shot to shot;
3. stills are turned into clips, spread evenly through the video, until clips
   make up `video_broll_share` of the pictures;
4. every shot whose visible subject is the story's main character is marked
   `face=main`, and BuzzEdit swaps that one character's reference face into
   it (ReActor). Nobody else's shot is marked, so another character, a crowd
   or a back view keeps its own face; with several people in a marked shot
   the main character is put nearest, since only the largest face is swapped.

The cast sheet (`production/cast_sheet.json`) is written once per project by
the CharacterPlanner from the script; edit it by hand to fix a look, and the
next render uses the edit.

Each character may also carry a `voice` ({voice, preset, match_pitch,
pitch_shift, steps}, BuzzEdit VOICE_CHANGER_PLAN.md brief S3): BuzzEdit
converts that character's labelled lines to a voice from its library before
the render, and the creator's narration stays his own. `propose_voices` fills
it from the character's description (woman, child, creature, the dead, man),
only with voices BuzzEdit's library has; the Projects page changes it.
"""

from __future__ import annotations

import bisect
import json
import logging
import math
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from integrations.script_reconcile import LABEL_LINE_RE, speaker_key, speaker_name

logger = logging.getLogger("buzzcaf_ai.story_visuals")

#: Directive kinds the story style keeps. Music is a bed, not an edit, and a
#: sound cue is the scene's own sound (footsteps, rain), not a transition hit.
KEPT_DIRECTIVES = ("broll", "video", "music", "sfx")
#: Kept directives that are not pictures: passed through as they are.
_AS_WRITTEN = ("music", "sfx")
#: Plan beat kinds the story style keeps (the planner-side names of the above).
KEPT_BEAT_KINDS = ("broll_image", "broll_video", "music_cue", "sfx_cue")

CAST_SHEET_ASSET = "production/cast_sheet.json"

#: What every clip's motion should feel like: slow and steady, never a whip.
#: No "camera" in it: BuzzEdit draws a `[video:]` clip's first frame from the
#: same text, and the still model drew a DSLR into every shot (2026-10-03).
CALM_MOTION = ("slow steady cinematic motion, calm and eerie, subtle natural movement, "
               "no fast motion, no shaking")

_DIRECTIVE_RE = re.compile(r"\[\s*([a-z_]+)\s*:\s*([^\]]*?)\s*\]\s?", re.IGNORECASE)
_HEADING_LINE_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+.*(?:\r?\n|$)", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_SPACE_RUN_RE = re.compile(r"[ \t]{2,}")

#: Longest script excerpt the cast-sheet call reads. Characters are named
#: and described early in a story; the rest only costs tokens.
_CAST_SOURCE_CHARS = 24000


# ------------------------------------------------------------------ prompt

def planner_section(share: float, cast: Optional[Dict[str, Any]] = None) -> str:
    """The planner instructions that replace the effect catalog for a story
    channel: which kinds exist, how many clips, and how the shots hang
    together."""
    pct = int(round(max(0.0, min(1.0, share)) * 100))
    lines = [
        "### Story visuals -- pictures and videos only",
        "This channel tells a story with pictures and moving clips and nothing else on "
        "screen: no cards, captions or pop-ups. Sound is welcome: the window's `sounds` "
        "(footsteps, a door, rain, a shout -- what the scene would really sound like) are "
        "placed under the voice, so write them. Use ONLY these picture kinds:",
        "- **broll_image** -- a still picture. Needs `image_prompt`.",
        "- **broll_video** -- a short moving clip (animated from a still of the same "
        "scene). Needs `video_prompt` (the scene and its slow motion) and `image_prompt` "
        "(the same scene as a still).",
        "- **music_cue** -- only where the music should change.",
        "No text on screen, no captions, cards, headings, chapter titles, newspapers, "
        "case files, maps, charts, documents, fx, atmos or grade beats -- they are removed "
        "before the render.",
        f"About {pct}% of the pictures should be `broll_video`; choose the moments where "
        "something moves: a door easing open, a figure walking away, fog crossing a road, "
        "a lantern swinging.",
        "Shots follow the story in order, like a film's storyboard: each picture is the "
        "next moment of what the narrator is describing, in the same place and the same "
        "night as the shot before it, until the story itself moves on. Never cut to a "
        "generic or unrelated image, a real news photo, or a documentary/stock look.",
        "Same characters in every shot: whenever a character is on screen, describe them "
        "with exactly the look given in the cast below (same face, age, hair and "
        "clothes), never a new description.",
        "Calm and scary, not rushed: slow, steady framing; long, quiet shots; "
        "darkness, shadow, mist and stillness carry the dread. No flashes, shaking, "
        "glitches or busy montage.",
        "No camera is ever seen: describe only what is in the picture, never the camera "
        "filming it. Never write the words camera, DSLR, lens, tripod, photographer or "
        "film crew in `image_prompt` or `video_prompt` -- the image model draws whatever "
        "is named, so \"the camera pans across the corridor\" puts a camera in the shot. "
        "Write the motion as the movement itself: \"slow pan across the corridor\", "
        "\"slow push toward the door\", \"close view of his trembling hands\". A camera "
        "appears only when the story itself is about one (a CCTV camera on the wall).",
        "`image_prompt` and `video_prompt` are always written in English.",
    ]
    cast_block = cast_prompt_block(cast)
    if cast_block:
        lines.append(cast_block)
    face_block = main_face_section(cast)
    if face_block:
        lines.append(face_block)
    try:
        from integrations import music_catalog
        lines.append(music_catalog.prompt_section())
    except Exception:  # noqa: BLE001 - planning runs without the music menu
        pass
    return "\n".join(lines)


def cast_prompt_block(cast: Optional[Dict[str, Any]]) -> str:
    if not cast:
        return ""
    lines = ["### Cast and world (use these looks word for word)"]
    if cast.get("world"):
        lines.append(f"World: {cast['world']}")
    main = main_character(cast)
    for person in cast.get("characters") or []:
        if isinstance(person, dict) and person.get("name") and person.get("look"):
            tag = " (MAIN CHARACTER)" if person is main else ""
            lines.append(f"- {person['name']}{tag}: {person['look']}")
    return "\n".join(lines) if len(lines) > 1 else ""


def main_face_section(cast: Optional[Dict[str, Any]]) -> str:
    """How the planner marks the shots that get the main character's face.
    BuzzEdit swaps one reference face into each marked shot, and only into
    the largest face in the frame, so the mark has to be exact."""
    main = main_character(cast)
    if main is None:
        return ""
    name = main["name"]
    return "\n".join([
        f"### {name}'s face (one face in every shot of {name})",
        f"Every picture of {name} gets the same face, swapped in after the picture is drawn. "
        f"On each broll_image and broll_video beat add `\"main_face\": true` ONLY when {name} "
        f"is in the shot, face clearly visible, and is the nearest, largest face in the picture. "
        f"Write {name}'s look from the cast in that beat's prompts, never the name alone.",
        f"`\"main_face\": false` for every other shot: another character on their own, a crowd, "
        f"a place, an object, {name}'s hands, back, silhouette or shadow, or {name} far away. "
        f"A wrong true puts {name}'s face on someone else.",
        f"When {name} shares a shot with anyone else, {name} is in the foreground, nearest and "
        f"largest; the others stand further back, smaller. Only {name}'s face is swapped; every "
        f"other character keeps the look the cast gives them and never gets {name}'s look.",
    ])


# -------------------------------------------------------------- cast sheet

CAST_PROMPT = """Read this story and write its visual cast sheet: what an image \
model must be told so every picture of the video shows the same people in the \
same world.

Reply with a single JSON object and nothing else:
{{"world": "one English line of what the camera sees in EVERY frame of this story: season, time of \
day, weather, light, colour palette, and the textures of the place (vegetation, walls, roads). Never \
name animals or creatures, people, or named parks, reserves, cities or brands — a creature named here \
would be drawn into every picture.",
  "main_character": "the name of the ONE character the story follows, or \\"\\"",
  "characters": [
    {{"name": "the name used in the story",
      "aliases": ["other words the story uses for them, e.g. the guard, the old woman"],
      "gender": "male, female or \\"\\"",
      "look": "one English line: apparent age, gender, build, face, hair, clothing and one \
distinctive detail -- concrete and visual, no personality, no names"}}
  ]}}

Only characters who would appear on screen (the narrator only if they are in \
the story). A ghost or creature gets a look too, kept vague but fixed (e.g. "a \
tall thin figure in a wet white sari, face always hidden by long black hair"). \
At most 8 characters.

{main_rules}

{bible}Story:
{story}
"""

#: Who BuzzEdit gives one fixed face. Its ReActor pass swaps a reference face
#: into every shot tagged as showing that person, so a wrong pick is worse
#: than none: a creature would get a man's face, a real person a stranger's.
MAIN_RULES = """main_character is the one person the pictures keep coming back to: \
the protagonist (in a first-person story, the narrator as they appear in it). \
Leave it "" when the story has no single lead (several equal characters, a list \
of separate rules or incidents with different people, a place or an event), \
when the lead's face is never seen (a ghost, a creature, a voice, a hidden \
figure), or when the lead is a real, identifiable public person."""

MAIN_PROMPT = """This is the visual cast sheet of a story, and the story. Pick \
the story's main character for it.

{main_rules}

Reply with a single JSON object and nothing else:
{{"main_character": "a name exactly as it appears in the cast sheet, or \\"\\"",
  "gender": "male, female or \\"\\""}}

Cast sheet:
{cast}

Story:
{story}
"""

_GENDERS = {"male": "male", "man": "male", "m": "male", "boy": "male",
            "female": "female", "woman": "female", "f": "female", "girl": "female"}
#: Words too common to tie a picture to one person ("he walks in").
_PRONOUNS = {"he", "him", "his", "she", "her", "hers", "they", "them", "the man", "the woman",
             "man", "woman", "i", "me", "narrator", "the narrator", "main"}

#: Creatures a world or look line must never carry into every picture: the
#: ep2 world line named a "tiger reserve" and 421 of its 461 image prompts said
#: "tiger" (CLIPS_AND_SOUND_PLAN.md, F1). A beat that names its own animal
#: keeps it.
CREATURE_WORDS: Tuple[str, ...] = (
    "tiger", "tigers", "leopard", "lion", "elephant", "bear", "wolf", "snake", "deer",
    "panther", "cheetah", "crocodile", "monkey", "jackal", "hyena", "buffalo", "bull", "horse",
    "dog", "cat", "bird", "eagle", "vulture", "owl", "bat",
    "बाघ", "शेर", "हाथी", "भालू", "साँप",
)
#: A word character, Devanagari vowel signs included (`\w` alone stops at them).
_WORD_CHARS = r"\w\u0900-\u097f"
_CREATURE_RE = re.compile(
    rf"(?<![{_WORD_CHARS}])(?P<word>"
    + "|".join(re.escape(w) for w in sorted(CREATURE_WORDS, key=len, reverse=True))
    + rf")(?![{_WORD_CHARS}])"
    rf"(?P<place>[\s-]+(?:national[\s-]+park|reserve|sanctuary|park)(?![{_WORD_CHARS}]))?",
    re.IGNORECASE)
_FOREST_NEXT_RE = re.compile(r"\s*forests?\b", re.IGNORECASE)


def _tidy(text: str) -> str:
    """`text` after words were cut out of it: single spaces, no space before
    punctuation, no doubled commas, no comma at either end."""
    text = " ".join(text.split())
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,;])(?:\s*[,;])+", r"\1", text)
    return text.strip(" ,;")


def _creatures_in(text: str) -> set:
    return {m.group("word").lower() for m in _CREATURE_RE.finditer(text or "")}


def _strip_creatures(text: str, keep: Optional[set] = None) -> str:
    """`text` without the creature words `keep` does not hold; a creature's
    reserve, sanctuary or park becomes plain "forest". Returned untouched
    when there is nothing to cut."""
    keep = keep or set()

    def cut(m: "re.Match[str]") -> str:
        if m.group("word").lower() in keep:
            return m.group(0)
        if m.group("place") and not _FOREST_NEXT_RE.match(text, m.end()):
            return "forest"
        return ""

    out = _CREATURE_RE.sub(cut, text)
    return text if out == text else _tidy(out)


def visual_world(line: str) -> str:
    """The cast sheet's world line as a look only: it is appended to every
    picture, so a creature named in it is drawn into every shot. Creature
    words go ("a dense, remote tiger reserve" -> "a dense, remote forest");
    at most 300 characters."""
    text = " ".join(unicodedata.normalize("NFC", str(line or "")).split())
    return _strip_creatures(text)[:300]


def _bible_text(project: Any) -> str:
    """The long-script story bible, when the script was written in sections."""
    try:
        root = os.path.join(project.get_project_dir(), "script", "sections")
        for dirpath, _, files in os.walk(root):
            if "plan.json" in files:
                with open(os.path.join(dirpath, "plan.json"), "r", encoding="utf-8") as f:
                    bible = (json.load(f) or {}).get("bible")
                if bible:
                    return "Story bible:\n" + json.dumps(bible, ensure_ascii=False)[:6000] + "\n\n"
    except Exception:  # noqa: BLE001
        pass
    return ""


def _clean_cast(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    characters = []
    for person in data.get("characters") or []:
        if not isinstance(person, dict):
            continue
        name = " ".join(str(person.get("name") or "").split())
        look = " ".join(str(person.get("look") or "").split()).replace("]", ")")
        if not name or not look:
            continue
        aliases = [" ".join(str(a).split()) for a in (person.get("aliases") or [])
                   if str(a).strip() and " ".join(str(a).split()).lower() not in _PRONOUNS]
        entry = {"name": name, "aliases": aliases[:6], "look": look[:300]}
        gender = _GENDERS.get(str(person.get("gender") or "").strip().lower())
        if gender:
            entry["gender"] = gender
        if "voice" in person:
            # Present means decided (None = the creator's own voice); absent
            # means never proposed, which a production proposes once.
            entry["voice"] = _clean_voice(person.get("voice"))
        characters.append(entry)
    world = " ".join(str(data.get("world") or "").split()).replace("]", ")")[:300]
    cast: Dict[str, Any] = {"world": world, "characters": characters[:8]}
    if "main_character" in data:
        # Present means decided ("" = no lead); absent means a sheet written
        # before the face swap, which ensure_cast_sheet asks about once.
        wanted = " ".join(str(data.get("main_character") or "").split()).lower()
        cast["main_character"] = next((p["name"] for p in cast["characters"]
                                       if wanted and p["name"].lower() == wanted), "")
    return cast


# --------------------------------------------------------- cast voices

#: The fields of a character's `voice` -- one entry of BuzzEdit's project
#: `voice_map` (routes/audio_voice.py): a library voice, a preset (Woman,
#: Child, Demon, Monster, Ghost), "Match my pitch contour", semitones, steps.
VOICE_KEYS = ("voice", "preset", "match_pitch", "pitch_shift", "steps")
#: The preset each kind of character is voiced with (BuzzEdit's presets.json).
KIND_PRESETS = {"woman": "Woman", "child": "Child", "demon": "Demon", "monster": "Monster", "ghost": "Ghost"}
#: Words in a library voice's name or kind that fit a kind of character, for
#: when the preset's own reference clip is not in the library.
_LIBRARY_WORDS = {
    "woman": ("woman", "women", "female", "lady"),
    "child": ("child", "kid", "boy", "girl"),
    "demon": ("demon", "monster", "creature", "beast", "devil"),
    "monster": ("monster", "demon", "creature", "beast"),
    "ghost": ("ghost", "spirit"),
    "man": ("man", "men", "male", "guy", "gentleman", "father", "husband"),
}
_MONSTER_RE = re.compile(r"\b(?:monsters?|monstrous|beasts?|creatures?|werewol(?:f|ves)|ogres?|trolls?)\b", re.I)
#: A demon's own words win over a generic "creature" ("a rakshas, a hunched creature").
_DEMON_RE = re.compile(
    r"\b(?:demons?|demonic|devils?|satan|shaitaa?n|rakshas[ai]?|rakshasas|brahmarakshas|pishach\w*|"
    r"daityas?|asuras?|jinns?|djinns?|vet[a]{1,2}l|bet[a]{1,2}l)\b", re.I)
_GHOST_RE = re.compile(
    r"\b(?:ghosts?|ghostly|spirits?|dead(?![-\s]?(?:eyed|pan|line))|undead|corpses?|phantoms?|wraiths?|"
    r"apparitions?|spect(?:re|er)s?|bhoot\w*|bhut|chudail|churail|daayan|dayan|aatma|atma|pret|preta)\b", re.I)
_CHILD_RE = re.compile(
    r"\b(?:child|children|kids?|boys?|girls?|toddlers?|baby|babies|infants?|schoolboy|schoolgirl|"
    r"bachch?[ai]|bacch?[ai])\b", re.I)
_FEMALE_RE = re.compile(
    r"\b(?:woman|women|female|lady|ladies|girls?|she|her|hers|mother|wife|daughter|sister|grandmother|aunt|"
    r"widow|bride|queen|maa|nani|dadi|mausi|chachi|aurat|mahila|ladki|didi)\b", re.I)
_MALE_RE = re.compile(
    r"\b(?:man|men|male|gentleman|boys?|he|him|his|father|husband|son|brother|grandfather|uncle|king|"
    r"priest|baba|dada|nana|chacha|bhaiya|ladka|aadmi)\b", re.I)
_ADULT_RE = re.compile(r"\b(?:teen\w*|adult|young (?:woman|man|lady)|grown|college|elderly|old (?:woman|man))\b",
                       re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
_DECADES = {"twenties": 20, "thirties": 30, "forties": 40, "fifties": 50, "sixties": 60, "seventies": 70,
            "eighties": 80, "nineties": 90}
_AGE_NUMBER = r"(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")"
_YEARS_OLD_RE = re.compile(r"\b" + _AGE_NUMBER + r"[\s-]*(?:years?|yrs?)(?:[\s-]*old)?\b", re.I)
_AGED_RE = re.compile(r"\b(?:aged?|of about|of around|about|around|roughly|nearly)\s+" + _AGE_NUMBER
                      + r"\b(?![\s-]*(?:m|cm|ft|feet|foot|metres?|meters?|inch\w*|kg|kilos?|minutes?|hours?)\b)",
                      re.I)
_DECADE_RE = re.compile(r"\b(?:(" + "|".join(_DECADES) + r")|(\d)0s)\b", re.I)


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clean_voice(raw: Any) -> Optional[Dict[str, Any]]:
    """A character's `voice` as stored, or None (no conversion: the creator's
    own voice). A preset alone is kept (BuzzEdit then uses its reference)."""
    if not isinstance(raw, dict):
        return None
    voice = " ".join(str(raw.get("voice") or "").split())[:80]
    preset = " ".join(str(raw.get("preset") or "").split())[:40]
    if preset.lower() == "custom":
        preset = ""
    if not voice and not preset:
        return None
    return {"voice": voice or None, "preset": preset or None,
            "match_pitch": bool(raw.get("match_pitch")),
            "pitch_shift": _clamp_int(raw.get("pitch_shift"), 0, -12, 12),
            "steps": _clamp_int(raw.get("steps"), 25, 10, 50)}


def character_names(cast: Optional[Dict[str, Any]]) -> List[str]:
    """The cast's character names: the speakers whose `NAME:` lines are their
    dialogue (`script_reconcile`)."""
    return [str(p["name"]) for p in (cast or {}).get("characters") or []
            if isinstance(p, dict) and p.get("name")]


def voices_decided(cast: Optional[Dict[str, Any]]) -> bool:
    """Whether the cast's voices were ever proposed or set: a character with a
    `voice` field (None counts -- the creator's own voice was chosen)."""
    return any(isinstance(p, dict) and "voice" in p for p in (cast or {}).get("characters") or [])


def _age_value(token: str) -> Optional[int]:
    token = token.lower()
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token)


def _apparent_age(text: str) -> Optional[int]:
    """The age a character's description gives ("an 8-year-old boy", "a girl
    of about eight", "a woman in her thirties"), or None."""
    for regex in (_YEARS_OLD_RE, _AGED_RE):
        m = regex.search(text)
        if m:
            age = _age_value(m.group(1))
            if age is not None and 0 < age < 120:
                return age
    m = _DECADE_RE.search(text)
    if m:
        return _DECADES[m.group(1).lower()] if m.group(1) else int(m.group(2)) * 10
    return None


def voice_kind(person: Dict[str, Any]) -> Optional[str]:
    """What a character sounds like, from their name, aliases, gender and look:
    "monster", "demon", "ghost", "child", "woman", "man", or None."""
    text = " ".join([str(person.get("name") or ""), " ".join(str(a) for a in person.get("aliases") or []),
                     str(person.get("look") or "")])
    if _DEMON_RE.search(text):
        return "demon"
    if _MONSTER_RE.search(text):
        return "monster"
    if _GHOST_RE.search(text):
        return "ghost"
    age = _apparent_age(text)
    if (age is not None and age < 13) or (age is None and _CHILD_RE.search(text) and not _ADULT_RE.search(text)):
        return "child"
    gender = person.get("gender")
    if gender == "female":
        return "woman"
    if gender == "male":
        return "man"
    female, male = len(_FEMALE_RE.findall(text)), len(_MALE_RE.findall(text))
    if female > male:
        return "woman"
    if male > female:
        return "man"
    return None


def _voice_names(voices: Any) -> List[Dict[str, str]]:
    """BuzzEdit's library (`GET /api/audio/voices`) as [{name, kind}]."""
    if isinstance(voices, dict):
        voices = voices.get("voices")
    out = []
    for v in voices or []:
        if isinstance(v, dict) and str(v.get("name") or "").strip():
            out.append({"name": str(v["name"]).strip(), "kind": str(v.get("kind") or "")})
        elif isinstance(v, str) and v.strip():
            out.append({"name": v.strip(), "kind": ""})
    return out


def _preset_table(presets: Any) -> Dict[str, Dict[str, Any]]:
    """BuzzEdit's presets (`GET /api/audio/voice/presets`) as {name: preset}."""
    if isinstance(presets, dict) and isinstance(presets.get("presets"), dict):
        presets = presets["presets"]
    return {str(k): v for k, v in (presets or {}).items() if isinstance(v, dict)} if isinstance(presets, dict) else {}


def _library_voice(kind: str, preset: Optional[Dict[str, Any]], library: List[Dict[str, str]]) -> Optional[str]:
    """The library voice for a kind of character: the preset's own reference
    when the library has it, else a voice whose name or kind fits."""
    stem = str((preset or {}).get("voice") or "").strip().casefold()
    if stem:
        found = next((v["name"] for v in library if v["name"].casefold() == stem), None)
        if found:
            return found
    words = set(_LIBRARY_WORDS.get(kind, ()))
    for v in library:
        tokens = set(re.split(r"[^a-z]+", f"{v['name']} {v['kind']}".lower()))
        if words & tokens:
            return v["name"]
    return None


def propose_voices(cast: Optional[Dict[str, Any]], voices: Any, presets: Any) -> Dict[str, Any]:
    """The cast with every character's `voice` proposed from their description:
    a woman gets the Woman preset, a child Child, a creature Demon or Monster,
    the dead Ghost, a man a male voice from the library -- but only with a
    voice BuzzEdit's library has (`voices`, `GET /api/audio/voices`); without
    one the character's `voice` is None (the creator's own). `presets` is
    `GET /api/audio/voice/presets` (their parameter values)."""
    cast = dict(cast or {})
    library = _voice_names(voices)
    table = _preset_table(presets)
    defaults = presets.get("engine_defaults") if isinstance(presets, dict) else None
    defaults = defaults if isinstance(defaults, dict) else {}
    characters = []
    for person in cast.get("characters") or []:
        if not isinstance(person, dict):
            continue
        kind = voice_kind(person)
        entry: Optional[Dict[str, Any]] = None
        if kind and library:
            preset_name = KIND_PRESETS.get(kind)
            preset = table.get(preset_name) if preset_name else None
            voice = _library_voice(kind, preset, library)
            if voice:
                params = preset.get("params") if preset and isinstance(preset.get("params"), dict) else {}
                entry = _clean_voice({
                    "voice": voice, "preset": preset_name if preset else None,
                    "match_pitch": params.get("match_pitch", defaults.get("f0_condition", False)),
                    "pitch_shift": params.get("pitch_shift", defaults.get("pitch_shift", 0)),
                    "steps": params.get("steps", defaults.get("diffusion_steps", 25))})
        characters.append(dict(person, voice=entry))
    cast["characters"] = characters
    return cast


def set_character_voice(cast: Dict[str, Any], character: str, entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The cast with one character's `voice` set (None = the creator's own).
    KeyError when no character has that name (compared like speakers)."""
    wanted = speaker_key(character)
    characters, found = [], False
    for person in cast.get("characters") or []:
        if isinstance(person, dict) and wanted and speaker_key(str(person.get("name") or "")) == wanted:
            person, found = dict(person, voice=_clean_voice(entry)), True
        characters.append(person)
    if not found:
        raise KeyError(character)
    return dict(cast, characters=characters)


def voice_map_for(cast: Optional[Dict[str, Any]],
                  speakers: List[str]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """BuzzEdit's `voice_map` for a production: {speaker, as the script's
    labels write it -> that character's voice}, for every character with a
    voice; and a warning for each of them whose name never labels a line
    (BuzzEdit's `speaker_spans` speakers; "(V.O.)" dropped, case ignored)."""
    spoken: Dict[str, str] = {}
    for speaker in speakers or []:
        key = speaker_key(str(speaker or ""))
        if key and key not in spoken:
            spoken[key] = speaker_name(str(speaker)) or str(speaker).strip()
    voice_map: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    for person in (cast or {}).get("characters") or []:
        entry = _clean_voice(person.get("voice")) if isinstance(person, dict) else None
        if not entry:
            continue
        name = str(person.get("name") or "")
        label = spoken.get(speaker_key(name))
        if label is None:
            warnings.append(f"{name} has a voice but never speaks a line of their own in the script "
                            f"(no {name.upper()}: or {name.upper()} (V.O.) line), so it was not used.")
            continue
        voice_map[label] = {k: entry[k] for k in VOICE_KEYS if entry.get(k) is not None}
    return voice_map, warnings


#: BuzzEdit draws the reference portrait from the look and takes a shorter one
#: as "no lead" (character.from_settings), so a thinner look marks nothing here.
MIN_FACE_LOOK_WORDS = 6


def main_character(cast: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The cast entry of the story's main character, or None (also when their
    look is too thin to draw one fixed face from)."""
    name = (cast or {}).get("main_character") or ""
    person = next((p for p in (cast or {}).get("characters") or [] if p.get("name") == name), None) if name else None
    if person is None or len(str(person.get("look") or "").split()) < MIN_FACE_LOOK_WORDS:
        return None
    return person


def buzzedit_main_character(cast: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """BuzzEdit's `main_character` render setting: the face to swap into every
    `face=main` shot, `{}` when the story has no lead (BuzzEdit then guesses
    nothing and swaps nothing), or None for an undecided sheet (field left out)."""
    if not cast or "main_character" not in cast:
        return None
    person = main_character(cast)
    if person is None:
        return {}
    return {"name": person["name"], "description": person["look"], "gender": person.get("gender", "")}


def _pick_main(project: Any, cast: Dict[str, Any], story: str, agent_factory: Any) -> Dict[str, Any]:
    """An older sheet with its main character decided (and saved), or the
    sheet unchanged when the model cannot answer."""
    if not cast.get("characters") or not story:
        return cast
    try:
        from integrations.llm import clean_json_response

        agent = agent_factory()
        sheet = {k: v for k, v in cast.items() if k != "main_character"}
        raw = agent.execute(MAIN_PROMPT.format(main_rules=MAIN_RULES,
                                               cast=json.dumps(sheet, ensure_ascii=False),
                                               story=story[:_CAST_SOURCE_CHARS // 2]),
                            require_json=True)
        if getattr(getattr(agent, "llm_service", None), "last_response_simulated", False):
            return cast
        answer = json.loads(clean_json_response(str(raw)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("story_visuals: could not pick a main character (%s).", exc)
        return cast
    if not isinstance(answer, dict):
        return cast
    data = dict(cast, main_character=answer.get("main_character") or "")
    gender = _GENDERS.get(str(answer.get("gender") or "").strip().lower())
    if gender:
        data["characters"] = [dict(p, gender=p.get("gender") or gender)
                              if p["name"].lower() == str(data["main_character"]).strip().lower() else p
                              for p in cast["characters"]]
    upgraded = _clean_cast(data)
    _save_cast_sheet(project, upgraded)
    logger.info("story_visuals: main character picked for an older cast sheet: %r.",
                upgraded.get("main_character"))
    return upgraded


def _save_cast_sheet(project: Any, cast: Dict[str, Any]) -> None:
    if cast.get("world"):
        cast["world"] = visual_world(cast["world"])
    path = os.path.join(project.get_project_dir(), CAST_SHEET_ASSET)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cast, f, indent=2, ensure_ascii=False)


def save_cast_sheet(project: Any, cast: Dict[str, Any]) -> Dict[str, Any]:
    """Write an edited cast sheet (a character's voice, a voice proposal) and
    return it as stored."""
    clean = _clean_cast(cast)
    _save_cast_sheet(project, clean)
    return clean


def load_cast_sheet(project: Any) -> Dict[str, Any]:
    path = os.path.join(project.get_project_dir(), CAST_SHEET_ASSET)
    try:
        with open(path, "r", encoding="utf-8") as f:
            cast = _clean_cast(json.load(f))
    except (OSError, ValueError):
        return {}
    if cast.get("world"):
        cast["world"] = visual_world(cast["world"])
    return cast


def ensure_cast_sheet(project: Any, story_text: str, agent_factory: Any) -> Dict[str, Any]:
    """The project's cast sheet, written by the CharacterPlanner the first
    time it is needed. A failure returns {} -- the video still renders, just
    without the continuity hints."""
    existing = load_cast_sheet(project)
    story = (story_text or "").strip()
    if existing:
        if "main_character" not in existing:
            return _pick_main(project, existing, story, agent_factory)
        return existing
    if not story:
        return {}
    try:
        from integrations.llm import clean_json_response

        agent = agent_factory()
        prompt = CAST_PROMPT.format(main_rules=MAIN_RULES, bible=_bible_text(project),
                                    story=story[:_CAST_SOURCE_CHARS])
        raw = agent.execute(prompt, require_json=True)
        if getattr(getattr(agent, "llm_service", None), "last_response_simulated", False):
            logger.warning("story_visuals: cast sheet got simulated output; continuing without one.")
            return {}
        cast = _clean_cast(json.loads(clean_json_response(str(raw))))
    except Exception as exc:  # noqa: BLE001
        logger.warning("story_visuals: could not write a cast sheet (%s).", exc)
        return {}
    if not cast.get("characters") and not cast.get("world"):
        return {}
    cast.setdefault("main_character", "")
    _save_cast_sheet(project, cast)
    try:
        project.assets["cast_sheet"] = CAST_SHEET_ASSET
        project.save()
    except Exception:  # noqa: BLE001
        pass
    logger.info("story_visuals: cast sheet written (%d character(s), main: %r).",
                len(cast["characters"]), cast["main_character"])
    return cast


# --------------------------------------------------------- script rewrite

def _split_arg(arg: str) -> Tuple[str, Dict[str, str]]:
    """`prompt | look=noir` -> ("prompt", {"look": "noir"})."""
    fields, options = [], {}
    for part in arg.split("|"):
        part = part.strip()
        if not part:
            continue
        key, eq, value = part.partition("=")
        if eq and re.fullmatch(r"[a-z_]+", key.strip().lower()):
            options[key.strip().lower()] = value.strip()
        else:
            fields.append(part)
    return " | ".join(fields), options


def _join_arg(prompt: str, options: Dict[str, str]) -> str:
    return " | ".join([prompt] + [f"{k}={v}" for k, v in options.items()])


def _mentions(prompt: str, words: List[str]) -> bool:
    low = prompt.lower()
    for word in words:
        word = word.strip().lower()
        if len(word) >= 3 and re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", low):
            return True
    return False


def _with_continuity(prompt: str, cast: Optional[Dict[str, Any]]) -> str:
    """`prompt` plus the fixed look of every cast member it shows and the
    story's world -- each added once, never twice, and neither bringing in a
    creature the prompt itself does not name."""
    if not cast:
        return prompt
    extra: List[str] = []
    for person in cast.get("characters") or []:
        look = person.get("look") or ""
        if not look or look[:40].lower() in prompt.lower():
            continue
        if _mentions(prompt, [person.get("name") or ""] + list(person.get("aliases") or [])):
            extra.append(f"{person['name']}: {look}")
    world = visual_world(cast.get("world") or "")
    if world and world[:40].lower() not in prompt.lower():
        extra.append(world)
    named = _creatures_in(prompt)
    extra = [text for text in (_strip_creatures(e, named) for e in extra) if text]
    return prompt if not extra else prompt.rstrip(" .,;") + ". " + ". ".join(extra)


def lint_prompt(prompt: str, beat_text: str) -> str:
    """The last guard on an outgoing picture prompt: a creature word that the
    beat's own prompt (`beat_text`, before continuity) does not name is cut
    out, wherever it came from."""
    return _strip_creatures(prompt, _creatures_in(beat_text))


# ------------------------------------------------------------ main face
#
# BuzzEdit swaps the main character's reference face into every `[broll:]` /
# `[video:]` marked `face=main` (ReActor, largest face in the frame only), and
# into nothing else. The planner marks each beat `main_face` true or false
# (`face=main` / `face=no`); a script whose pictures carry no mark at all (the
# writer's own directives) is marked here from who the prompt names.

FACE_OPTION = "face"
_FACE_ON = {"main", "true", "yes", "on", "1"}
#: The main character is in the shot but their face is not: swapping would
#: find another face, or none.
_NO_FACE_RE = re.compile(
    r"\b(?:from behind|back view|(?:his|her|their) back|back to the|backs? turned|turns? away|"
    r"walks? away|silhouett\w*|shadow of|(?:his|her|their) shadow|hands?|fingers|feet|footsteps|"
    r"far away|distant|in the distance|tiny figure|faceless|face (?:hidden|obscured|covered)|"
    r"hidden face)\b", re.IGNORECASE)
_FACE_MARK_RE = re.compile(r"\|\s*" + FACE_OPTION + r"\s*=", re.IGNORECASE)


def _with_face(prompt: str, options: Dict[str, str], cast: Optional[Dict[str, Any]],
               infer: bool) -> Tuple[str, Dict[str, str]]:
    """`prompt` and `options` with the face mark settled: `face=main` and the
    main character's look (first, where the image model weighs it most) on a
    shot of them, no `face` option on any other shot. With others in the shot
    the main character is put nearest, since only the largest face is swapped."""
    options = dict(options)
    marked = str(options.pop(FACE_OPTION, "")).strip().lower() in _FACE_ON
    main = main_character(cast)
    if main is None:
        return prompt, options
    names = [main["name"]] + list(main.get("aliases") or [])
    if infer:
        marked = _mentions(prompt, names) and not _NO_FACE_RE.search(prompt)
    if not marked:
        return prompt, options
    if main["look"][:40].lower() not in prompt.lower():
        prompt = f"{main['name']}: {main['look']}. {prompt}"
    others = [p["name"] for p in (cast or {}).get("characters") or []
              if p is not main and _mentions(prompt, [p["name"]] + list(p.get("aliases") or []))]
    if others:
        prompt = (prompt.rstrip(" .,;") + f". {main['name']} in the foreground, nearest, the largest "
                  f"face in the picture; {', '.join(others)} further back, smaller")
    options[FACE_OPTION] = "main"
    return prompt, options


def _face_suffix(options: Dict[str, str]) -> str:
    return f" | {FACE_OPTION}=main" if options.get(FACE_OPTION) == "main" else ""


def _picture(prompt: str, options: Dict[str, str], cast: Optional[Dict[str, Any]],
             infer: bool) -> Tuple[str, Dict[str, str]]:
    """One picture directive's prompt and options, ready for BuzzEdit."""
    beat_text = prompt
    prompt, options = _with_face(prompt, options, cast, infer)
    return lint_prompt(without_camera(_with_continuity(prompt, cast)), beat_text), options


# --------------------------------------------------------------- no camera
#
# The still model draws whatever a prompt names, and BuzzEdit draws a
# `[video:]` clip's first frame from the clip's own text -- so a planner's
# "The camera slowly pans across his face" put a DSLR in the shot, and the
# clip animated from that still kept it. Every picture prompt is rewritten to
# name the movement, not the thing filming it.

_ADVERBS = {"slowly": "slow", "gently": "gentle", "steadily": "steady",
            "smoothly": "smooth", "softly": "gentle"}
#: Verb stem after "the camera" -> what the shot is called without it ("" drops
#: the phrase: "the camera captures his hands" -> "his hands").
_CAMERA_MOVES: Tuple[Tuple[str, str], ...] = (
    ("pan", "pan"), ("track", "tracking view of"), ("mov", "push"), ("zoom", "zoom"),
    ("push", "push"), ("pull", "pull back"), ("glid", "glide"), ("drift", "drift"),
    ("tilt", "tilt"), ("doll", "push"), ("cran", "rise"), ("ris", "rise"),
    ("rotat", "orbit"), ("circl", "orbit"), ("orbit", "orbit"), ("follow", "view following"),
    ("hold", "lingering view"), ("linger", "lingering view"), ("remain", "still view"),
    ("stay", "still view"), ("look", "view"), ("cut", "cut"), ("focus", "close focus"),
    ("captur", ""), ("show", ""), ("reveal", ""), ("fram", ""),
)
_CAMERA_ACTION_RE = re.compile(
    r"\b(?:the\s+|a\s+)?camera\s+(?P<adv>(?:(?:slowly|gently|steadily|smoothly|softly|quickly|"
    r"then|now|also|is|continues\s+to|begins\s+to|starts\s+to)\s+)*)"
    r"(?P<verb>(?:" + "|".join(stem for stem, _ in _CAMERA_MOVES) + r")[a-z]*)"
    r"(?:\s+(?:still|static|steady|fixed|motionless)\b)?",
    re.IGNORECASE)
_CAMERA_NOUN_RE = re.compile(
    r"\bcamera\s+(movement|motion|shake|work|angles?|moves?|position|pov|perspective)\b", re.IGNORECASE)
_AT_CAMERA_RE = re.compile(
    r"\b(?:on|to|toward|towards|into|at|facing)\s+(?:the\s+)?camera\b", re.IGNORECASE)
_GEAR_RE = re.compile(
    r"\b(?:shot|taken|captured|photographed|filmed)\s+(?:on|with)\s+(?:an?\s+)?"
    r"(?:dslr|camera|canon|nikon|sony|\d+\s?mm)[^,.;\]]*"
    r"|\b\d{2,3}\s?mm\s+lens\b|\bf/\d+(?:\.\d+)?\b|\bdslr\b",
    re.IGNORECASE)
#: Words that make "camera" an object of the story (kept): a CCTV camera.
_STORY_CAMERAS = {"cctv", "security", "surveillance", "video", "old", "vintage", "broken",
                  "polaroid", "film", "phone", "mobile", "trail", "doorbell", "dash",
                  "dashboard", "hidden", "his", "her", "their", "web", "spy", "night-vision"}
_LEFTOVER_CAMERA_RE = re.compile(r"\b(?:([\w-]+)\s+)?camera\b", re.IGNORECASE)


def _camera_move(m: "re.Match[str]") -> str:
    verb = m.group("verb").lower()
    shot = next((name for stem, name in _CAMERA_MOVES if verb.startswith(stem)), "")
    if shot:
        adverb = next((_ADVERBS[w] for w in m.group("adv").lower().split() if w in _ADVERBS), "")
        shot = f"{adverb} {shot}".strip()
    if shot and m.group(0)[:1].isupper():
        shot = shot[:1].upper() + shot[1:]
    return shot


def _leftover_camera(m: "re.Match[str]") -> str:
    before = (m.group(1) or "").lower()
    if before in _STORY_CAMERAS:
        return m.group(0)
    return "the view" if before == "the" else (m.group(1) + " " if m.group(1) and before != "a" else "")


def without_camera(prompt: str) -> str:
    """`prompt` with every mention of the camera filming the shot rewritten
    as the shot itself; a camera that is part of the story (a CCTV camera on
    the wall) stays."""
    if not re.search(r"camera|dslr|\bf/\d|\d\s?mm\b", prompt, re.IGNORECASE):
        return prompt
    text = _CAMERA_ACTION_RE.sub(_camera_move, prompt)
    text = _CAMERA_NOUN_RE.sub(lambda m: m.group(1), text)
    text = _AT_CAMERA_RE.sub("toward the viewer", text)
    text = _GEAR_RE.sub("", text)
    text = _LEFTOVER_CAMERA_RE.sub(_leftover_camera, text)
    text = re.sub(r"\s+([,.;])", r"\1", text)
    text = re.sub(r"([,;])(?:\s*[,;])+", r"\1", text)
    text = re.sub(r"(^|[.;])\s*,[,\s]*", lambda m: m.group(1) + (" " if m.group(1) else ""), text)
    text = _SPACE_RUN_RE.sub(" ", text).strip(" ,;")
    # A sentence that now starts lower-case ("his hands shake") reads fine to
    # the model; only the very first letter is tidied.
    return text[:1].upper() + text[1:] if text else prompt


def _video_prompt(prompt: str, options: Dict[str, str]) -> str:
    look = options.get("look")
    text = prompt.rstrip(" .,;")
    if look:
        text += f", {look} look"
    if CALM_MOTION not in text:
        text += f", {CALM_MOTION}"
    return text


def _video_positions(count: int, share: float) -> List[bool]:
    """Which of `count` pictures should be clips for `share`, spread evenly
    (the n-th picture is a clip when it crosses the next whole multiple)."""
    share = max(0.0, min(1.0, share))
    return [math.floor((i + 1) * share + 1e-9) > math.floor(i * share + 1e-9) for i in range(count)]


# ------------------------------------------------------------ timed shots
#
# "Video 80%" means 80% of the finished video's running time is generated
# clips, and "Images 20%" a fifth of it still pictures; the face gets the rest. Counting pictures cannot get there: BuzzEdit used to end every
# script shot 4-5 s after its word whatever came next, so a 13.5-minute
# Raat3Baje cut with 14 clips had 70 s of video (9%). With the edited
# programme's word times known, every shot is given an exact length
# (`seconds=` on the directive, which BuzzEdit honours) and the clips are laid
# down until they fill the share, spread evenly through the video.

#: Longest clip Wan is asked for (BuzzEdit's BROLL_SECONDS_CAP).
CLIP_MAX_SECONDS = 8.0
#: Shortest still worth showing.
MIN_STILL_SECONDS = 2.5
#: Video + images at least this share of the runtime: the opening before the
#: first picture is covered too (the face only appears where the mix leaves room).
FULL_COVER = 0.97
#: Shortest clip worth generating; shorter reads as a flash in a calm story.
MIN_CLIP_SECONDS = 3.0
#: Two pictures closer together than this are one moment: the later is dropped.
MIN_SHOT_SECONDS = 2.5
#: Less of the speaker than this between two shots is a flicker, not a
#: shot of them: the picture runs on to the next one instead.
MIN_FACE_SECONDS = 1.5
#: Extra clips that carry a scene on when its stretch of narration is longer
#: than one clip. The same place and people, a different view.
CONTINUATIONS = ("the same moment, seen a little closer", "the same place, seen wider",
                 "a quiet detail of the same scene", "the same scene, a moment later")

_PIECE_RE = re.compile(r"\[\s*([a-z_]+)\s*:\s*([^\]]*?)\s*\]|\s+|[^\s\[]+|\[", re.IGNORECASE)


def _floor2(seconds: float) -> float:
    return math.floor(max(0.0, seconds) * 100.0 + 1e-6) / 100.0


def plan_timed_shots(anchors: List[int], word_starts: List[float], duration_s: float,
                     share: float, clip_max_s: float = CLIP_MAX_SECONDS,
                     image_share: float = 0.0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Every shot's start word, length and kind.

    `share` and `image_share` are the shares of the RUNNING TIME that are
    generated clips and still images; the creator's face gets the rest. Video
    has priority, then images (an image share past what video leaves is cut
    to fit), then the face.

    `anchors` are the pictures' word indexes in story order; `word_starts`
    each word's programme time. Each picture owns the narration from its word
    to the next picture's. Walking the video in order, a stretch is filled
    with clips when the video is behind `share` x the time elapsed by its end,
    then with stills when the images are behind theirs -- back to back, each
    piece at most `clip_max_s` and starting on a word -- so both track their
    share all the way through instead of bunching. Returns `(shots, stats)`;
    each shot is `{picture, word, seconds, video, part}` (`part` > 0 carries
    the picture's scene on in a further clip or still)."""
    share_v = max(0.0, min(1.0, share))
    share_i = max(0.0, min(1.0 - share_v, image_share))
    clip_max_s = max(MIN_CLIP_SECONDS, min(CLIP_MAX_SECONDS, clip_max_s))
    n_words = len(word_starts)

    def at(j: int) -> float:
        return word_starts[j] if j < n_words else duration_s

    kept: List[int] = []
    merged = 0
    for i, j in enumerate(anchors):
        # With no images, a stretch too short for a clip would only be face:
        # it joins the picture before it.
        too_close = MIN_SHOT_SECONDS if share_i > 0 else max(MIN_SHOT_SECONDS, MIN_CLIP_SECONDS)
        if j >= n_words or (kept and at(j) - at(anchors[kept[-1]]) < too_close):
            merged += 1
            continue
        kept.append(i)
    anchors = list(anchors)
    full = share_v + share_i >= FULL_COVER
    if kept and full:
        # Everything is pictures: the first one starts on the first word, so
        # the opening before it is covered too.
        anchors[kept[0]] = 0

    def word_near(after: int, target: float, lo: float, hi: float) -> Optional[int]:
        """The word nearest `target` starting within [lo, hi], past `after`."""
        first = bisect.bisect_left(word_starts, lo, after)
        last = bisect.bisect_right(word_starts, hi, first) - 1
        if last < first:
            return None
        k = bisect.bisect_left(word_starts, target, first, last + 1)
        options = [x for x in (k - 1, k) if first <= x <= last]
        return min(options, key=lambda x: abs(word_starts[x] - target)) if options else None

    def floor_of(video: bool) -> float:
        return MIN_CLIP_SECONDS if video else MIN_STILL_SECONDS

    shots: List[Dict[str, Any]] = []
    done = {True: 0.0, False: 0.0}                 # video seconds, still seconds
    for k, i in enumerate(kept):
        j0 = anchors[i]
        start0 = at(j0)
        end = at(anchors[kept[k + 1]]) if k + 1 < len(kept) else duration_s
        window = max(0.0, end - start0)
        # The stretch is filled toward video + images together; video takes
        # its share first and images the rest. Tracking the images' own deficit
        # instead starved them: at 80/20 video left gaps too short for a still
        # in most stretches, and the images ended at 14%.
        want_all = min(window, max(0.0, (share_v + share_i) * end - done[True] - done[False]))
        behind_v = share_v * end - done[True]
        behind_i = share_i * end - done[False]
        if want_all < MIN_CLIP_SECONDS + MIN_STILL_SECONDS:
            # Too short to split into a clip and a still: the whole stretch
            # goes to whichever is further behind its share (video on a tie),
            # or a split would leave image slivers too short to show -- at
            # 80/20 the images ended at 14%.
            take_video = share_v > 0 and want_all >= MIN_CLIP_SECONDS and (behind_v >= behind_i or share_i <= 0)
            want_v = want_all if take_video else 0.0
            want_i = 0.0 if take_video or share_i <= 0 else want_all
        else:
            want_v = min(want_all, max(0.0, behind_v))
            want_v = want_v if want_v >= MIN_CLIP_SECONDS else 0.0
            want_i = want_all - want_v if share_i > 0 else 0.0
        want_i = want_i if want_i >= MIN_STILL_SECONDS else 0.0
        if want_i == 0.0 and 0 < want_all - want_v and want_v and share_i <= 0:
            want_v = want_all
        if want_v + want_i <= 0:
            continue                                # the face carries this stretch
        # A sliver of face between two shots is a flicker -- and at a full mix
        # there is no face at all: either way the last kind runs on.
        if window - want_v - want_i < (window + 1.0 if full else MIN_FACE_SECONDS):
            if want_i:
                want_i = window - want_v
            else:
                want_v = window
        pieces = ([(True, want_v / math.ceil(want_v / clip_max_s))] * math.ceil(want_v / clip_max_s)
                  if want_v else [])
        pieces += ([(False, want_i / math.ceil(want_i / clip_max_s))] * math.ceil(want_i / clip_max_s)
                   if want_i else [])
        limit = start0 + want_v + want_i
        j, start = j0, start0
        for n, (video, length) in enumerate(pieces):
            next_j: Optional[int] = None
            if n + 1 < len(pieces):
                next_video = pieces[n + 1][0]
                next_j = word_near(j + 1, start + length, start + floor_of(video),
                                   min(start + clip_max_s, limit - floor_of(next_video)))
                if next_j is None and limit - start > clip_max_s:
                    # A silence with no word to cut on: hold the full length and
                    # start the next piece on the first word after it.
                    after = bisect.bisect_left(word_starts, start + clip_max_s, j + 1)
                    next_j = after if after < n_words and at(after) < limit - floor_of(next_video) else None
            hold = min(clip_max_s, at(next_j) - start) if next_j is not None else min(clip_max_s, limit - start)
            hold = _floor2(hold)
            if hold >= floor_of(video) or (n == 0 and hold >= 1.0):
                shots.append({"picture": i, "word": j, "seconds": hold, "video": video, "part": n})
                done[video] += hold
            if next_j is None:
                break
            j, start = next_j, at(next_j)

    clips = [s for s in shots if s["video"]]
    stills = [s for s in shots if not s["video"]]
    video_s = sum(s["seconds"] for s in clips)
    image_s = sum(s["seconds"] for s in stills)
    stats = {
        "runtime_s": round(duration_s, 1),
        "video_target_s": round(share_v * duration_s, 1),
        "video_s": round(video_s, 1),
        "video_runtime_share": round(video_s / duration_s, 3) if duration_s else 0.0,
        "image_target_s": round(share_i * duration_s, 1),
        "image_s": round(image_s, 1),
        "image_runtime_share": round(image_s / duration_s, 3) if duration_s else 0.0,
        "face_runtime_share": round(max(0.0, 1.0 - (video_s + image_s) / duration_s), 3) if duration_s else 1.0,
        "clips": len(clips),
        "continuation_clips": sum(1 for s in clips if s["part"] > 0),
        "stills": len(stills),
        "still_s": round(image_s, 1),
        "pictures_merged": merged,
    }
    return shots, stats


def _apply_timed(text: str, share: float, cast: Optional[Dict[str, Any]],
                 word_times: List[float], duration_s: float, clip_max_s: float,
                 image_share: float, stats: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """`apply_to_script` when the programme's word times are known: the
    pictures are lifted out of the text, timed by `plan_timed_shots` and put
    back before the words they now start on, each with its `seconds=`."""
    infer = not _FACE_MARK_RE.search(text)
    pieces: List[Tuple[str, str]] = []                      # ("word"|"space"|"keep", text)
    pictures: List[Tuple[int, str, Dict[str, str]]] = []   # (word index, prompt, options)
    # A character's speaker label on its own line ("MAYA:", script_reconcile)
    # is not a spoken word: it must not shift the words onto the wrong times.
    label_spans = [(m.start(), m.end()) for m in LABEL_LINE_RE.finditer(text) if m.group(0).strip()]
    label_starts = [start for start, _ in label_spans]
    n_words = 0
    for m in _PIECE_RE.finditer(text):
        piece = m.group(0)
        if m.group(1) is not None:
            kind = m.group(1).lower()
            if kind not in KEPT_DIRECTIVES:
                stats["removed"] += 1
            elif kind in _AS_WRITTEN:
                pieces.append(("keep", piece))
            else:
                prompt, options = _picture(*_split_arg(m.group(2)), cast, infer)
                pictures.append((n_words, prompt, options))
        elif piece.isspace():
            pieces.append(("space", piece))
        elif label_spans and _inside(m.start(), label_starts, label_spans):
            pieces.append(("keep", piece))
        else:
            pieces.append(("word", piece))
            n_words += 1

    # The rendered text is the programme's own words, one token each; if the
    # count ever disagrees, map by position rather than lose the timing.
    if len(word_times) == n_words:
        starts = [float(t) for t in word_times]
    else:
        scale = len(word_times) / max(1, n_words)
        starts = [float(word_times[min(len(word_times) - 1, int(j * scale))]) for j in range(n_words)]
    for j in range(1, len(starts)):
        starts[j] = max(starts[j], starts[j - 1])

    shots, timing = plan_timed_shots([p[0] for p in pictures], starts, duration_s, share,
                                     clip_max_s, image_share)
    inserts: Dict[int, List[str]] = {}
    for shot in shots:
        _, prompt, options = pictures[shot["picture"]]
        if shot["part"]:
            prompt = f"{prompt.rstrip(' .,;')}, {CONTINUATIONS[(shot['part'] - 1) % len(CONTINUATIONS)]}"
        seconds = f"seconds={shot['seconds']:g}"
        stats["main_face"] += 1 if options.get(FACE_OPTION) == "main" else 0
        if shot["video"]:
            directive = f"[video: {_video_prompt(prompt, options)} | {seconds}{_face_suffix(options)}]"
        else:
            directive = f"[broll: {_join_arg(prompt, options)} | {seconds}]"
        inserts.setdefault(shot["word"], []).append(directive)

    out: List[str] = []
    j = 0
    for kind, piece in pieces:
        if kind == "word":
            out.extend(directive + " " for directive in inserts.get(j, []))
            j += 1
        out.append(piece)
    rewritten = "".join(out)
    rewritten = _SPACE_RUN_RE.sub(" ", rewritten)
    rewritten = _BLANK_RUN_RE.sub("\n\n", rewritten).strip() + "\n"

    stats["pictures"] = len(pictures)
    stats["videos"] = timing["clips"]
    stats["made_video"] = timing["clips"]
    stats.update(timing)
    return rewritten, stats


def _inside(position: int, starts: List[int], spans: List[Tuple[int, int]]) -> bool:
    k = bisect.bisect_right(starts, position) - 1
    return k >= 0 and position < spans[k][1]


def apply_to_script(text: str, share: float, cast: Optional[Dict[str, Any]] = None,
                    word_times: Optional[List[float]] = None, duration_s: Optional[float] = None,
                    clip_max_s: float = CLIP_MAX_SECONDS,
                    image_share: float = 0.0) -> Tuple[str, Dict[str, Any]]:
    """The directive script BuzzEdit is handed, rewritten for the story style.
    Returns `(text, stats)`; spoken words are never touched.

    With `word_times` (each spoken word's start in the edited programme) and
    `duration_s`, `share` and `image_share` are the shares of the whole
    video's RUNNING TIME that are generated clips and still images (the face
    gets the rest), and every shot is timed to make it so (`_apply_timed`).
    Without them it is the share of the pictures that are clips."""
    stats: Dict[str, Any] = {"removed": 0, "headings_removed": 0, "pictures": 0, "videos": 0,
                             "made_video": 0, "main_face": 0}

    headings = _HEADING_LINE_RE.findall(text)
    stats["headings_removed"] = len(headings)
    text = _HEADING_LINE_RE.sub("\n", text)
    if word_times and duration_s and duration_s > 0:
        return _apply_timed(text, share, cast, word_times, float(duration_s),
                            clip_max_s, image_share, stats)

    infer = not _FACE_MARK_RE.search(text)
    matches = list(_DIRECTIVE_RE.finditer(text))
    pictures = [m for m in matches if m.group(1).lower() in ("broll", "video")]
    make_video = _video_positions(len(pictures), share)
    picture_index = {m.start(): n for n, m in enumerate(pictures)}

    out: List[str] = []
    pos = 0
    for m in matches:
        out.append(text[pos:m.start()])
        pos = m.end()
        kind = m.group(1).lower()
        if kind not in KEPT_DIRECTIVES:
            stats["removed"] += 1
            continue
        if kind in _AS_WRITTEN:
            out.append(m.group(0))
            continue
        prompt, options = _picture(*_split_arg(m.group(2)), cast, infer)
        stats["pictures"] += 1
        stats["main_face"] += 1 if options.get(FACE_OPTION) == "main" else 0
        if kind == "video" or make_video[picture_index[m.start()]]:
            if kind == "broll":
                stats["made_video"] += 1
            stats["videos"] += 1
            out.append(f"[video: {_video_prompt(prompt, options)}{_face_suffix(options)}] ")
        else:
            out.append(f"[broll: {_join_arg(prompt, options)}] ")
    out.append(text[pos:])
    rewritten = "".join(out)
    rewritten = _SPACE_RUN_RE.sub(" ", rewritten)
    rewritten = _BLANK_RUN_RE.sub("\n\n", rewritten).strip() + "\n"
    return rewritten, stats


def filter_beats(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Plan beats the story style keeps (for the plan-review screen, so the
    creator is not shown cards that will never render)."""
    return [b for b in beats if str(b.get("kind") or "").strip().lower() in KEPT_BEAT_KINDS]
