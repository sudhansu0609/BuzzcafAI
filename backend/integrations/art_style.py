"""
The art style: what medium a video's pictures, clips, thumbnail scene and
on-screen text are made in (the creator's request, 2026-10-21, for the
Beyond3Baje survival stories: "real or explainer or stick figure or cartoon").

It is a separate axis from `visual_style` (`buzzedit_settings.py`: "story"
= pictures only, "full" = every text and effect layer). The art style says
HOW things are drawn; the visual style says WHICH layers exist. Resolved like
every other video setting -- channel profile -> project -> request -- and
sent to BuzzEdit as `art_style`, which has the same table in
`presentation/art_style.py` (the two repos share no code).

Each style carries:
- `look`      -- appended to every picture prompt (the still model draws
                 whatever medium it is told; a local planner forgets);
- `motion`    -- how a clip animated from that picture should move;
- `negative`  -- what must not appear (ignored by Z-Image, kept for others);
- `thumbnail` -- the medium phrase for the thumbnail's scene;
- `text`      -- "channel" (the visual style decides), "on" (short text
                 cards are part of this medium, even on a story channel) or
                 "off" (pictures only);
- `planner`   -- how the visual planner and the PromptEngineer must write
                 prompts for it;
- `cast`      -- how the CharacterPlanner describes people in it;
- `face_swap` -- whether the main character's real face is swapped in
                 (only a photoreal picture can take a real face).
"""

from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional, Tuple


class ArtStyle(NamedTuple):
    label: str
    look: str
    motion: str
    negative: str
    thumbnail: str
    text: str
    planner: str
    cast: str
    face_swap: bool
    prefix: str = ""   # leads the prompt when the medium must come first (stick figures)


#: Slow, steady motion for a photoreal clip. No "camera" in it: BuzzEdit
#: draws a `[video:]` clip's first frame from the same text (2026-10-03).
REAL_MOTION = ("slow steady cinematic motion, calm and eerie, subtle natural movement, "
               "no fast motion, no shaking")

