"""Life3Baje mood reel (REELS_DESK_PLAN.md §6, VR2): the planning pieces.

2-4 real ghazal / kavita lines (the Shorts desk's rights-checked poem search)
shown one couplet at a time as text cards over 4-6 slow portrait scenes in one
world, with a generated soothing bed and the theme's own ambience. No voice,
no face, no production queue -- the reel is rendered by BuzzEdit's recording-
less renderer (`POST /api/reels/vibe`).

    theme/mood  pick_theme()/pick_mood()  the creator's named visual themes, rotated so
                                           consecutive reels differ, each paired with a mood
    lines       find_lines()              shorts_desk.find -> the best-scoring candidate
                                           with whole couplets (any rights, credited; never
                                           Urdu script on screen)
    shots       plan_shots()              MoodReelPlanner -> validate_plan() (4-6 shots, timing,
                                           no camera words, couplet cards, credit)
    ambience    ambience_for()            the theme's own quiet sound bed (rain, wind ...)
    request     vibe_body()               the exact `POST /api/reels/vibe` body: `music` is
                                           always None (2026-10-24, VR8) -- the creator adds his
                                           own Instagram song over the ambience; `music_for()`
                                           is kept but unused

The orchestration (project, plan, BuzzEdit render, package) is
`auto_story.make_mood_reel`.
"""

import json
import logging
import random
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("buzzcaf_ai.mood_reel")

KEY = "mood_reel"
LABEL = "Mood reel (ghazal lines over slow scenes)"
# 15-30s (2026-10-23 night rules, VR7: supersedes the earlier 15-45 range);
# `parse_seconds` clamps to this, so 45 is no longer reachable even by hand.
LENGTHS = ("15 seconds", "20 seconds", "26 seconds", "30 seconds")
CHANNELS = ("Life3Baje",)
DEFAULT_SECONDS, MIN_SECONDS, MAX_SECONDS = 26.0, 15.0, 30.0
# "Fewer cuts... 1-3 shots (one long shot is ideal)" (2026-10-23 night rules,
# VR7, supersedes the earlier 4-6 floor): 15s plans 1-2, 20-30s plans 2-3 --
# see `MoodReelPlanner.md`; this is just the outer band `validate_plan` repairs to.
MIN_SHOTS, MAX_SHOTS = 1, 3
# A shot's seconds, as planned: up to the whole reel (one continuous shot,
# VR7 rule B) -- BuzzEdit's vibe renderer chains anything past its own
# single-clip ceiling into several image-to-video segments.
SHOT_MIN_S, SHOT_MAX_S = 4.0, 30.0
#: The cards breathe before the first line and after the last (REELS_DESK_PLAN.md §6).
CARD_LEAD_S, CARD_TAIL_S = 1.5, 2.5
STYLES = ("real", "painterly", "illustrated")
#: The theme/mood rotation remembers this many recent picks (auto_story settings' `rotation`).
RECENT_PICKS = 3
#: A single consistent level inside the creator's -18..-22 dB ask.
AMBIENCE_GAIN_DB = -20.0

#: mood -> (what the planner is told, the shayari theme filter, the kavita theme filter)
MOODS: Dict[str, "tuple[str, str, str]"] = {
    "tanhai": ("tanhai: a quiet loneliness, late night, rain", "Tanhai", "Loneliness"),
    "waqt": ("waqt: time passing gently, dusk turning to night", "Waqt", "Time & death"),
    "zindagi": ("zindagi: calm reflection on life, an empty road at night", "Zindagi / life", "Life & purpose"),
    "umeed": ("umeed: soft hope, first light after a long night", "Umeed", "Hope & courage"),
    "ishq": ("ishq: tender longing, a lamp in the rain", "Ishq", "Love"),
}

