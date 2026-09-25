"""
Brand -> BuzzEdit `PresentationSettings`, with a per-call override.

BuzzcafAI's brands carry a voice/tone identity but nothing comparable to
BuzzEdit's rendering-time `genre` (its B-roll heuristics key off it) -- this
is the one, deliberately small, place that bridges the two vocabularies.
Field names below are copied from `BuzzEdit/backend/presentation/models.py`
(`PresentationSettings`); it has no `ConfigDict`, so an unknown key would be
silently ignored rather than a 422, but sending only real fields is better
hygiene than relying on that.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Overridable brand -> BuzzEdit genre map (source plan's "Interchange
# schema" / "Build - BuzzcafAI" §3).
_BRAND_GENRE = {
    "beyond3baje": "documentary",
    "raat3baje": "horror",
    "khayal3baje": "horror",
    "life3baje": "general",
    "originals": "general",
}


def _brand_key(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (brand or "").lower())


def settings_for_brand(brand: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A `PresentationSettings`-shaped dict for `brand`, with `overrides`
    (a per-video style override from the produce_video caller) merged in last.

    Kept deliberately small: it does not read `prompts/channels/<Brand>.md`
    through an LLM call for extra hints -- that would turn a fast, synchronous
    settings mapper into a model round-trip. An unrecognised brand defaults to
    the "general" genre rather than raising.
    """
    genre = _BRAND_GENRE.get(_brand_key(brand), "general")
    return _settings_for_genre(genre, overrides)


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


def fx_palette_for(brand: str, genre: Optional[str] = None) -> tuple:
    """Recommended effect names for a brand (or an explicit genre override)."""
    name = (genre or _BRAND_GENRE.get(_brand_key(brand), "general")).lower()
    name = _GENRE_ALIASES.get(name, name)
    return _GENRE_FX.get(name, _GENRE_FX["general"])


def _settings_for_genre(genre: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "genre": genre,
        # BuzzEdit clamps target_coverage to [0.0, 0.80] and video_broll_share
        # to [0.0, 0.5]; these defaults sit comfortably inside both.
        "target_coverage": 0.6,
        "video_broll_share": 0.18,  # kept low -- Wan 2.2 i2v costs minutes per clip
        "atmosphere": "auto",
        "grade": "auto",
        "broll": True,
        "broll_video": True,
        "thumbnail": True,
        "render": True,
    }
    base.update(overrides or {})
    return base
