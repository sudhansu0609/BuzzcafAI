"""
The effect catalog: every visual effect the planner may call, in one place.

Each entry says what the effect looks like, when to use it, which fields it
needs, an exact example, and how it is written as a BuzzEdit directive. The
same table drives three things, so they cannot drift apart:

1. the planner's instructions (`prompt_section`) -- the model sees each kind
   with its fields and a worked example, not just a list of names;
2. repair and validation of what the model sends back (`normalize_beat`) --
   aliases resolved ("pills" -> `pill_labels`), fields coerced (a
   "A; B; C" string -> a list), limits enforced, and a beat that still
   cannot render is dropped with a reason instead of reaching BuzzEdit as a
   broken card;
3. the directive text BuzzEdit parses (`directive_for`), whose grammar is
   `BuzzEdit/backend/presentation/script.py::directive_beats` -- pinned by
   `tests/test_effect_catalog.py` against the exact strings BuzzEdit's own
   tests parse.

The designed graphics (statement cards, the canvas layout, pill labels, ...)
were added from two studied reference styles -- clean explainer edits and
documentary storytelling -- and work on every channel.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: Colour looks a generated still can take (BuzzEdit graphics.LOOKS).
LOOKS = ("bw", "noir", "sepia", "red_duotone", "blue_duotone", "warm", "cool")
#: One-shot transitions (BuzzEdit render/atmosphere.py).
TRANSITIONS = ("whiteflash", "glitch", "flash", "shutter")
DOCUMENT_FORMATS = ("web", "book")


def clean(value: Any) -> str:
    """One line, no `[`, `]` or `|` (all directive syntax)."""
    text = "" if value is None else str(value)
    text = text.replace("[", "(").replace("]", ")").replace("|", "/").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _data(beat: Dict[str, Any]) -> Dict[str, Any]:
    data = beat.get("data")
    return data if isinstance(data, dict) else {}


def _pick(beat: Dict[str, Any], *keys: str) -> Any:
    """First non-empty value among `keys`, on the beat or in its `data`."""
    data = _data(beat)
    for key in keys:
        for source in (beat, data):
            value = source.get(key)
            if value is not None and str(value).strip() != "":
                return value
    return None


def _as_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple)):
        items = [clean(v) for v in value]
    elif isinstance(value, str):
        items = [clean(v) for v in re.split(r"[;\n]|,(?=\s*\S)", value)]
    else:
        items = []
    return [i for i in items if i]


def _words(text: str) -> List[str]:
    return [w for w in re.split(r"\s+", text or "") if w]


def _truncate_words(text: str, n: int) -> str:
    words = _words(text)
    return " ".join(words[:n])


def _ensure_mark(text: str, marker: str) -> str:
    """`marker` ("*" or "==") around the longest word when the model forgot to
    highlight anything -- a statement or quote with no emphasis reads flat."""
    if marker in text:
        return text
    words = _words(text)
    if not words:
        return text
    core = max(words, key=lambda w: len(w.strip(".,!?;:"))).strip(".,!?;:")
    return text.replace(core, f"{marker}{core}{marker}", 1) if core else text


@dataclass
class Effect:
    kind: str
    directive: str
    group: str                      # "picture" | "layout" | "overlay" | "card" | "documentary" | "motion"
    summary: str
    use_when: str
    fields: Dict[str, str]          # required: field -> what to put there
    example: Dict[str, Any]
    optional: Dict[str, str] = field(default_factory=dict)
    aliases: Tuple[str, ...] = ()
    #: Seconds that must pass before this kind may appear again (`space_beats`).
    min_gap_s: float = 0.0
    #: beat -> (normalized beat or None, reason when None)
    normalize: Optional[Callable[[Dict[str, Any]], Tuple[Optional[Dict[str, Any]], str]]] = None
    #: normalized beat -> the directive's argument (the text after `kind: `)
    arg: Optional[Callable[[Dict[str, Any]], str]] = None


# --- normalizers (designed graphics) ------------------------------------------------------

def _norm_statement(beat):
    text = clean(_pick(beat, "text", "statement", "sentence") or beat.get("anchor"))
    if not text:
        return None, "statement_card needs `text`"
    beat["text"] = _ensure_mark(_truncate_words(text, 22), "*")
    return beat, ""


def _norm_canvas(beat):
    prompt = clean(_pick(beat, "image_prompt", "prompt"))
    if not prompt:
        return None, "canvas_card needs `image_prompt`"
    beat["image_prompt"] = prompt
    caption = clean(_pick(beat, "caption", "subtext"))
    beat["caption"] = caption[:48] if caption else ""
    look = str(_pick(beat, "look") or "").strip().lower()
    beat["look"] = look if look in LOOKS else ""
    return beat, ""


def _norm_pills(beat):
    items = _as_list(_pick(beat, "items", "labels", "chips", "pills", "text"))
    items = [i[:28] for i in items][:4]
    if len(items) < 2:
        return None, "pill_labels needs 2-4 `items`"
    beat["items"] = items
    return beat, ""


def _norm_point(beat):
    text = clean(_pick(beat, "text", "point"))
    if not text:
        return None, "numbered_point needs `text`"
    number = str(_pick(beat, "number", "n", "index") or "1").strip().rstrip(".")
    beat["number"] = number[:3] if number else "1"
    beat["text"] = _truncate_words(text, 9)
    return beat, ""


def _norm_name(beat):
    name = clean(_pick(beat, "text", "name"))
    if not name:
        return None, "name_title needs `text` (the name)"
    words = _words(name)
    capitalised = sum(1 for w in words if w[:1].isupper() or not w[:1].isalpha())
    if len(words) > 4 or capitalised * 2 < len(words):
        # "Main ek software engineer" is a sentence, not a name -- a real run
        # did exactly that; a statement or pill fits that line, a name title
        # does not.
        return None, "name_title `text` must be a person's name (1-4 capitalised words)"
    beat["text"] = name[:40]
    beat["subtext"] = clean(_pick(beat, "subtext", "role", "title"))[:48]
    return beat, ""


def _norm_source_quote(beat):
    source = clean(_pick(beat, "source", "site", "publication"))
    quote = clean(_pick(beat, "text", "quote"))
    if not quote:
        return None, "source_quote needs `text` (the cited sentence)"
    if not source:
        return None, "source_quote needs `source` -- never show an uncited quote"
    beat["source"] = source[:60]
    beat["text"] = _ensure_mark(_truncate_words(quote, 40), "==")
    beat["image_prompt"] = clean(beat.get("image_prompt"))
    return beat, ""


def _norm_document(beat):
    fmt = str(_pick(beat, "format", "type") or "web").strip().lower()
    beat["format"] = fmt if fmt in DOCUMENT_FORMATS else "web"
    title = clean(_pick(beat, "text", "title", "headline"))
    if not title:
        return None, "document needs `text` (the headline)"
    beat["text"] = title[:120]
    beat["subtext"] = _truncate_words(clean(_pick(beat, "subtext", "body", "excerpt")), 60)
    beat["site"] = clean(_pick(beat, "site", "source", "book"))[:60]
    if "==" not in beat["text"] + beat["subtext"]:
        beat["subtext" if beat["subtext"] else "text"] = _ensure_mark(
            beat["subtext"] or beat["text"], "==")
    return beat, ""


def _norm_timeline(beat):
    ticks = _as_list(_pick(beat, "ticks", "dates", "years"))
    if len(ticks) < 2:
        return None, "timeline needs 2+ `ticks`"
    ticks = ticks[:9]
    active = _pick(beat, "active")
    starred = [i for i, t in enumerate(ticks) if t.startswith("*")]
    ticks = [t.strip("*").strip() for t in ticks]
    try:
        index = int(active) if active is not None else (starred[0] if starred else len(ticks) - 1)
    except (TypeError, ValueError):
        index = starred[0] if starred else len(ticks) - 1
    beat["ticks"], beat["active"] = ticks, max(0, min(index, len(ticks) - 1))
    beat["text"] = clean(_pick(beat, "text", "headline", "value"))[:24]
    if not beat["text"]:
        return None, "timeline needs `text` (the big figure)"
    beat["subtext"] = clean(_pick(beat, "subtext", "caption"))[:60]
    return beat, ""


def _norm_transition(beat):
    effect = str(_pick(beat, "effect", "text") or "whiteflash").strip().lower().replace(" ", "")
    effect = {"white_flash": "whiteflash", "flashwhite": "whiteflash", "rgb_glitch": "glitch"}.get(effect, effect)
    if effect not in TRANSITIONS:
        return None, f"transition `effect` must be one of {', '.join(TRANSITIONS)}"
    beat["effect"] = effect
    return beat, ""


def _norm_broll_image(beat):
    prompt = clean(_pick(beat, "image_prompt", "prompt"))
    if not prompt:
        return None, "broll_image needs `image_prompt`"
    beat["image_prompt"] = prompt
    look = str(_pick(beat, "look") or "").strip().lower()
    beat["look"] = look if look in LOOKS else ""
    return beat, ""


# --- directive arguments -------------------------------------------------------------------

def _arg_statement(b):
    return clean(b["text"]) + ("" if b.get("with_speaker", True) not in (False, "false", "off") else " | speaker=off")


def _arg_canvas(b):
    parts = [clean(b["image_prompt"])]
    if b.get("caption"):
        parts.append(clean(b["caption"]))
    if b.get("look"):
        parts.append(f"look={b['look']}")
    if b.get("with_speaker", True) in (False, "false", "off"):
        parts.append("speaker=off")
    return " | ".join(parts)


def _arg_timeline(b):
    ticks = ", ".join(f"*{clean(t)}*" if i == b["active"] else clean(t) for i, t in enumerate(b["ticks"]))
    parts = [ticks, clean(b["text"])]
    if b.get("subtext"):
        parts.append(clean(b["subtext"]))
    return " | ".join(parts)


def _arg_document(b):
    parts = [b["format"]]
    if b.get("site"):
        parts.append(clean(b["site"]))
    parts.append(clean(b["text"]))
    if b.get("subtext"):
        parts.append(clean(b["subtext"]))
    return " | ".join(parts)


def _arg_source_quote(b):
    parts = [clean(b["source"]), clean(b["text"])]
    if b.get("image_prompt"):
        parts.append(clean(b["image_prompt"]))
    return " | ".join(parts)


def face_option(b) -> str:
    """` | face=main` / ` | face=no` for a story beat the planner marked
    `main_face` (story_visuals: BuzzEdit swaps the main character's face into
    `face=main` shots only); "" when the beat carries no mark."""
    if "main_face" not in b:
        return ""
    on = b["main_face"] is True or str(b["main_face"]).strip().lower() in ("true", "yes", "1")
    return " | face=main" if on else " | face=no"


def _arg_broll_image(b):
    arg = clean(b["image_prompt"])
    return (f"{arg} | look={b['look']}" if b.get("look") else arg) + face_option(b)


CATALOG: List[Effect] = [
    Effect(
        kind="broll_image", directive="broll", group="picture",
        summary="A generated full-frame still cut in over the speaker (with a slow Ken Burns move).",
        use_when="Whenever a concrete thing, place or scene is mentioned. The workhorse of every edit.",
        fields={"image_prompt": "a vivid, specific, literal scene description in English"},
        optional={"look": f"colour look for the still: {', '.join(LOOKS)} (documentary drama: noir, red_duotone, sepia)"},
        example={"kind": "broll_image", "image_prompt": "boot prints in fresh snow at dawn, pine forest", "look": "blue_duotone"},
        aliases=("broll", "image", "still", "picture"),
        normalize=_norm_broll_image, arg=_arg_broll_image,
    ),
    Effect(
        kind="statement_card", directive="statement", group="layout",
        summary="The speaker's key sentence set big in serif on an off-white canvas, 1-3 key words in coral, "
                "the speaker still live in a framed slot on the right.",
        use_when="The thesis, a rule, or a punchline the viewer should read as well as hear. About one per 2 minutes.",
        fields={"text": "6-18 words, the key 1-3 words wrapped in *asterisks*"},
        optional={"with_speaker": "false to fill the canvas with text only"},
        example={"kind": "statement_card", "text": "If you want *more money*, you have to spend *more hours* on it"},
        aliases=("statement", "statement_text", "text_card", "big_text_card"), min_gap_s=75.0,
        normalize=_norm_statement, arg=_arg_statement,
    ),
    Effect(
        kind="canvas_card", directive="canvas", group="layout",
        summary="A generated picture floating in a rounded, shadowed card on an off-white canvas, an optional "
                "caption on it, the speaker live in a slot on the right. The clean explainer look.",
        use_when="Showing an example, a memory or a product while keeping the speaker present. Alternate with plain B-roll.",
        fields={"image_prompt": "the picture inside the card, described in English"},
        optional={"caption": "short label on the picture, e.g. 'Me at age 14'", "look": f"one of {', '.join(LOOKS)}"},
        example={"kind": "canvas_card", "image_prompt": "teenager gaming late at night, monitor glow", "caption": "Me at age 14"},
        aliases=("canvas", "card_layout", "floating_card", "framed_broll"), min_gap_s=20.0,
        normalize=_norm_canvas, arg=_arg_canvas,
    ),
    Effect(
        kind="pill_labels", directive="pills", group="overlay",
        summary="2-4 rounded labels popping in one by one beside the speaker.",
        use_when="The speaker lists options, goals, reasons or excuses in one breath.",
        fields={"items": "2-4 labels of 1-4 words each, as a list"},
        example={"kind": "pill_labels", "items": ["Financially free", "Retire her parents", "Pay off the mortgage"]},
        aliases=("pills", "chips", "labels", "list_labels", "bullet_labels"), min_gap_s=45.0,
        normalize=_norm_pills, arg=lambda b: "; ".join(clean(i) for i in b["items"]),
    ),
    Effect(
        kind="numbered_point", directive="point", group="overlay",
        summary="A white bar with a coral numbered circle and a short line of text, top of frame.",
        use_when="The speaker starts point 1, 2, 3 of a list or a step of a method.",
        fields={"number": "the point's number", "text": "the point in 2-8 words"},
        example={"kind": "numbered_point", "number": 1, "text": "Super friendly for beginners"},
        aliases=("point", "numbered", "step", "list_item"), min_gap_s=8.0,
        normalize=_norm_point, arg=lambda b: f"{b['number']} | {clean(b['text'])}",
    ),
    Effect(
        kind="name_title", directive="name", group="overlay",
        summary="A person's NAME and role in clean type, bottom right above the captions.",
        use_when="A person (or the speaker) is introduced, quoted or shown for the first time.",
        fields={"text": "the person's NAME only, 1-4 capitalised words -- never a sentence"},
        optional={"subtext": "their role, e.g. 'Author of Atomic Habits'"},
        example={"kind": "name_title", "text": "James Clear", "subtext": "Author of Atomic Habits"},
        aliases=("name", "lower_third", "name_card", "person_title"), min_gap_s=60.0,
        normalize=_norm_name, arg=lambda b: clean(b["text"]) + (f" | {clean(b['subtext'])}" if b.get("subtext") else ""),
    ),
    Effect(
        kind="source_quote", directive="source_quote", group="documentary",
        summary="'SOURCE: ...' over a darkened picture, with the cited sentence and its key phrase under a "
                "yellow highlighter.",
        use_when="A fact is attributed to a named article, report, book or website. Only with a real, named source.",
        fields={"source": "the publication or website name", "text": "the cited sentence, key phrase wrapped in ==double equals=="},
        optional={"image_prompt": "a background picture (darkened behind the text), described in English"},
        example={"kind": "source_quote", "source": "opindia.com",
                 "text": "He went undercover as ==Iftikhar Bhatt== to reach the militants",
                 "image_prompt": "a quiet village street in Kashmir at night"},
        aliases=("source_card_quote", "cited_quote", "citation", "source_highlight"), min_gap_s=25.0,
        normalize=_norm_source_quote, arg=_arg_source_quote,
    ),
    Effect(
        kind="document", directive="document", group="documentary",
        summary="A web article (browser window) or a book page, headline and excerpt with key phrases highlighted.",
        use_when="The speaker refers to an article, report or book passage. Prefer over a plain quote when the source is a page.",
        fields={"format": "web or book", "text": "the headline (or chapter title)",
                "subtext": "the excerpt, key phrase wrapped in ==double equals=="},
        optional={"site": "the website (web) or 'Book title (Author)' (book)"},
        example={"kind": "document", "format": "web", "site": "www.thesentinel.com",
                 "text": "The Hidden Story of ==Operation Rakshak==",
                 "subtext": "Operations were led by the Army's ==Para Special Forces== units"},
        aliases=("web_article", "article", "book_page", "webpage", "document_highlight"), min_gap_s=25.0,
        normalize=_norm_document, arg=_arg_document,
    ),
    Effect(
        kind="timeline", directive="timeline", group="documentary",
        summary="A big figure over a ruler of dates with one date marked.",
        use_when="A number that belongs to a moment in time (an age, a year, a before/after), or placing an event in history.",
        fields={"ticks": "2-9 dates or labels in order, as a list", "text": "the big figure, e.g. '60 KG' or '1999'"},
        optional={"active": "0-based index of the marked tick (default: last)", "subtext": "one short caption line"},
        example={"kind": "timeline", "ticks": ["1975", "1980", "1985", "1990"], "active": 2,
                 "text": "60 KG", "subtext": "weight gained in four weeks"},
        aliases=("timeline_ruler", "date_ruler", "year_marker"), min_gap_s=40.0,
        normalize=_norm_timeline, arg=_arg_timeline,
    ),
    Effect(
        kind="transition", directive="fx", group="motion",
        summary="A one-shot transition on the cut: whiteflash (dip to white, documentary), glitch (RGB tear).",
        use_when="Between two story beats or before a reveal. Sparingly -- at most one every 30-45 seconds.",
        fields={"effect": f"one of {', '.join(TRANSITIONS)}"},
        example={"kind": "transition", "effect": "whiteflash"},
        aliases=("flash_transition", "white_flash", "glitch_transition", "cut_transition"), min_gap_s=30.0,
        normalize=_norm_transition,
        arg=lambda b: f"{b['effect']} dur={0.5 if b['effect'] in ('whiteflash', 'glitch') else 0.4}",
    ),
]

#: The kinds BuzzEdit already had (written by `integrations/buzzedit_script.py`),
#: listed so the planner sees one complete menu.
EXISTING_KINDS: Dict[str, str] = {
    "broll_video": "a generated moving clip (use for motion: pouring, walking, weather); `video_prompt`",
    "map": "a drawn map of a place; `place`",
    "chart": "an animated bar/pie/line chart; `data` {labels, values, chart_type}",
    "stat_callout": "a big number counting up; `data` {value, suffix}, `text` label",
    "quote_card": "a quotation card; `text` quote, `subtext` who said it",
    "character_card": "a person card with a box; `text` name, `subtext` role",
    "location_card": "a place/date card; `text`, `subtext`",
    "definition_card": "a term and its meaning; `text` term, `subtext` meaning",
    "split": "two pictures side by side (A vs B); `text` A, `subtext` B",
    "newspaper": "a newspaper clipping; `data` {headline, dateline, masthead}",
    "case_file": "a case file / dossier; `data` {title, fields, stamp}",
    "chapter": "a chapter title card between sections; `text`",
    "fx": "a short effect hit; `effect` from the palette",
    "atmos": "an ambient effect held longer; `effect`",
    "grade": "a colour shift for a moment; `data` {saturation, contrast, vignette}",
    "music_cue": "the background music from this line on; `music` e.g. \"sad solo violin, 70 bpm\" or \"off\"",
}

BY_KIND: Dict[str, Effect] = {e.kind: e for e in CATALOG}
ALIASES: Dict[str, str] = {alias: e.kind for e in CATALOG for alias in e.aliases}
ALL_KINDS: Tuple[str, ...] = tuple(sorted(set(BY_KIND) | set(EXISTING_KINDS)))
#: Directive names this catalog emits beyond BuzzEdit's original vocabulary.
NEW_DIRECTIVES: Tuple[str, ...] = ("statement", "canvas", "pills", "point", "name",
                                   "source_quote", "document", "timeline")

#: Which designed graphics fit which genre best (the planner is told these
#: first; every kind stays allowed everywhere).
GENRE_FAVOURITES: Dict[str, Tuple[str, ...]] = {
    "vlog": ("statement_card", "canvas_card", "pill_labels", "numbered_point", "name_title"),
    "motivational": ("statement_card", "canvas_card", "pill_labels", "numbered_point"),
    "education": ("numbered_point", "pill_labels", "statement_card", "canvas_card", "timeline"),
    "finance": ("statement_card", "pill_labels", "numbered_point", "timeline", "document"),
    "documentary": ("source_quote", "document", "timeline", "name_title", "transition"),
    "history": ("source_quote", "document", "timeline", "name_title", "transition"),
    "true_crime": ("source_quote", "document", "timeline", "name_title", "transition"),
    "horror": ("source_quote", "document", "transition", "timeline"),
    "mystery": ("source_quote", "document", "timeline", "transition"),
    "news": ("document", "source_quote", "timeline", "name_title"),
}
DEFAULT_FAVOURITES = ("statement_card", "canvas_card", "pill_labels", "numbered_point", "source_quote")


def resolve_kind(kind: Any) -> str:
    key = str(kind or "").strip().lower().replace("-", "_").replace(" ", "_")
    return ALIASES.get(key, key)


def normalize_beat(beat: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """(repaired beat, "") or (None, why it cannot render). Kinds outside the
    catalog pass through with only their alias resolved."""
    beat = dict(beat)
    beat["kind"] = resolve_kind(beat.get("kind"))
    effect = BY_KIND.get(beat["kind"])
    if effect is None or effect.normalize is None:
        return beat, ""
    return effect.normalize(beat)


def directive_for(beat: Dict[str, Any]) -> Optional[str]:
    """`[directive: arg]` for a catalog kind (normalized first), or None."""
    fixed, _reason = normalize_beat(beat)
    if fixed is None:
        return None
    effect = BY_KIND.get(fixed["kind"])
    if effect is None or effect.arg is None:
        return None
    return f"[{effect.directive}: {effect.arg(fixed)}]"


def space_beats(beats: Sequence[Dict[str, Any]], time_key: str = "start") -> List[Dict[str, Any]]:
    """Drop a designed effect that repeats sooner than its kind's `min_gap_s`
    after the last one kept -- models over-use a new toy (three statement
    cards a minute in a real run). Order and every other beat are kept."""
    last: Dict[str, float] = {}
    kept: List[Dict[str, Any]] = []
    for beat in sorted(beats, key=lambda b: float(b.get(time_key) or 0.0)):
        effect = BY_KIND.get(resolve_kind(beat.get("kind")))
        at = float(beat.get(time_key) or 0.0)
        if effect is not None and effect.min_gap_s:
            previous = last.get(effect.kind)
            if previous is not None and at - previous < effect.min_gap_s:
                continue
            last[effect.kind] = at
        kept.append(beat)
    return kept


def favourites_for(genre: Optional[str], genre_secondary: Optional[str] = None) -> List[str]:
    seen: List[str] = []
    for g in (genre, genre_secondary):
        for kind in GENRE_FAVOURITES.get(str(g or "").lower(), ()):
            if kind not in seen:
                seen.append(kind)
    return seen or list(DEFAULT_FAVOURITES)


def prompt_section(genre: Optional[str] = None, genre_secondary: Optional[str] = None) -> str:
    """The effect menu for the planner: every designed effect with what it looks
    like, when to use it, its fields and an exact example, then the older
    kinds in one line each. Favourites for the genre come first."""
    import json
    favourites = favourites_for(genre, genre_secondary)
    ordered = sorted(CATALOG, key=lambda e: (e.kind not in favourites,
                                             favourites.index(e.kind) if e.kind in favourites else 99))
    lines = ["### Effect catalog (use these exact `kind` names and fields)"]
    if favourites:
        lines.append(f"Best fits for this video: {', '.join(favourites)}. Mix them with B-roll; "
                     "never the same designed effect twice in a row.")
    for effect in ordered:
        required = "; ".join(f"`{k}`: {v}" for k, v in effect.fields.items())
        optional = "; ".join(f"`{k}`: {v}" for k, v in effect.optional.items())
        lines.append(f"- **{effect.kind}** -- {effect.summary} Use when: {effect.use_when} "
                     f"Needs {required}." + (f" Optional {optional}." if optional else "")
                     + f"\n  Example: {json.dumps(effect.example, ensure_ascii=False)}")
    lines.append("Other kinds: " + "; ".join(f"**{k}** ({v})" for k, v in EXISTING_KINDS.items()) + ".")
    gaps = ", ".join(f"{e.kind} {int(e.min_gap_s)}s" for e in CATALOG if e.min_gap_s)
    lines.append("Marks: *asterisks* colour words in a statement_card; ==double equals== put the "
                 "highlighter on words in a source_quote or document. Text on screen is short -- "
                 "a card is read in 3 seconds.")
    lines.append("Language: `image_prompt` and `video_prompt` are ALWAYS written in English (the "
                 "image model reads English). On-screen words (`text`, `items`, `caption`, "
                 "`subtext`) follow the video's language -- Hinglish in Roman script here.")
    lines.append(f"Spacing: the same designed effect never repeats sooner than {gaps}; "
                 "extras are removed.")
    from integrations import music_catalog
    lines.append(music_catalog.prompt_section())
    return "\n".join(lines)


def kinds_pipe() -> str:
    """`a|b|c` for the JSON schema line."""
    return "|".join(ALL_KINDS)