#: The visual themes the creator named (2026-10-23 evening), each paired with the
#: existing mood that fits it, plus the theme's own quiet ambience (REELS_DESK_PLAN.md §6).
#: Every world is Indian (his first look at the test reel: the houses came out European).
THEMES: Dict[str, Dict[str, Any]] = {
    "moonlight": {"label": "Moonlight", "mood": "tanhai",
                  "world": "late night under a full moon high in a deep blue sky, a quiet Indian hill town like Shimla or Mussoorie, old Himachali houses with sloped tin roofs, silver moonlight, long still shadows",
                  "ambience": ["a light night breeze", "crickets"]},
    "mountains": {"label": "Misty mountains", "mood": "zindagi",
                  "world": "misty Himalayan mountains and wide valleys, terraced fields, a small temple far off, drifting cloud, distant peaks",
                  "ambience": ["wind over the ridge", "distant birds"]},
    "storm": {"label": "Storm over fields", "mood": "tanhai",
              "world": "a monsoon storm over open Indian village fields, steady rain, distant lightning, wind in the paddy",
              "ambience": ["steady rain", "far thunder"]},
    "cozy": {"label": "Cozy rain", "mood": "ishq",
             "world": "a cozy Indian home, rain on the window, a lamp, a glass of hot chai on the sill, a shawl folded on a charpai",
             "ambience": ["rain on the window glass", "a soft wind outside"]},
    "night_road": {"label": "Quiet night road", "mood": "zindagi",
                   "world": "a quiet Indian hill road at night, sodium streetlights, an empty stretch, slow mist",
                   "ambience": ["a light night breeze", "far traffic"]},
    "snowfall": {"label": "Snowfall", "mood": "umeed",
                 "world": "gentle snowfall over a still Himalayan town of wooden houses, soft white light, quiet",
                 "ambience": ["a hush of wind", "a quiet stillness"]},
    "lake_dusk": {"label": "Lake at dusk", "mood": "waqt",
                  "world": "a hill lake in India at dusk, wooden boats, still water, the last light, soft reflections",
                  "ambience": ["water lapping gently", "crickets"]},
    # 2026-10-23 night rules, VR7: ordinary phone-footage worlds matching the
    # creator's own reference reels (REELS_DESK_PLAN.md §6) -- real Indian
    # places, no camera words, people only far off/from behind/in silhouette.
    "old_houses": {"label": "Old houses", "mood": "waqt",
                   "world": "weathered old houses with peeling lime-wash and wooden balconies along a "
                            "quiet Indian lane at dusk, no one close",
                   "ambience": ["distant birds", "a soft breeze"]},
    "night_forest": {"label": "Night forest", "mood": "tanhai",
                     "world": "moonlight through tall trees in an Indian forest, fireflies, low mist "
                              "drifting between the trunks",
                     "ambience": ["crickets", "a far owl"]},
    "old_hut": {"label": "Old hut in the hills", "mood": "zindagi",
               "world": "a lone mud-and-thatch hut in the Indian hills, a lantern in the doorway, "
                        "chimney smoke rising",
               "ambience": ["wind", "a crackling fire"]},
    "broken_walls": {"label": "Broken walls", "mood": "waqt",
                     "world": "crumbling brick walls of an abandoned Indian haveli, creepers, light "
                              "through broken arches",
                     "ambience": ["wind through ruins", "pigeons"]},
    "village_evening": {"label": "Village evening", "mood": "zindagi",
                        "world": "an Indian village lane in evening light, children far off, cattle "
                                 "returning home, no one up close",
                        "ambience": ["distant voices", "cowbells"]},
    "train_window": {"label": "Train window", "mood": "waqt",
                     "world": "the view from a moving Indian train window over green hills and "
                              "clouds, the window frame in the corner of the shot",
                     "ambience": ["train rhythm"]},
    "city_golden_hour": {"label": "City golden hour", "mood": "zindagi",
                        "world": "a tree-lined Indian street at golden hour, people cycling away, "
                                 "seen from behind, never facing forward",
                        "ambience": ["far traffic"]},
    "monsoon_garden": {"label": "Monsoon garden", "mood": "ishq",
                       "world": "a misty monsoon garden in Kerala, marigolds, steady rain falling "
                                "straight down",
                       "ambience": ["rain on leaves"]},
    "night_street_leaves": {"label": "Night street, autumn leaves", "mood": "tanhai",
                            "world": "a wet Indian night street, sodium lamps, autumn leaves on the "
                                     "ground, no one close",
                            "ambience": ["light rain", "a far scooter"]},
}