STYLES: Dict[str, ArtStyle] = {
    "real": ArtStyle(
        label="Real (cinematic, photoreal)",
        look="",
        motion=REAL_MOTION,
        negative="",
        thumbnail="cinematic film still, one clear subject, close framing, strong contrast",
        text="channel",
        planner="",
        cast="",
        face_swap=True,
    ),
    "explainer": ArtStyle(
        label="Explainer (flat vector illustration)",
        look=("flat vector explainer illustration, clean simple geometric shapes, bold flat colours, "
              "soft gradients, clear silhouettes, minimal detail, generous empty space, "
              "modern infographic style"),
        motion=("smooth simple 2D animation, one element moves at a time, gentle easing, "
                "flat shapes sliding and fading, no camera shake"),
        negative="photograph, photorealistic, realistic skin, 3d render, film grain, clutter",
        thumbnail="flat vector explainer illustration, bold flat colours, one clear subject, clean background",
        text="on",
        planner=(
            "ART STYLE -- EXPLAINER. Every picture and clip is a flat vector explainer illustration: "
            "simple geometric shapes, bold flat colours, clear silhouettes, lots of empty space, the "
            "look of a modern animated explainer video. Describe scenes as diagrams of what happened: "
            "a cutaway of the ship with a small air pocket marked, a map with a dotted drift line, a "
            "simple figure beside a scale bar. People are simplified figures with clear poses, never "
            "realistic faces. Numbers, distances and durations are the point of this style: put them on "
            "screen as `popup` or `stat_callout` beats next to the picture, never drawn inside it. No "
            "photographs, no film-still language, no lens or lighting words, no textures."),
        cast=("Describe each character the way a flat vector explainer would draw them: a simple figure, "
              "a flat skin tone, a two-colour outfit, one shape that identifies them (a cap, a beard, a "
              "red scarf). No realistic facial detail."),
        face_swap=False,
    ),
    "stick_figure": ArtStyle(
        label="Stick figure (whiteboard drawing)",
        look=("crude stick figure drawing: people are a circle for the head and five straight black lines "
              "for the body, no face, no clothes, no hands; thin black marker on plain white paper, "
              "childlike whiteboard doodle, objects drawn with three or four lines, no colour fill, "
              "no shading, a single red accent line"),
        motion=("hand-drawn whiteboard animation, the lines appear as if being drawn, slight line "
                "wobble, simple movement of one figure, white background stays still"),
        negative="photograph, photorealistic, colour fill, 3d render, shading, gradients, detailed faces",
        thumbnail="stick figure drawing in black marker on white paper, one red accent, hand-drawn",
        text="on",
        planner=(
            "ART STYLE -- STICK FIGURE. Every picture and clip is a hand-drawn stick-figure sketch in "
            "black marker on plain white paper, like a whiteboard explainer: thin uneven lines, no "
            "shading, no colour except a single red accent for the one thing that matters in the shot. "
            "A ship is a few lines, a mountain a triangle, a person a stick figure with a round head "
            "and one expressive pose. Keep every scene to one idea with lots of white space. Short "
            "hand-written labels belong on screen as `popup` or `stat_callout` beats beside the "
            "drawing, never drawn inside it. No photographs, no realism, no lighting or lens words."),
        cast=("Describe each character as a stick figure: a round head, a line body, and ONE drawn "
              "detail that tells them apart (a hat, glasses, a beard, a long skirt, a red scarf). "
              "No face detail, no skin, no realistic clothing."),
        face_swap=False,
        prefix=("A crude whiteboard doodle in black marker on plain white paper, the whole picture is "
                "the drawing, nothing photographed, nothing in the frame but the one scene described. Any "
                "person is drawn as a stick figure (a circle head, straight lines for the body, no face, "
                "no clothes, no skin colour), and no other figures are added. The doodle shows only:"),
    ),
    "cartoon": ArtStyle(
        label="Cartoon (2D animated)",
        look=("bold 2D cartoon illustration, thick clean outlines, flat cel shading, bright saturated "
              "colours, expressive simplified characters, animated series style"),
        motion=("smooth 2D cartoon animation, expressive movement of one character or object, "
                "flat cel-shaded colours, steady framing, no camera shake"),
        negative="photograph, photorealistic, realistic skin, 3d render, film grain",
        thumbnail="bold 2D cartoon illustration, thick outlines, bright colours, one expressive subject",
        text="off",
        planner=(
            "ART STYLE -- CARTOON. Every picture and clip is a bold 2D cartoon: thick clean outlines, "
            "flat cel shading, bright saturated colours, expressive simplified characters, the look of "
            "an animated series. Describe scenes as cartoon frames -- an exaggerated expression, a "
            "clear pose, a simple background with two or three colours -- never as photographs. No "
            "lens, lighting or film words, no realism, no textures."),
        cast=("Describe each character as a cartoon character: a simple exaggerated silhouette, flat "
              "colours, two or three fixed costume colours, one feature that identifies them at a "
              "glance (big glasses, a long moustache, a yellow raincoat). No realistic facial detail."),
        face_swap=False,
    ),
    "painterly": ArtStyle(
        label="Painterly (soft oil / gouache)",
        look=("soft painterly illustration, loose oil and gouache brushwork, muted earthy palette with "
              "one warm light source, visible brush texture, no outlines, soft edges, atmospheric depth, "
              "quiet and melancholic"),
        motion=("very slow drift, mist and light shifting gently, brush texture steady, no fast motion, "
                "no shaking"),
        negative="photograph, photorealistic, 3d render, hard outlines, cartoon, neon, text, watermark",
        thumbnail="soft painterly illustration, muted palette, one warm light, one clear subject",
        text="channel",
        planner=(
            "ART STYLE -- PAINTERLY. Every picture and clip is a soft painting in loose oil and gouache "
            "brushwork: a muted earthy palette, visible brush texture, soft edges and no outlines, the "
            "look of a quiet, melancholic illustrated book. Describe scenes as a painter would: light, "
            "weather, distance, a single warm source -- a lamp in a far window, a low sun behind mist, "
            "one candle in a dark room -- and let the rest fall into soft shadow. People are figures in "
            "the scene, seen through posture and silhouette, never realistic faces. No lens or film "
            "words, no photographs, no realism, and no text in the picture."),
        cast=("Describe each character as a painter would: a silhouette, a posture, the colour of a "
              "coat, never facial detail."),
        face_swap=False,
    ),
    # 2026-10-24 (VR8): a soothing hand-drawn look for Life3Baje mood reels,
    # next to "real" -- frame-by-frame Procreate-style animation, never a
    # photograph. BuzzEdit's own vibe-reel look pass steps a video shot's
    # motion to ~12fps held frames and adds a static paper-grain texture for
    # this style instead of "real"'s handheld drift/film grain.
    # 2026-10-27 (creator's request): no single medium for the whole video --
    # each shot is real, stick figure, a map or a chart, picked by the
    # planner per shot (`art` on the beat); see `is_mixed`/`shot_style` below.
    "mixed": ArtStyle(
        label="Mixed (real + stick figure + maps & charts)",
        look="",
        motion=REAL_MOTION,
        negative="",
        thumbnail="cinematic film still, one clear subject, close framing, strong contrast",
        text="on",
        planner=(
            "ART STYLE -- MIXED. This video mixes two mediums shot by shot: on every picture "
            "and clip beat write \"art\": \"real\" for the story's moments as they looked -- "
            "people, places, the event, the emotion -- about half the pictures, or "
            "\"art\": \"stick_figure\" for explaining: how or why something happened, a "
            "cutaway or diagram, a sequence, cause and effect, a \"what would you do\" -- "
            "about a third of the pictures. A real shot follows the channel's own photoreal "
            "rules; a stick_figure shot is a crude whiteboard doodle: one idea, lots of white "
            "space, a single red accent, no colour fill, no realistic faces. About one in three "
            "of those stick_figure shots is better as a `stick_scene` beat instead of a plain "
            "picture, when the moment is an action (one pose from idle, walk, run, point, "
            "shrug, think, cheer, fall, sit, scared, swim, climb). Never two stick_figure shots "
            "or two maps in a row without a reason. Add a `map` beat "
            "(field `place`) whenever a place, a route or a distance first matters, and a "
            "`chart` beat (`data` {labels, values, chart_type: bar|line|pie}, `text` title) "
            "whenever numbers are compared or change over time."),
        cast=("Describe each character realistically as usual -- apparent age, build, face, "
              "hair, clothing -- AND give them ONE drawn detail that still marks the same "
              "person in a stick-figure shot (a cap, glasses, a red scarf): the one feature a "
              "crude doodle keeps once the realistic detail is gone."),
        face_swap=True,
    ),
    # 2026-10-27 (creator's request): "more of illustrated style and stick
    # figure and less real, for more quirky documentaries, and more
    # engaging" -- a second per-shot mix (`MIXES`), mostly hand-drawn.
    "mixed_quirky": ArtStyle(
        label="Quirky documentary (illustrated + stick figure, a little real)",
        look="",
        motion=("gentle hand-animated movement, drawings held and stepped, soft easing, no fast "
                "motion, no shaking"),   # illustrated's motion
        negative="",
        thumbnail="soothing hand-drawn illustration, soft pastel palette, one clear subject, storybook calm",
        text="on",
        planner=(
            "ART STYLE -- QUIRKY DOCUMENTARY (MIXED). This video mixes three mediums shot by "
            "shot, for an engaging, fast-moving documentary feel: on every picture and clip "
            "beat write \"art\": \"illustrated\" for most of the story -- the hand-drawn "
            "illustration look, characters with exaggerated, expressive poses -- about 45% of "
            "the pictures, or \"art\": \"stick_figure\" for the explaining and the visual gags: "
            "a stick figure reacting to the absurd number, a \"you are here\" arrow, a "
            "before/after -- about 35%, or \"art\": \"real\" only for the moments that land "
            "harder as real: the actual place, the object, the one face that matters -- about "
            "10-15%. About one in three of the stick_figure shots is better as an animated "
            "`stick_scene` beat than a plain picture. A `paper_collage` beat (field `prompts`, "
            "2-4 pictures) suits a scrapbook moment -- a handful of evidence, a before/after, "
            "gathered at once. Add a `map` beat (field `place`) and a `chart` beat (`data` {labels, "
            "values, chart_type: bar|line|pie}, `text` title) as often as a place or a number "
            "comes up -- more freely than in the plainer mixed style. Put a `popup`, "
            "`stat_callout` or `definition_card` on every surprising number or term. Keep it "
            "engaging: a new picture every few seconds, a playful contrast between consecutive "
            "shots, curiosity first -- never horror-grim."),
        cast=("Describe each character realistically as usual -- apparent age, build, face, "
              "hair, clothing -- AND give them ONE drawn detail used in BOTH the illustrated "
              "and the stick-figure shots (a cap, glasses, a red scarf), so the same person is "
              "recognisable in either drawn medium."),
        face_swap=True,
    ),
    # 2026-10-29 (STICK_WORLD_PLAN.md): dressed stick figures standing in an
    # illustrated period world -- every era from prehistoric to the future,
    # the vocabulary shared with BuzzEdit at `integrations/stick_world.json`.
    # Plain pictures are the PLACE only (rich period detail, nobody close
    # up); a person moment is a `stick_scene` beat instead (`era`/`outfit`
    # dress the figures, `bg` is the illustrated place behind them). Not a
    # per-shot mix: every picture is this one medium.
    "stick_world": ArtStyle(
        label="Stick world (dressed stick figures in illustrated scenes)",
        look=("hand-painted storybook illustration of the place and its period -- architecture, "
              "materials, light and colour of the era, rich historical detail -- wide and open, "
              "nobody close up, soft painted brushwork, the colour and mood of the story's "
              "moment, an illustrated graphic-novel background"),
        motion=("gentle hand-animated movement, drawings held and stepped, soft easing, no fast "
                "motion, no shaking"),
        # Never "modern" or "neon" here: the present-day, 1990s and future eras
        # are stick-world periods too (stick_world.json).
        negative=("photograph, photorealistic, 3d render, CGI, unreal engine, anime, glossy, "
                  "text, watermark, close-up faces"),
        thumbnail="hand-painted illustration, rich period detail, one clear subject, strong mood",
        text="on",
        planner=(
            "ART STYLE -- STICK WORLD. Every plain picture and clip is a hand-painted storybook "
            "illustration of the PLACE itself -- its period architecture, materials and light, "
            "rich historical detail -- wide and open, nobody close up: a person moment belongs "
            "to a `stick_scene` beat instead, never a close-up face drawn into a plain picture. "
            "Describe scenes the way an illustrator researching the period would: the market, "
            "the court, the workshop, the street -- never as a photograph or film still, no "
            "lens, camera or realism words. A dressed stick figure enters the story only through "
            "a `stick_scene` beat: give it `era` (the period, e.g. \"ancient_greece\") to dress "
            "every figure for it, or an `outfit` per figure (the cast's own fixed spec, word for "
            "word) when a named character needs their own clothes, and `bg` -- an English "
            "picture prompt for the place behind them -- whenever that place has not just been "
            "shown as a plain picture. Reach for `map`, `timeline` or `chart` for a documentary, "
            "case-study or What If moment instead of a drawing."),
        cast=("Describe each character as a stick_scene outfit spec: ALSO give, next to the "
              "usual `look`, an `\"outfit\"` (one spec built from the stick-world vocabulary -- "
              "one body garment, one headwear, one held item, one hair/beard piece, order-free, "
              "joined by '+', e.g. \"chiton+laurel+scroll+beard\") and an `\"era\"` (its "
              "stick_world.json period key, e.g. \"ancient_greece\"). That exact spec is reused "
              "for the character in every stick_scene beat that names them."),
        face_swap=False,
    ),
    "illustrated": ArtStyle(
        label="Illustrated animation (hand-drawn)",
        look=("soothing hand-drawn digital illustration, frame-by-frame animation style, soft "
              "gouache and pencil brush texture, visible hand-drawn strokes, gentle pastel and "
              "muted colour palette, simple clean shapes, cozy storybook calm, a slight paper "
              "grain, no hard or glossy outlines"),
        motion=("gentle hand-animated movement, drawings held and stepped, soft easing, no fast "
                "motion, no shaking"),
        negative=("photograph, photorealistic, 3d render, CGI, unreal engine, anime, glossy, "
                  "neon, text, watermark"),
        thumbnail="soothing hand-drawn illustration, soft pastel palette, one clear subject, storybook calm",
        text="channel",
        planner=(
            "ART STYLE -- ILLUSTRATED. Every picture and clip is a soothing hand-drawn digital "
            "illustration, like a frame-by-frame Procreate animation: soft gouache and pencil "
            "brush texture, visible strokes, a gentle pastel and muted palette, simple clean "
            "shapes, cozy storybook calm, a slight paper grain. Describe scenes the way an "
            "illustrator would: light, weather, a cosy detail -- never as a photograph or film "
            "still, with no lens, camera or realism words. People are soft drawn figures, seen "
            "through posture and silhouette, never a realistic or photographic face. No text in "
            "the picture."),
        cast=("Describe each character the way a soft hand-drawn illustration would: a gentle "
              "silhouette, a posture, the colour of a coat, never photographic facial detail."),
        face_swap=False,
    ),
}

