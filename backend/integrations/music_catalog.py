"""The background-music vocabulary the Studio shares: the Music page's
builder (while BuzzEdit is offline), the per-project music brief, and the
planner prompt that teaches agents to write `[music: ...]` cues.

Mirrors BuzzEdit's presentation/music_gen.py -- the two repos share no code,
so this copy is kept in step by hand (a test pins the engine names).
"""
from typing import Any, Dict

# Shown while BuzzEdit starts, and merged into an older BuzzEdit's answer.
FALLBACK_CATALOG: Dict[str, Any] = {
    "default_engine": "ace_step",
    "engines": [
        {"name": "ace_step", "label": "ACE-Step", "model": "ACE-Step v1 3.5B",
         "license": "Apache-2.0", "max_seconds": 240.0, "ready": False,
         "note": "Full-length beds up to 4 min, best for whole-video music."},
        {"name": "stable_audio", "label": "Stable Audio Open", "model": "Stable Audio Open 1.0",
         "license": "Stability AI Community Licence", "max_seconds": 47.0, "ready": False,
         "note": "Short loops and stingers up to 47 s, for intros, transitions and Shorts."},
    ],
    "music_genres": [
        "cinematic", "orchestral", "ambient", "lo-fi", "hip hop", "trap", "electronic", "edm",
        "synthwave", "pop", "rock", "acoustic", "jazz", "classical", "piano solo",
        "indian classical", "bollywood", "sufi", "indian folk", "devotional",
    ],
    "instruments": {
        "Keys": ["piano", "electric piano", "synth pads", "organ", "harmonium"],
        "Strings": ["violin", "cello", "string section", "acoustic guitar", "electric guitar",
                    "bass guitar", "sitar", "sarangi", "santoor", "ukulele"],
        "Wind & brass": ["bansuri flute", "flute", "shehnai", "saxophone", "trumpet", "brass section"],
        "Percussion": ["tabla", "dholak", "dhol", "drums", "taiko drums", "808 bass", "claps"],
        "Texture": ["choir", "tanpura drone", "bells", "synth arpeggio", "vinyl crackle"],
    },
    "moods": {
        "calm": "calm", "peaceful": "calm", "dreamy": "calm",
        "sad": "soft", "romantic": "soft", "nostalgic": "soft",
        "happy": "upbeat", "hopeful": "upbeat", "playful": "upbeat", "energetic": "upbeat",
        "dark": "tense", "eerie": "tense", "mysterious": "tense", "suspenseful": "tense",
        "epic": "intense", "dramatic": "intense", "aggressive": "intense", "triumphant": "intense",
    },
    "bpm_range": [50, 180],
    "video_genres": sorted([
        "comedy", "cooking", "devotional", "documentary", "finance", "gaming", "general",
        "geopolitics", "health_fitness", "horror", "motivational", "mystery", "news",
        "science_education", "tech", "travel", "true_crime", "vlog",
    ]),
    "max_seconds": 240.0,
    "max_variations": 6,
}


# The Music page's presets (BuzzEdit's MUSIC_STYLES keys), for the planner.
STYLE_PRESETS = (
    "horror_dark", "horror_climax", "suspense", "true_crime", "sad_violin",
    "morning_raga_flute", "happy_flute", "cinematic_epic", "dramatic", "motivational",
    "lofi_calm", "tech_minimal", "comedy_playful", "devotional_calm",
)


def prompt_section() -> str:
    """How a planner writes music cues, with the vocabulary BuzzEdit understands."""
    instruments = sorted({i for items in FALLBACK_CATALOG["instruments"].values() for i in items})
    return "\n".join([
        "### Music cues (`music_cue` beats -> `[music: ...]` in the script)",
        "Background music is instrumental and generated for this video. Plan WHERE it changes and WHAT it "
        "is: one `music_cue` beat on the opening line, then one at each real shift of feeling (the build, "
        "the reveal, the turn, the ending) -- usually 2-5 per video, never closer than ~40 seconds apart. "
        "`music` is a short ENGLISH description: 1-2 instruments + a mood (+ genre, + tempo in bpm when it "
        "matters), e.g. \"sad solo violin, 70 bpm\", \"dark ambient, tanpura drone, eerie\", "
        "\"lo-fi, electric piano, calm, 85 bpm\". Instruments you name lead the track. "
        "`off` gives silence from that point (a dramatic pause, a confession).",
        f"Instruments: {', '.join(instruments)}.",
        f"Genres: {', '.join(FALLBACK_CATALOG['music_genres'])}.",
        f"Moods: {', '.join(FALLBACK_CATALOG['moods'])}.",
        f"Presets (may be named instead): {', '.join(STYLE_PRESETS)}.",
        "Follow the channel's Music direction below when one is given.",
    ])


def channel_music_section(brand: str) -> str:
    """The `## Music` section of the brand's channel guide, or ""."""
    import os
    import re
    from core.paths import CHANNELS_DIR
    path = os.path.join(CHANNELS_DIR, f"{(brand or '').replace(' ', '').strip()}.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    match = re.search(r"^## Music\b.*?(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(0).strip() if match else ""


def planner_direction(project: Any) -> str:
    """What the visual planner is told about this video's music: nothing to
    plan when music is off (or script cues are), else the channel's music
    direction and the creator's own brief, if set."""
    from integrations.buzzedit_settings import resolve_settings
    settings, _ = resolve_settings(project.brand, None, project)
    if settings.get("music") is False:
        return "### This video's music\nMusic is OFF for this video: plan no `music_cue` beats."
    if settings.get("music_tracks"):
        return ("### This video's music\nThe creator picked this video's music tracks and their levels: "
                "plan no `music_cue` beats.")
    if settings.get("music_cues") is False:
        return ("### This video's music\nScript music cues are off for this video: "
                "plan no `music_cue` beats.")
    lines = ["### This video's music"]
    section = channel_music_section(project.brand)
    if section:
        lines.append(section.replace("## Music", "Channel music direction:", 1))
    brief = str(settings.get("music_brief") or "").strip()
    if brief:
        lines.append(f"The creator chose this video's music: \"{brief}\". It plays from the opening; "
                     "add a `music_cue` only where the feeling clearly changes, in keeping with it.")
    return "\n".join(lines) if len(lines) > 1 else ""