_BANNED_RE = re.compile(r"\b(?:shot on|photo of|photograph of|cameras?|dslrs?|lens(?:es)?|tripods?|"
                        r"photographers?)\b", re.IGNORECASE)
#: Urdu (Nastaliq) is Perso-Arabic script; a line fetched in it is skipped --
#: on screen it must be Devanagari or Roman (REELS_DESK_PLAN.md §6).
_URDU_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


def parse_seconds(length: Any) -> float:
    """"26 seconds" / 26 / None -> seconds, kept within 15-45."""
    if length in (None, ""):
        return DEFAULT_SECONDS
    m = re.search(r"\d+(?:\.\d+)?", str(length))
    if not m:
        raise ValueError(f"A mood reel's length is a number of seconds, not {length!r}.")
    return max(MIN_SECONDS, min(MAX_SECONDS, float(m.group(0))))


def is_urdu_script(text: str) -> bool:
    return bool(_URDU_RE.search(text or ""))


def script_of(lines: List[str]) -> str:
    """"devanagari" when any line uses it, else "roman" (never Urdu -- `find_lines` skips it)."""
    return "devanagari" if _DEVANAGARI_RE.search(" ".join(lines)) else "roman"


# --- theme / mood rotation ----------------------------------------------------------------

def _recent(rotation_key: str) -> List[str]:
    from app.services import auto_story
    return list((auto_story.settings().get("rotation") or {}).get(rotation_key) or [])


def _remember(rotation_key: str, picked: str) -> None:
    from app.services import auto_story
    rotation = dict(auto_story.settings().get("rotation") or {})
    rotation[rotation_key] = (list(rotation.get(rotation_key) or []) + [picked])[-RECENT_PICKS:]
    auto_story.set_settings({"rotation": rotation})


def pick_mood(mood: Optional[str] = None) -> str:
    if mood and mood in MOODS:
        return mood
    recent = _recent("mood_reel_mood")
    choices = [m for m in MOODS if m not in recent] or list(MOODS)
    picked = random.choice(choices)
    _remember("mood_reel_mood", picked)
    return picked


def pick_theme(theme: Optional[str] = None) -> str:
    """A visual theme, rotated so it is never one of the last few picks (unless
    `theme` is given explicitly, e.g. from the Story Desk's picker)."""
    if theme and theme in THEMES:
        return theme
    recent = _recent("mood_reel_theme")
    choices = [t for t in THEMES if t not in recent] or list(THEMES)
    picked = random.choice(choices)
    _remember("mood_reel_theme", picked)
    return picked


# --- lines ------------------------------------------------------------------------------

def _units(text: str) -> List[List[str]]:
    """The poem as whole couplets (a stanza's lines in pairs); a stanza's odd last line is
    half of a sher cut by the excerpt, so it ends the run instead of joining it."""
    units: List[List[str]] = []
    for stanza in re.split(r"\n\s*\n", text or ""):
        lines = [ln.strip() for ln in stanza.split("\n") if ln.strip()]
        lines = [ln for ln in lines if not ln.startswith(("#", "—", "-", "("))]
        for i in range(0, len(lines), 2):
            units.append(lines[i:i + 2])
        if len(lines) % 2:
            break
    return units


def _ending(line: str) -> str:
    """A line's last word, bare: what a ghazal's radif (or a poem's rhyme) repeats."""
    words = re.findall(r"[\wऀ-ॿ]+", line or "")
    return words[-1].lower() if words else ""


def _same_poem(first: List[str], unit: List[str]) -> bool:
    """Whether a couplet continues the first one: the same radif (last word of the
    second line), or at least the same rhyme (its last two letters). A page holding
    several ghazals otherwise joins two of them (2026-10-23: Ghalib's "...dam nikle"
    sher followed by one ending "...kyun ho")."""
    a, b = _ending(first[-1]), _ending(unit[-1])
    return bool(a and b) and (a == b or a[-2:] == b[-2:])