ART_STYLES: Tuple[str, ...] = tuple(STYLES.keys())
DEFAULT = "real"

_ALIASES = {
    "photoreal": "real", "photo": "real", "realistic": "real", "cinematic": "real", "film": "real",
    "stick": "stick_figure", "stickfigure": "stick_figure", "stick_figures": "stick_figure",
    "whiteboard": "stick_figure", "doodle": "stick_figure",
    "vector": "explainer", "flat": "explainer", "infographic": "explainer",
    "animated": "cartoon", "animation": "cartoon", "toon": "cartoon", "anime": "cartoon",
    "oil": "painterly", "gouache": "painterly", "watercolor": "painterly", "watercolour": "painterly",
    "painting": "painterly",
    "mix": "mixed", "combo": "mixed", "hybrid": "mixed", "mixed_media": "mixed",
    "quirky": "mixed_quirky", "quirky_doc": "mixed_quirky", "quirky_documentary": "mixed_quirky",
    "stickworld": "stick_world", "dressed_stick": "stick_world", "dressed_stick_figure": "stick_world",
    "period_stick": "stick_world",
}

#: Which styles are a per-shot mix of other media, largest-share medium
#: first (the fallback when a beat's own `art` option is missing or not one
#: of this mix's media). A third mix is a new row here, not new code: every
#: `is_mixed`/`shot_style` caller below reads this table, never a literal
#: style name.
MIXES: Dict[str, Dict[str, Any]] = {
    "mixed": {"media": {"real": 0.5, "stick_figure": 0.35}, "thumbnail_medium": "real"},
    "mixed_quirky": {"media": {"illustrated": 0.45, "stick_figure": 0.35, "real": 0.12},
                     "thumbnail_medium": "illustrated"},
}
#: Every medium any mix allows for `art`, used to validate a beat's `art`
#: option (`effect_catalog.art_option`) without hardcoding one mix's media.
MIX_MEDIA: frozenset = frozenset(medium for mix in MIXES.values() for medium in mix["media"])
#: A short noun phrase for a medium, used to describe a mix's own media
#: generically (`step_direction`) instead of a hardcoded sentence per mix.
_MEDIUM_PHRASE = {"real": "photoreal story shots", "stick_figure": "stick-figure explainer drawings",
                  "illustrated": "hand-drawn illustration"}


