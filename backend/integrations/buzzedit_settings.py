"""
Brand -> BuzzEdit `PresentationSettings`, with a per-call override.

BuzzcafAI's brands carry a voice/tone identity but nothing comparable to
BuzzEdit's rendering-time `genre` (its B-roll heuristics key off it) -- this
is the one, deliberately small, place that bridges the two vocabularies.
Field names below are copied from `BuzzEdit/backend/presentation/models.py`
(`PresentationSettings`); it has no `ConfigDict`, so an unknown key would be
silently ignored rather than a 422, but sending only real fields is better
hygiene than relying on that.

Settings resolve in five layers, each overriding the last:

    built-in base -> its density preset -> Studio-wide switches (Pixabay)
    -> the brand's channel profile -> the project's saved `video_settings`
    -> the request's `settings_override`

A layer that sets `density` re-expands that density's numeric preset before
its own explicit fields are applied, so an explicit field in that same layer
still wins over the preset it just introduced.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any, Dict, Optional, Tuple

from core.paths import CONFIG_DIR
from integrations.art_style import ART_STYLES, text_cards as _art_text_cards

# BuzzEdit's own genre vocabulary (`presentation/genre.py`), copied literally
# for the same reason `buzzedit_script.py` copies `_DIRECTIVES`: the two repos
# share no dependency apart from `buzzcaf_ports.py`.
GENRES: Tuple[str, ...] = (
    "general", "horror", "true_crime", "comedy", "gaming", "tech", "science_education",
    "finance", "motivational", "health_fitness", "cooking", "travel", "devotional",
    "news", "vlog", "documentary", "mystery", "geopolitics",
)

DENSITIES: Tuple[str, ...] = ("calm", "balanced", "busy", "max")

VOICE_PRESETS: Tuple[str, ...] = (
    "studio_mic", "broadcast", "warm_radio", "rap_vocal", "crisp_bass", "horror_intimate",
    "clean", "podcast", "light",
)

# density -> the numeric fields it implies (source plan's density table).
_DENSITY_PRESETS: Dict[str, Dict[str, Any]] = {
    "calm": {
        "target_coverage": 0.30, "video_broll_share": 0.10,
        "broll_seconds_min": 3.0, "broll_seconds_max": 5.0,
        "min_oncamera_gap_s": 1.5, "zoom_depth": 0.08,
        "punch_rate_per_minute": 1.0, "text_fx_per_minute": 1.0,
    },
    "balanced": {
        "target_coverage": 0.50, "video_broll_share": 0.20,
        "broll_seconds_min": 3.0, "broll_seconds_max": 5.0,
        "min_oncamera_gap_s": 1.0, "zoom_depth": 0.10,
        "punch_rate_per_minute": 1.5, "text_fx_per_minute": 2.0,
    },
    "busy": {
        "target_coverage": 0.65, "video_broll_share": 0.30,
        "broll_seconds_min": 3.0, "broll_seconds_max": 5.0,
        "min_oncamera_gap_s": 0.8, "zoom_depth": 0.12,
        "punch_rate_per_minute": 2.5, "text_fx_per_minute": 3.0,
    },
    "max": {
        "target_coverage": 0.80, "video_broll_share": 0.45,
        "broll_seconds_min": 3.0, "broll_seconds_max": 5.0,
        "min_oncamera_gap_s": 0.6, "zoom_depth": 0.14,
        "punch_rate_per_minute": 3.5, "text_fx_per_minute": 4.5,
    },
}

# Where the one-source-of-truth channel profile table lives. A module-level
# path (not a constant baked into the loader) so a test can monkeypatch it to
# a throwaway file instead of touching the real config directory.
CHANNEL_PROFILES_PATH = os.path.join(CONFIG_DIR, "channel_profiles.json")

_DEFAULT_PROFILE: Dict[str, Any] = {
    "genre": "general", "genre_secondary": None, "density": "balanced", "voice_preset": "studio_mic",
}

# Where every video starts (the creator's call, 2026-10-08: 199 clips on one
# 25-minute story was too many): 30% of the running time generated video, 55%
# still images, 15% his face. Applied after the channel and style layers, so a
# project's own sliders still win -- and the sliders can be moved while a
# render runs (produce_api.push_live_settings).
MIX_DEFAULTS: Dict[str, Any] = {"video_broll_share": 0.3, "image_broll_share": 0.55}

# Seeded once at import if the file does not exist yet; afterwards the file on
# disk is the source of truth (GET/PUT read and write it directly).
# Auto-edit pacing a channel profile may carry (`auto_edit: {...}`), forwarded
# to BuzzEdit's transcribe call. Keys are BuzzEdit's own field names:
#   max_pause_seconds     -- a pause longer than this is trimmed
#   pause_padding_seconds -- room kept either side of every cut
#   fumble_aggressiveness -- 0..1, how many ambiguous fumbles to cut
AUTO_EDIT_FIELDS: Dict[str, Tuple[float, float]] = {
    "max_pause_seconds": (0.1, 5.0),
    "pause_padding_seconds": (0.0, 1.0),
    "fumble_aggressiveness": (0.0, 1.0),
}

_SEED_PROFILES: Dict[str, Dict[str, Any]] = {
    # Pacing measured from the creator's reference cut of ep1 (2026-09-26):
    # no pause over ~1.1s survives, ~0.35s of room either side of a cut.
    "life3baje": {"genre": "vlog", "genre_secondary": "motivational", "density": "busy", "voice_preset": "studio_mic",
                  "auto_edit": {"max_pause_seconds": 1.0, "pause_padding_seconds": 0.35}},
    "raat3baje": {"genre": "horror", "genre_secondary": "mystery", "density": "busy", "voice_preset": "horror_intimate",
                  "visual_style": "story"},
    "khayal3baje": {"genre": "horror", "genre_secondary": "mystery", "density": "busy", "voice_preset": "horror_intimate",
                    "visual_style": "story"},
    "beyond3baje": {"genre": "documentary", "genre_secondary": "mystery", "density": "busy", "voice_preset": "broadcast",
                    "visual_style": "story"},
    "originals": {"genre": "general", "genre_secondary": None, "density": "balanced", "voice_preset": "studio_mic"},
    # TheTallStoryteller (2026-10-23): narrated, every genre, no face -- the
    # same "story" visual rule as the other story channels (pictures and
    # videos only, same characters, calm storyboard order), chosen here
    # because it is narrated world-building exactly like them, not because
    # it is horror. Not in FACE_LED_STORY_CHANNELS below: it has no face at all.
    "thetallstoryteller": {"genre": "general", "genre_secondary": None, "density": "balanced",
                           "voice_preset": "warm_radio", "visual_style": "story"},
}

# A profile's `visual_style` (absent = "full"):
#   full  -- everything BuzzEdit can dress a video with: captions, title,
#            cards, text effects, newspapers, sound effects, mood hits.
#   story -- pictures and videos only, told calmly (the creator's call,
#            2026-10-02, for the story channels): no captions, headings,
#            cards, newspaper/case-file cutaways, text effects, zoom punches
#            (back on, gently, for the face-led channels below), whooshes,
#            ambience or flash/shake hits; half of the cutaways are
#            generated video, each held 5-8 s. The music bed stays, and so do
#            the scene's own sounds the planners cue (`sfx_diegetic`, since
#            2026-10-09: footsteps, rain, a shout) -- `sfx` keeps only the
#            whoosh/pop/stinger hits off. Any field can still be turned back
#            on per project or per request, since those layers apply after
#            this one.
VISUAL_STYLES: Tuple[str, ...] = ("full", "story")

# The art style (2026-10-21, `integrations/art_style.py`): the medium the
# pictures, clips, thumbnail scene and text cards are made in -- real
# (photoreal, the default), explainer, stick_figure or cartoon. A separate
# axis from the visual style: it says HOW things are drawn, the visual style
# says WHICH layers exist. Resolved through the same layers (channel profile
# -> project -> request) and sent to BuzzEdit as `art_style`.
#
# A drawn style whose medium includes short text (explainer, stick figure)
# brings these layers back on a story channel, right after the story layer,
# so a project or request can still turn any of them off.
ART_TEXT_SETTINGS: Dict[str, Any] = {
    "popups": True, "cards": True, "chapter_titles": True, "stat_callouts": True,
    "definition_cards": True, "quote_cards": True,
}
# A drawn style on a full-style channel that keeps text off (cartoon) leaves
# the full layers alone: the visual style owns them.

STORY_STYLE_SETTINGS: Dict[str, Any] = {
    "captions": False, "title": False, "popups": False, "graphics": False,
    "cards": False, "chapter_titles": False, "end_screen": False,
    "location_cards": False, "character_cards": False, "stat_callouts": False,
    "source_cards": False, "definition_cards": False, "quote_cards": False,
    "maps": False, "split_screens": False, "newspapers": False, "case_files": False,
    "freeze_on_stats": False, "pip": "off", "text_fx": False,
    "face_zoom": False, "punch_rate_per_minute": 0.0, "text_fx_per_minute": 0.0,
    "atmosphere": "off", "mood_hits": False,
    "sfx": False, "sfx_diegetic": True, "ambience": False,
    "video_broll_share": 0.3, "image_broll_share": 0.55,
    "broll_seconds_min": 5.0, "broll_seconds_max": 8.0,
}

# The story channels the creator presents on camera. Their face footage keeps
# BuzzEdit's slow push-in on every take and a gentle punch-in about once a
# minute (2026-10-03: a Raat3Baje cut with the zooms off played flat); the
# animated Khayal3Baje has no face to zoom. Applied right after the story
# style, so a project or request can still turn the zooms off.
FACE_LED_STORY_CHANNELS: Tuple[str, ...] = ("raat3baje", "beyond3baje")
# zoom_depth 0.14 since 2026-10-08: at 0.08 (jittered 0.06-0.10) under 85%
# cutaway coverage the ep2 render read as having no zoom at all.
FACE_LED_STORY_SETTINGS: Dict[str, Any] = {
    "face_zoom": True, "punch_rate_per_minute": 1.0, "zoom_depth": 0.14,
}

_profiles_lock = threading.Lock()


def _brand_key(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def brand_key(brand: str) -> str:
    """Public alias of `_brand_key` -- the brand-name normaliser other
    modules (e.g. `produce_api`'s transcription `glossary`) also need."""
    return _brand_key(brand)


def _load_channel_profiles() -> Dict[str, Dict[str, Any]]:
    """The channel-profiles table, seeding the file with the defaults the
    first time it is read. Re-reads from disk on every call (small file,
    rarely read) so a PUT from another request is visible immediately."""
    with _profiles_lock:
        if not os.path.exists(CHANNEL_PROFILES_PATH):
            os.makedirs(os.path.dirname(CHANNEL_PROFILES_PATH), exist_ok=True)
            with open(CHANNEL_PROFILES_PATH, "w", encoding="utf-8") as f:
                json.dump(_SEED_PROFILES, f, indent=2, ensure_ascii=False)
            return {k: dict(v) for k, v in _SEED_PROFILES.items()}
        try:
            with open(CHANNEL_PROFILES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {k: dict(v) for k, v in _SEED_PROFILES.items()}


def _save_channel_profiles(profiles: Dict[str, Dict[str, Any]]) -> None:
    with _profiles_lock:
        os.makedirs(os.path.dirname(CHANNEL_PROFILES_PATH), exist_ok=True)
        with open(CHANNEL_PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)


def list_channel_profiles() -> Dict[str, Dict[str, Any]]:
    """Every known brand's profile, unknown brands excluded (the caller gets
    `_DEFAULT_PROFILE` for those from `get_channel_profile` on demand)."""
    return _load_channel_profiles()


def get_channel_profile(brand: str) -> Dict[str, Any]:
    """`brand`'s saved profile, or the general/balanced/studio_mic default
    for a brand nobody has configured yet."""
    profiles = _load_channel_profiles()
    profile = profiles.get(_brand_key(brand))
    return dict(profile) if profile else dict(_DEFAULT_PROFILE)


class InvalidChannelProfile(ValueError):
    """A channel-profile PUT named a genre or density BuzzEdit does not have."""


def clean_auto_edit(block: Any) -> Optional[Dict[str, float]]:
    """Validate a profile's `auto_edit` block: known keys only, numbers within
    `AUTO_EDIT_FIELDS` range. None/empty -> None. Raises `InvalidChannelProfile`."""
    if block is None:
        return None
    if not isinstance(block, dict):
        raise InvalidChannelProfile("auto_edit must be an object of BuzzEdit pacing fields.")
    cleaned: Dict[str, float] = {}
    for key, value in block.items():
        if key not in AUTO_EDIT_FIELDS:
            raise InvalidChannelProfile(
                f"Unknown auto_edit field: {key!r}. Must be one of {', '.join(AUTO_EDIT_FIELDS)}.")
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise InvalidChannelProfile(f"auto_edit.{key} must be a number.")
        low, high = AUTO_EDIT_FIELDS[key]
        if not (low <= number <= high):
            raise InvalidChannelProfile(f"auto_edit.{key} must be between {low} and {high}.")
        cleaned[key] = number
    return cleaned or None


def set_channel_profile(brand: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and persist `brand`'s profile. Raises `InvalidChannelProfile`
    on an unknown genre or density; the caller (the API route) turns that
    into a 400."""
    genre = profile.get("genre")
    genre_secondary = profile.get("genre_secondary")
    density = profile.get("density")
    voice_preset = profile.get("voice_preset") or _DEFAULT_PROFILE["voice_preset"]

    if genre not in GENRES:
        raise InvalidChannelProfile(f"Unknown genre: {genre!r}. Must be one of {', '.join(GENRES)}.")
    if genre_secondary is not None and genre_secondary not in GENRES:
        raise InvalidChannelProfile(f"Unknown genre_secondary: {genre_secondary!r}. Must be one of {', '.join(GENRES)}.")
    if density not in DENSITIES:
        raise InvalidChannelProfile(f"Unknown density: {density!r}. Must be one of {', '.join(DENSITIES)}.")

    cleaned = {"genre": genre, "genre_secondary": genre_secondary, "density": density, "voice_preset": voice_preset}
    profiles = _load_channel_profiles()
    # `visual_style`, like `auto_edit`, survives a PUT that leaves it out.
    if "visual_style" in profile and profile.get("visual_style") is not None:
        if profile["visual_style"] not in VISUAL_STYLES:
            raise InvalidChannelProfile(
                f"Unknown visual_style: {profile['visual_style']!r}. Must be one of {', '.join(VISUAL_STYLES)}.")
        cleaned["visual_style"] = profile["visual_style"]
    elif "visual_style" not in profile:
        saved_style = (profiles.get(_brand_key(brand)) or {}).get("visual_style")
        if saved_style:
            cleaned["visual_style"] = saved_style
    # `art_style` the same way: kept across a PUT that leaves it out.
    if "art_style" in profile and profile.get("art_style") is not None:
        if profile["art_style"] not in ART_STYLES:
            raise InvalidChannelProfile(
                f"Unknown art_style: {profile['art_style']!r}. Must be one of {', '.join(ART_STYLES)}.")
        cleaned["art_style"] = profile["art_style"]
    elif "art_style" not in profile:
        saved_art = (profiles.get(_brand_key(brand)) or {}).get("art_style")
        if saved_art in ART_STYLES:
            cleaned["art_style"] = saved_art
    # `auto_edit` is optional: a payload that omits it keeps what is saved
    # (the Settings page only edits the four style fields); an explicit
    # `null` clears it; anything else is validated key by key.
    if "auto_edit" in profile:
        auto_edit = clean_auto_edit(profile.get("auto_edit"))
    else:
        auto_edit = (profiles.get(_brand_key(brand)) or {}).get("auto_edit")
    if auto_edit:
        cleaned["auto_edit"] = auto_edit
    profiles[_brand_key(brand)] = cleaned
    _save_channel_profiles(profiles)
    return cleaned


def channel_visual_style(brand: str) -> str:
    """`brand`'s visual style: its saved profile's, else the seed table's (so
    a channel_profiles.json written before `visual_style` existed still gets
    the story look for the story channels), else "full"."""
    saved = get_channel_profile(brand).get("visual_style")
    if saved in VISUAL_STYLES:
        return saved
    return (_SEED_PROFILES.get(_brand_key(brand)) or {}).get("visual_style") or "full"


def is_story_style(settings: Dict[str, Any]) -> bool:
    return (settings or {}).get("visual_style") == "story"


def channel_art_style(brand: str) -> str:
    """`brand`'s art style: its saved profile's, else "real"."""
    saved = get_channel_profile(brand).get("art_style")
    return saved if saved in ART_STYLES else "real"


def art_style_of(settings: Dict[str, Any]) -> str:
    style = (settings or {}).get("art_style")
    return style if style in ART_STYLES else "real"


def _base_settings() -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        "visual_style": "full",
        "art_style": "real",
        "genre": "general",
        "genre_secondary": None,
        "density": "balanced",
        "voice_preset": "studio_mic",
        "voice_enhance": "auto",
        "sfx_source": "auto",
        # The scene's own sounds the planners cue (`[sfx: ...]`: footsteps,
        # rain), BuzzEdit's switch for them apart from `sfx` (the transition
        # hits). On for every channel.
        "sfx_diegetic": True,
        "music_source": "auto",
        "music": True,
        "music_brief": "",
        "music_cues": True,
        "music_engine": "ace_step",
        "music_tracks": [],
        "music_tracks_mode": "together",
        "allow_free_stock": False,
        "atmosphere": "auto",
        "grade": "auto",
        "broll": True,
        "broll_video": True,
        "thumbnail": True,
        "render": True,
        # No "Generative AI" corner tag on generated pictures and clips
        # (2026-10-08): the disclosure is made in YouTube's upload form, not
        # burnt into every cutaway.
        "ai_label": False,
        # How the creator's face is used (2026-10-16): "mixed" -- it comes
        # back between the pictures all through (the mix sliders); or
        # "face_intro" -- only his face for the first `face_intro_seconds`,
        # then pictures and clips to the end. Studio-side: story_visuals
        # times the shots, BuzzEdit gets `face_intro_s`.
        "face_layout": "mixed",
        "face_intro_seconds": 90,
    }
    settings.update(_DENSITY_PRESETS["balanced"])
    return settings


FACE_LAYOUTS: Tuple[str, ...] = ("mixed", "face_intro")


def _channel_face_layer(brand: str) -> Dict[str, Any]:
    """The channel's face layout default (Long-form panel / channel formats)."""
    try:
        from app.services.session_format import channel_defaults
        defaults = channel_defaults(brand)
    except Exception:  # noqa: BLE001 - settings unreadable: the base layer's
        return {}
    return {"face_layout": defaults.get("face_layout"), "face_intro_seconds": defaults.get("face_intro_seconds")}


def face_intro_seconds(settings: Dict[str, Any]) -> float:
    """Seconds of face-only opening for a face-first video, 0 for "mixed"."""
    if (settings or {}).get("face_layout") != "face_intro":
        return 0.0
    try:
        value = float(settings.get("face_intro_seconds") if settings.get("face_intro_seconds") is not None else 90)
    except (TypeError, ValueError):
        return 90.0
    # 0 is "no face at all" (2026-10-23: an auto story whose take has no
    # intro clip is pictures from the first frame); anything else is 10-300 s.
    if value <= 0:
        return 0.0
    return max(10.0, min(300.0, value))


def _studio_settings_layer() -> Dict[str, Any]:
    """Studio-wide switches that seed every project's defaults, applied right
    after the base layer so a channel profile, the project, or the request
    can still override them. Today that is Settings -> "Use Pixabay stock
    footage": with the switch on and a key saved, `allow_free_stock` starts
    True for every render (BuzzEdit then fills a beat ComfyUI could not make
    from Pixabay instead of leaving it blank)."""
    try:
        from integrations.llm import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001 - settings unreadable means no extra layer
        return {}
    layer: Dict[str, Any] = {}
    key = cfg.get("pixabay_api_key") or os.environ.get("PIXABAY_API_KEY")
    if cfg.get("pixabay_enabled") and key:
        layer["allow_free_stock"] = True
    return layer


def _apply_layer(settings: Dict[str, Any], layer: Optional[Dict[str, Any]],
                  name: str, sources: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """`settings` with `layer` merged in: a `density` in `layer` re-expands
    that preset's numbers first, then every non-None field in `layer`
    (including `density` itself, and any explicit numeric override sitting
    alongside it) is applied on top -- so an explicit field always wins over
    the preset its own layer just introduced."""
    if not layer:
        return settings
    settings = dict(settings)
    density = layer.get("density")
    if density in _DENSITY_PRESETS:
        for key, value in _DENSITY_PRESETS[density].items():
            settings[key] = value
            if sources is not None:
                sources[key] = name
    for key, value in layer.items():
        if value is not None:
            settings[key] = value
            if sources is not None:
                sources[key] = name
    return settings


def resolve_settings(
    brand: str, overrides: Optional[Dict[str, Any]] = None, project: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """The full layered resolution, plus which layer each field came from
    (`GET /api/projects/{id}/video_settings` shows this in the Studio UI)."""
    sources: Dict[str, str] = {}
    # The base layer populates every key -- including `genre_secondary: None`
    # -- outright, rather than through `_apply_layer`'s "skip a None value"
    # rule (that rule is for an override layer choosing not to touch a key,
    # not for the base layer that defines which keys exist at all).
    settings = dict(_base_settings())
    sources.update({key: "base" for key in settings})
    settings = _apply_layer(settings, _studio_settings_layer(), "studio_settings", sources)
    profile = get_channel_profile(brand)
    profile["visual_style"] = channel_visual_style(brand)
    settings = _apply_layer(settings, profile, "channel_profile", sources)
    settings = _apply_layer(settings, _channel_face_layer(brand), "channel_format", sources)
    project_layer = None
    if project is not None:
        metadata = getattr(project, "metadata", None) or {}
        project_layer = metadata.get("video_settings")
    # The style is decided by the most specific layer that names one, then
    # expanded right after the channel profile -- so a project can switch a
    # story channel back to "full" (and get BuzzEdit's defaults again), and
    # any single field a project or request sets (sfx back on, say) still
    # wins over the style, since those layers apply after it.
    style = profile["visual_style"]
    for layer in (project_layer, overrides):
        if layer and layer.get("visual_style") in VISUAL_STYLES:
            style = layer["visual_style"]
    if style == "story":
        settings = _apply_layer(settings, STORY_STYLE_SETTINGS, "visual_style", sources)
        if _brand_key(brand) in FACE_LED_STORY_CHANNELS:
            settings = _apply_layer(settings, FACE_LED_STORY_SETTINGS, "face_led", sources)
    # The art style, decided the same way (channel profile, then the most
    # specific layer that names one). A drawn style whose medium includes
    # short text puts the text cards back on a story channel; a drawn style
    # without text turns them off on a full one.
    art = channel_art_style(brand)
    art_source = "channel_profile" if art != "real" else "base"
    for layer, name in ((project_layer, "project"), (overrides, "request")):
        if layer and layer.get("art_style") in ART_STYLES:
            art, art_source = layer["art_style"], name
    settings["art_style"] = art
    sources["art_style"] = art_source
    wants_text = _art_text_cards(art)
    if wants_text is True and style == "story":
        settings = _apply_layer(settings, ART_TEXT_SETTINGS, "art_style", sources)
    elif wants_text is False and style != "story":
        settings = _apply_layer(settings, {key: False for key in ART_TEXT_SETTINGS}, "art_style", sources)
    settings = _apply_layer(settings, MIX_DEFAULTS, "mix_default", sources)
    settings = _apply_layer(settings, project_layer, "project", sources)
    settings = _apply_layer(settings, overrides, "request", sources)
    # A project (or request) that set BuzzEdit's coverage pair itself and no
    # image share keeps that older meaning: its video share is a share of the
    # coverage, not of the runtime (runtime_mix).
    if (sources.get("target_coverage") in ("project", "request")
            and sources.get("image_broll_share") not in ("project", "request")):
        settings.pop("image_broll_share", None)
        sources.pop("image_broll_share", None)
    # Free stock is real-world footage found by keyword: for fiction horror it
    # comes back as documentary photos that match neither the story nor the
    # genre (2026-10-01: 104 of 117 Raat3Baje visuals were Pixabay pictures of
    # ruined factories). The Studio-wide switch therefore does not reach these
    # genres; a project or a request can still turn stock on by name.
    if (settings.get("genre") in _NO_STOCK_GENRES and settings.get("allow_free_stock")
            and sources.get("allow_free_stock") == "studio_settings"):
        settings["allow_free_stock"] = False
        sources["allow_free_stock"] = "genre_rule"
    return settings, sources


_NO_STOCK_GENRES = {"horror"}


def settings_for_brand(brand: str, overrides: Optional[Dict[str, Any]] = None, project: Any = None) -> Dict[str, Any]:
    """A `PresentationSettings`-shaped dict for `brand`, resolved through the
    base -> density -> channel-profile -> project -> request layers above.

    Kept deliberately small: it does not read `prompts/channels/<Brand>.md`
    through an LLM call for extra hints -- that would turn a fast, synchronous
    settings mapper into a model round-trip. An unrecognised brand defaults to
    the "general" genre rather than raising.
    """
    settings, _ = resolve_settings(brand, overrides, project)
    return for_buzzedit(settings)


# ------------------------------------------------------------ the mix
#
# The creator sets three shares of the RUNNING TIME (2026-10-03): video clips,
# images (stills) and his face -- each up to 100%, filled in that order of
# priority, the face getting whatever is left. `image_broll_share` set on any
# layer (and every story-style video) means these numbers; a full-style
# channel that never set it keeps BuzzEdit's older pair -- `target_coverage`
# of the runtime, `video_broll_share` of that coverage -- untouched.

def _share(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def runtime_mix(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Video / images / face as shares of the running time, video first."""
    if settings.get("visual_style") == "story" or settings.get("image_broll_share") is not None:
        video = _share(settings.get("video_broll_share"))
        images = min(_share(settings.get("image_broll_share")), 1.0 - video)
        mode = "runtime"
    else:
        coverage = _share(settings.get("target_coverage"))
        video = coverage * _share(settings.get("video_broll_share"))
        images = coverage - video
        mode = "coverage"
    return {"video": round(video, 3), "images": round(images, 3),
            "face": round(max(0.0, 1.0 - video - images), 3), "mode": mode}


_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def achieved_mix(buzzedit_project: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """What the finished edit really is: generated clips and stills as shares
    of its running time, measured on BuzzEdit's timeline (cut-away media on
    the overlay tracks; the recording on V1 and full-length layers don't count)."""
    timeline = (buzzedit_project or {}).get("timeline") or {}
    try:
        fps = float(timeline["fps_num"]) / float(timeline["fps_den"])
        runtime = float(timeline["duration_frames"]) / fps
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if runtime <= 0:
        return None
    sources = timeline.get("sources") or []
    by_id = {s.get("id"): s for s in sources} if isinstance(sources, list) else dict(sources)
    clip_s = still_s = 0.0
    clips = stills = 0
    for item in timeline.get("items") or []:
        if item.get("kind") != "media" or item.get("track") == "V1" or not item.get("enabled", True):
            continue
        if item.get("origin") not in ("broll", "auto_broll", "generated"):
            continue
        source = by_id.get(item.get("source_id")) or {}
        path = str(source.get("path") or source.get("file") or "").lower()
        seconds = (float(item["timeline_end_frame"]) - float(item["timeline_start_frame"])) / fps
        if path.endswith(_VIDEO_EXTS):
            clip_s += seconds
            clips += 1
        elif path.endswith(_IMAGE_EXTS):
            still_s += seconds
            stills += 1
    return {"runtime_s": round(runtime, 1), "video": round(clip_s / runtime, 3), "images": round(still_s / runtime, 3),
            "clips": clips, "stills": stills, "video_s": round(clip_s, 1), "image_s": round(still_s, 1)}


def for_buzzedit(settings: Dict[str, Any]) -> Dict[str, Any]:
    """The resolved settings in BuzzEdit's terms. In runtime-mix mode its
    coverage is video + images; a full-style video's clip share becomes the
    clips' part of that coverage (BuzzEdit's meaning). A story video keeps
    the runtime shares: the Studio times its shots itself (story_visuals)."""
    mix = runtime_mix(settings)
    if mix["mode"] != "runtime":
        return settings
    out = dict(settings)
    coverage = round(min(1.0, mix["video"] + mix["images"]), 3)
    out["target_coverage"] = coverage
    out["image_broll_share"] = mix["images"]
    if out.get("visual_style") == "story":
        out["video_broll_share"] = mix["video"]
    else:
        out["video_broll_share"] = round(mix["video"] / coverage, 3) if coverage else 0.0
    return out


# Recommended effect names per genre — the BuzzcafAI-side mirror of BuzzEdit's
# `presentation/genre.py::_FX_PALETTE`. Fed into the visual-plan prompt so the
# model places `fx`/`atmos` beats that suit the video, and BuzzEdit renders them.
_GENRE_FX: Dict[str, tuple] = {
    "documentary": ("grain", "light_leak", "spotlight", "push", "newspaper", "map", "stat"),
    "horror": ("flicker", "shutter", "glitch", "fog", "shake", "flash", "vhs", "strobe"),
    "true_crime": ("grain", "redaction", "spotlight", "flicker", "case_file"),
    "mystery": ("grain", "flicker", "redaction", "spotlight", "shutter", "case_file"),
    "finance": ("push", "stat", "chart", "spotlight"),
    "geopolitics": ("grain", "spotlight", "push", "map", "newspaper"),
    "general": ("grain", "push"),
}

_GENRE_ALIASES = {
    "geopolitical": "geopolitics", "financial_documentary": "finance",
    "financial": "finance", "business": "finance", "crime": "true_crime",
}


def _fx_for_genre(genre: str) -> tuple:
    name = _GENRE_ALIASES.get((genre or "").lower(), (genre or "").lower())
    return _GENRE_FX.get(name, _GENRE_FX["general"])


def fx_palette_for(brand: str, genre: Optional[str] = None, genre_secondary: Optional[str] = None) -> tuple:
    """Recommended effect names for a brand (or explicit genre overrides),
    the primary genre's palette followed by the secondary's (deduplicated,
    order preserved). Omitted genres fall back to the brand's channel profile."""
    profile = get_channel_profile(brand)
    primary = genre or profile.get("genre") or "general"
    secondary = genre_secondary if genre_secondary is not None else profile.get("genre_secondary")
    palette = list(_fx_for_genre(primary))
    if secondary:
        for fx in _fx_for_genre(secondary):
            if fx not in palette:
                palette.append(fx)
    return tuple(palette)