def take_lines(text: str, most: int = 4) -> List[str]:
    """2-4 consecutive lines from the start of `text`, whole couplets only (a sher is never
    cut), and only couplets of the same ghazal or poem as the first."""
    out: List[str] = []
    for unit in _units(text):
        if len(unit) < 2 or len(out) + len(unit) > most:
            break
        if out and not _same_poem(out[:2], unit):
            break
        out += unit
        if len(out) >= most:
            break
    return out if len(out) >= 2 else []


#: Where public-domain lines live (died before 1966 under Indian law): the eras
#: the Shorts desk filters by, then poets by name, tried in this order -- tried
#: first since they tend to bring the most relatable, widely-known couplets, but
#: (2026-10-23 evening) no longer the only rights accepted: Instagram allows a
#: credited song or a living poet's line too, so a candidate is never rejected
#: for its rights, only for having no whole couplet or being in Urdu script.
PUBLIC_DOMAIN_ERAS = {"shayari": ["Classical (Mir, Ghalib, Daagh, Zauq)"],
                      "poem": ["Bhakti (Kabir, Tulsi, Meera)", "Chhayavad (Nirala, Prasad, Pant, Mahadevi)"]}
PUBLIC_DOMAIN_POETS = {"shayari": ["Mirza Ghalib", "Mir Taqi Mir", "Momin Khan Momin", "Daagh Dehlvi", "Jigar Moradabadi", "Majaz Lakhnavi", "Allama Iqbal"],
                       "poem": ["Kabir", "Meera Bai", "Suryakant Tripathi Nirala", "Jaishankar Prasad", "Maithili Sharan Gupt", "Rahim"]}
MAX_FIND_ATTEMPTS = 6

def find_lines(channel: str, mood: str, say) -> Dict[str, Any]:
    """The best candidate's opening couplets: {lines, poet, title, candidate, format}.
    Any rights (credited, never silently embedded as a copyrighted recording --
    that is the render's job, not this search's); the public-domain-biased
    search order is kept since it tends to surface the most relatable couplets
    first, but a candidate is taken on its score, not its rights."""
    from app.services import shorts_desk
    _, shayari_theme, poem_theme = MOODS[mood]
    errors: List[str] = []
    attempts = []
    for fmt, theme in (("shayari", shayari_theme), ("poem", poem_theme)):
        if fmt not in shorts_desk.FORMATS.get(channel, {}):
            continue
        eras = PUBLIC_DOMAIN_ERAS.get(fmt, [])
        attempts.append((fmt, {"length": "Short (4-8 lines)", "theme": theme, "era": eras[0]} if eras else
                         {"length": "Short (4-8 lines)", "theme": theme}))
        for era in eras[1:]:
            attempts.append((fmt, {"length": "Short (4-8 lines)", "theme": theme, "era": era}))
        for poet in PUBLIC_DOMAIN_POETS.get(fmt, []):
            attempts.append((fmt, {"length": "Short (4-8 lines)", "theme": theme, "poet": poet}))
    # A theme filter can find nothing at all (2026-10-23: "tanhai" -- six empty searches,
    # the storm reel failed): the same eras with no theme come second, so a reel always
    # gets real lines, picked for the mood by the finder's own scoring.
    untheme = [(fmt, {"length": "Short (4-8 lines)", "era": f["era"]}) for fmt, f in attempts if "era" in f]
    attempts = attempts[:1] + untheme[:1] + attempts[1:] + untheme[1:]
    for fmt, filters in attempts[:MAX_FIND_ATTEMPTS]:
        label = filters.get("poet") or filters.get("era") or filters.get("theme")
        say(f"Finding real lines ({fmt}, {label})")
        found = shorts_desk.find(channel, fmt, filters, count=3, progress=say)
        cands = found.get("candidates") or []
        if not cands:
            errors.append(found.get("error") or f"{fmt}/{label}: nothing found")
        # Candidates already come back sorted by score (most relatable/emotional
        # first); the first one with a whole couplet in a usable script wins.
        for cand in cands:
            text = cand.get("text") or ""
            if is_urdu_script(text):
                continue
            lines = take_lines(text)
            if lines:
                return {"lines": lines, "poet": cand.get("poet", ""), "poet_died": cand.get("poet_died"),
                        "title": cand.get("best_title") or cand.get("title") or "", "format": fmt,
                        "source_url": cand.get("source_url", ""), "rights": cand.get("rights"),
                        "verdict": cand.get("verdict"), "score": cand.get("score")}
        if cands:
            errors.append(f"{fmt}/{label}: no candidate with a whole couplet in a usable script")
    raise RuntimeError("No lines for the mood reel: " + " | ".join(errors[-6:]))