def normalise(style: Any) -> str:
    """A user- or model-supplied style name mapped onto one we have; anything
    unrecognised is "real" (the style is a hint, and a wrong hint costs nothing)."""
    if not style:
        return DEFAULT
    slug = str(style).strip().lower().replace("-", "_").replace(" ", "_")
    if slug in STYLES:
        return slug
    return _ALIASES.get(slug, DEFAULT)


def is_valid(style: Any) -> bool:
    return isinstance(style, str) and style in STYLES


def is_mixed(style: Any) -> bool:
    return normalise(style) in MIXES


def shot_style(style: Any, art_option: Any = None) -> str:
    """Which medium ONE shot (not the whole video) is drawn in. A mix style
    (`MIXES`) picks it from the beat's own `art` option when that option
    names one of its media, else its first (largest-share) medium -- for
    `mixed` that stays `real` (no map/chart shot reaches this: those are
    never pictures). `art_option` is matched as written, never defaulted to
    "real" the way `normalise` would: an unknown medium must fall back to
    the mix's own first choice, not always "real". Any other style always
    draws every shot the same way, so this is just `normalise(style)`."""
    name = normalise(style)
    mix = MIXES.get(name)
    if mix is None:
        return name
    media = mix["media"]
    slug = str(art_option or "").strip().lower().replace("-", "_").replace(" ", "_")
    return slug if slug in media else next(iter(media))