# --- Hinglish transliteration (2026-10-23 night rules, VR7) ---------------------------------

def _parse_lines_payload(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    text = re.sub(r"^```[a-zA-Z]*\s*|\s*```\s*$", "", raw.strip()).strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if isinstance(data, dict):
        lines = data.get("lines")
        return lines if isinstance(lines, list) else None
    return data if isinstance(data, list) else None


def transliterate_lines(lines: List[str]) -> "tuple[List[str], bool]":
    """Devanagari couplet lines -> natural, casual Hinglish (Roman letters),
    one LLM call through the Studio's normal LLM service (JSON list in ->
    list out; same count, every line non-empty, no Devanagari left); one
    retry; on failure the given lines come back unchanged and `False`
    records it. A line already in Roman script is returned as it is --
    nothing to call the model for."""
    if not lines or not _DEVANAGARI_RE.search(" ".join(lines)):
        return lines, True
    from integrations.llm import LLMService, LLMUnavailable
    system_prompt = (
        "Transliterate each given Hindi/Urdu line (Devanagari) into natural, "
        "casual Hinglish -- the same words, in Roman letters, the way a young "
        "Indian would text them. Do not translate the meaning, do not add or "
        "drop lines, keep the same order. Reply with ONLY one JSON object: "
        '{"lines": ["<one Hinglish line per input line>"]}.')
    user_prompt = json.dumps({"lines": lines}, ensure_ascii=False)
    llm = LLMService(purpose="production")
    for _attempt in range(2):
        try:
            raw = llm.generate_text(system_prompt, user_prompt, require_json=True)
        except LLMUnavailable:
            break
        except Exception as exc:
            logger.warning("Transliteration call failed: %s", str(exc)[:200])
            continue
        out = _parse_lines_payload(raw)
        if (isinstance(out, list) and len(out) == len(lines)
                and all(isinstance(t, str) and t.strip() for t in out)
                and not any(_DEVANAGARI_RE.search(t) for t in out)):
            return [t.strip() for t in out], True
        logger.warning("Transliteration returned an unusable answer (attempt)")
    logger.warning("Transliteration unusable after retry; keeping Devanagari for %d line(s)", len(lines))
    return lines, False


# --- shots, cards and the plan -----------------------------------------------------------

def strip_banned(text: str) -> str:
    text = _BANNED_RE.sub("", str(text or ""))
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"([,;:])\s*(?=[,;:.])", "", text)
    return re.sub(r"\s{2,}", " ", text).strip(" ,;:")


def _norm(line: Any) -> str:
    return re.sub(r"\s+", " ", str(line or "")).strip()


def _couplets(lines: List[str]) -> List[str]:
    """The real lines as whole couplets, each `"line1\\nline2"`: one text card."""
    lines = [_norm(l) for l in lines if _norm(l)]
    return ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2) if lines[i:i + 2]]


def _cards(couplets: List[str], seconds: float, script: str) -> List[Dict[str, Any]]:
    """1-2 cards spread evenly across the reel, `CARD_LEAD_S` before the first
    and `CARD_TAIL_S` after the last. `script` is BuzzEdit's per-line field
    (it would auto-detect the same way, but the Studio already knows it --
    and already kept Urdu script out at `find_lines`)."""
    n = len(couplets)
    window = max(1.0, seconds - CARD_LEAD_S - CARD_TAIL_S)
    per = window / n
    return [{"text": text, "start_s": round(CARD_LEAD_S + i * per, 2), "end_s": round(CARD_LEAD_S + (i + 1) * per, 2),
            "script": script} for i, text in enumerate(couplets)]


def validate_plan(plan: Optional[Dict[str, Any]], lines: List[str], seconds: float,
                  poet: str = "", display_lines: Optional[List[str]] = None) -> Dict[str, Any]:
    """1-3 shots (2026-10-23 night rules, VR7: "fewer cuts... one long shot
    is ideal" -- supersedes the earlier 4-6 floor), every one "video"
    (2026-10-23 day: hyper-realistic AI motion, not a mostly-still reel --
    reel_hq, see `vibe_body`), seconds within 10% of `seconds` (rescaled if
    not, each kept within `SHOT_MIN_S`-`SHOT_MAX_S`), no camera words, 1-2
    couplet cards timed across the reel, credit on the last. Repairs what it
    can (a missing kind, an uneven total); raises when the plan is unusable.

    `display_lines` (2026-10-23 night rules, VR7), when given, is what the
    cards actually show -- the Hinglish transliteration of `lines`, in Roman
    script regardless of what `lines` itself is in -- while `lines` (the
    original, possibly Devanagari) still frames the shots. None (the
    default) keeps the old behaviour: the cards show `lines` as they are,
    script auto-detected."""
    if not isinstance(plan, dict):
        raise ValueError("The planner returned no plan.")
    world = strip_banned(plan.get("world") or "")
    if not world:
        raise ValueError("The plan has no world.")
    shots: List[Dict[str, Any]] = []
    for s in plan.get("shots") or []:
        if not isinstance(s, dict):
            continue
        prompt = strip_banned(s.get("prompt") or s.get("image_prompt") or "")
        motion = strip_banned(s.get("motion") or s.get("video_prompt") or "")
        if not prompt and not motion:
            continue
        prompt = prompt or motion
        try:
            secs = float(s.get("seconds") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        # Every shot is "video" (2026-10-23: the creator wants hyper-realistic
        # AI motion, not a mostly-still reel) -- whatever `kind` the planner
        # wrote (or omitted) is repaired here rather than failing the plan.
        shots.append({"prompt": prompt, "motion": motion or prompt, "seconds": secs, "kind": "video"})
    shots = shots[:MAX_SHOTS]
    if len(shots) < MIN_SHOTS:
        raise ValueError(f"The plan has {len(shots)} usable shot(s); a mood reel needs {MIN_SHOTS}-{MAX_SHOTS}.")
    for s in shots:
        if s["seconds"] <= 0:
            s["seconds"] = seconds / len(shots)
        s["seconds"] = max(SHOT_MIN_S, min(SHOT_MAX_S, s["seconds"]))
    total = sum(s["seconds"] for s in shots)
    rescaled = abs(total - seconds) > 0.10 * seconds
    if rescaled:
        for s in shots:
            s["seconds"] = s["seconds"] * seconds / total
    for s in shots:
        s["seconds"] = round(s["seconds"], 2)
    shown = display_lines if display_lines is not None else lines
    couplets = _couplets(shown)
    if not couplets:
        raise ValueError("The plan has no lines to show.")
    script = "roman" if display_lines is not None else script_of(lines)
    cards = _cards(couplets, seconds, script)
    bed = plan.get("bed") if isinstance(plan.get("bed"), dict) else {}
    return {"world": world, "shots": [{k: s[k] for k in ("prompt", "motion", "seconds", "kind")} for s in shots],
            "cards": cards, "credit": f"— {poet}" if poet else None, "bed": bed, "rescaled": rescaled}


def plan_shots(lines: List[str], theme: str, mood: str, seconds: float, style: str, channel: str,
               poet: str = "", display_lines: Optional[List[str]] = None) -> Dict[str, Any]:
    from app.services import shorts_desk
    task = {"lines": lines, "mood": MOODS.get(mood, (mood,))[0], "theme": THEMES.get(theme, {}).get("world", theme),
            "seconds": round(seconds), "style": style, "channel": channel}
    raw = shorts_desk._agent_json("MoodReelPlanner", task)
    return validate_plan(raw, lines, seconds, poet, display_lines=display_lines)


# --- music, ambience and the BuzzEdit request --------------------------------------------

def music_for(bed: Optional[Dict[str, Any]], mood: str) -> Dict[str, Any]:
    """The planner's bed as BuzzEdit's generated-music brief: `{brief, bpm}`."""
    bed = bed if isinstance(bed, dict) else {}
    instruments = [str(i) for i in (bed.get("instruments") or []) if str(i).strip()][:4] or ["santoor", "rain"]
    try:
        bpm = int(float(bed.get("bpm") or 60))
    except (TypeError, ValueError):
        bpm = 60
    bpm = max(50, min(80, bpm))
    feel = str(bed.get("mood") or MOODS.get(mood, (mood,))[0]).strip()
    brief = f"soothing {feel}, {', '.join(instruments)}, soft and slow, instrumental, no vocals"
    return {"brief": " ".join(brief.split())[:300], "bpm": bpm}


def ambience_for(theme: str) -> List[Dict[str, Any]]:
    """The theme's own quiet sound bed (rain, wind, crickets, far thunder ...),
    well under the music (the creator's -18..-22 dB ask)."""
    sounds = THEMES.get(theme, {}).get("ambience") or []
    return [{"prompt": s, "gain_db": AMBIENCE_GAIN_DB} for s in sounds[:2]]


#: Said in every reel's world, whatever the planner wrote (his first look, 2026-10-23:
#: the houses came out European; the moonlight reel's planner then wrote "dawn" and
#: dropped "Indian", so the theme's own world now always leads).
INDIA_ANCHOR = "set in India, Indian architecture and people's homes, never European"


def reel_world(theme: str, planned: str) -> str:
    """The theme's world first (time of day, place), then the planner's detail, then India."""
    base = THEMES.get(theme, {}).get("world", "")
    parts = [p for p in (base, planned, INDIA_ANCHOR) if p]
    return "; ".join(parts)


def vibe_body(out_dir: str, name: str, style: str, theme: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    """The exact `POST /api/reels/vibe` body (BuzzEdit's `VibeReelRequest`,
    REELS_DESK_PLAN.md §6 VR1): each card already carries its own `script`
    (set by `validate_plan`); there is no top-level one. `quality: "reel_hq"`
    (2026-10-23): every shot is now a video, so Life3Baje's AI clips must be
    the hyper-realistic graph, not stock-footage-looking generation. `music`
    is always None (2026-10-24, VR8): the tool adds no AI music to a mood
    reel -- the creator adds a real song himself in the Instagram app, over
    the soft scene ambience BuzzEdit still renders."""
    return {"out_dir": out_dir, "name": name, "art_style": style, "world": reel_world(theme, plan["world"]),
            "quality": "reel_hq", "shots": plan["shots"],
            "lines": plan["cards"], "credit": plan.get("credit"), "music": None, "ambience": ambience_for(theme),
            "font": None}


def package(lines: List[str], poet: str, hinglish_lines: Optional[List[str]] = None) -> Dict[str, Any]:
    """The Short package the Instagram caption is read from. `caption.txt` ==
    the Hinglish lines, a blank line, the Devanagari original, the credit,
    hashtags (2026-10-23 night rules, VR7) -- when `hinglish_lines` differs
    from `lines` (a real transliteration happened); when it is the same (the
    lines were already Roman, or the transliteration fell back) the original
    is shown just once, as before."""
    shown = hinglish_lines or lines
    caption = "\n".join(shown)
    if hinglish_lines and hinglish_lines != lines:
        caption += "\n\n" + "\n".join(lines)
    caption += f"\n\n— {poet}" if poet else ""
    return {"title": (shown[0] if shown else "Life3Baje")[:90], "caption": caption,
            "hook_line": shown[0] if shown else "",
            "hashtags": ["#khayal3bajefeels", "#shayari", "#ghazal", "#poetry", "#hindipoetry", "#urdupoetry", "#reels"],
            "poet": poet}