def get(style: Any) -> ArtStyle:
    return STYLES[normalise(style)]


def labels() -> Dict[str, str]:
    return {name: s.label for name, s in STYLES.items()}


def look_for(style: Any) -> str:
    return get(style).look


def motion_for(style: Any) -> str:
    return get(style).motion


def thumbnail_look(style: Any) -> str:
    """The medium phrase for the thumbnail's scene. A mix's thumbnail is
    always one fixed medium (`MIXES[...]["thumbnail_medium"]"), never picked
    per shot -- `mixed` stays real, `mixed_quirky` is illustrated."""
    name = normalise(style)
    mix = MIXES.get(name)
    if mix:
        return STYLES[mix["thumbnail_medium"]].thumbnail
    return get(style).thumbnail


def uses_face_swap(style: Any) -> bool:
    return get(style).face_swap


def text_cards(style: Any) -> Optional[bool]:
    """True: short text cards belong to this medium (back on even for a story
    channel); False: pictures only; None: the visual style decides."""
    text = get(style).text
    return None if text == "channel" else text == "on"


def apply_look(prompt: str, style: Any) -> str:
    """`prompt` with the style's look appended once; "real" leaves it alone."""
    look = look_for(style)
    text = (prompt or "").rstrip(" .,;")
    if look and look.lower() not in text.lower():
        text = f"{text}, {look}" if text else look
    prefix = get(style).prefix
    if prefix and text and not text.lower().startswith(prefix[:40].lower()):
        text = f"{prefix} {text[:1].lower() + text[1:]}"
    return text


def planner_section(style: Any) -> str:
    """The paragraph the visual planner / PromptEngineer gets for a non-real
    style; "" for real (the channel's own rules already describe it)."""
    name = normalise(style)
    s = STYLES[name]
    if not s.planner:
        return ""
    lines = ["### This video's art style", s.planner]
    if name in MIXES:
        # Unlike every other style, a mix has no one look to repeat on every
        # prompt: each shot's medium (and look) comes from its own `art`
        # field (`story_visuals.shot_style`).
        lines.append("The look is added per shot from `art`, never appended here to every prompt.")
    else:
        lines.append(f"Append to every image_prompt and video_prompt, word for word: \"{s.look}\".")
    lines += [f"Clip motion in this style: {s.motion}.",
              "style_hint for every beat: 'illustration'."]
    if s.text == "on":
        lines.append("Short on-screen text IS part of this style: use `popup` (at most six words), "
                     "`stat_callout` (one number with its unit) and `definition_card` beats for the "
                     "numbers, names and terms the narration gives, placed next to the picture that "
                     "shows them. They are rendered as text by the editor, so never ask the image "
                     "model to draw letters.")
        # Favoured for the clean/modern mediums only (M4, 2026-10-27) -- a
        # crude stick-figure doodle keeps to `popup`/`stat_callout` instead.
        preferred_fx = {"explainer": "shape_wipe, iris or bars", "mixed_quirky": "paper_tear or ink"}
        if name in ("explainer", "mixed", "mixed_quirky"):
            lines.append(
                "A key line, a twist or a number worth feeling earns a `kinetic_text` beat (4-14 "
                "words, the key words in *asterisks*) about once every 60-90 seconds; reach for a "
                f"`transition` ({preferred_fx.get(name, 'a shape transition')}) on a hard cut "
                "between scenes, sparingly.")
        # M8, 2026-10-28: which of the two new animated/cutout beats this
        # style reaches for first (stick_figure keeps to stick_scene alone;
        # explainer favours paper_collage; the two per-shot mixes favour
        # both, mixed_quirky first of all).
        # M12, 2026-10-28: the Phase 2 motion effects on top -- explainer also
        # favours flow_diagram/icon_list (process + list diagrams suit its
        # clean, modern look), mixed_quirky also favours icon_list/ui_mockup
        # (chat/forum mockups fit its quirky-documentary feel).
        favourite_motion = {
            "stick_figure": ("stick_scene",), "explainer": ("paper_collage", "flow_diagram", "icon_list"),
            "mixed": ("stick_scene", "paper_collage"),
            "mixed_quirky": ("paper_collage", "stick_scene", "icon_list", "ui_mockup"),
            "stick_world": ("stick_scene",),
        }.get(name)
        if favourite_motion:
            lines.append(f"Best fits for this style: {', '.join(favourite_motion)}.")
    elif s.text == "off":
        lines.append("No text on screen in this style: pictures and clips only.")
    return "\n".join(lines)


def cast_direction(style: Any) -> str:
    """The line added to the CharacterPlanner's prompt for a non-real style."""
    s = get(style)
    return f"\nART STYLE: {s.label}. {s.cast}\n" if s.cast else ""


def step_direction(style: Any) -> str:
    """One short block for every workflow step of a non-real project, so the
    writers, the storyboard planner and the thumbnail designer all know what
    the pictures will look like."""
    name = normalise(style)
    if name == DEFAULT:
        return ""
    s = STYLES[name]
    mix = MIXES.get(name)
    if mix:
        media_desc = ", ".join(_MEDIUM_PHRASE.get(m, m) for m in mix["media"])
        return (f"### This video's art style: {s.label}\n"
                f"This video mixes {media_desc}, plus maps and charts, picked shot by shot. "
                "Plan and describe each visual in whichever of those fits the moment, never as "
                "a photograph for a drawn shot nor as a drawing for a real one."
                + (" Short on-screen text (numbers, names, terms) is part of this style." if s.text == "on" else ""))
    return (f"### This video's art style: {s.label}\n"
            f"Every picture, clip and thumbnail scene of this video is made as: {s.look}. "
            f"Plan and describe visuals in that medium, never as photographs or film stills."
            + (" Short on-screen text (numbers, names, terms) is part of this style." if s.text == "on" else ""))
