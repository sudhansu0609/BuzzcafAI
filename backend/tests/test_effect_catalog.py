"""
The effect catalog (`integrations/effect_catalog.py`): the planner's menu, the
repair of what a model sends back, and the exact directives BuzzEdit parses.

`GOLDEN` is the contract with BuzzEdit: the same strings are parsed by
`BuzzEdit/backend/tests/test_graphics.py::GOLDEN`, so a change on either side
that breaks the other fails a test instead of a render.
"""

import re
from pathlib import Path

import pytest

from integrations import buzzedit_script, effect_catalog as E
from integrations.visual_windows import Window, build_window_prompt, parse_window_beats

GOLDEN = {
    "broll_image": "[broll: boot prints in fresh snow at dawn, pine forest | look=blue_duotone]",
    "statement_card": "[statement: If you want *more money*, you have to spend *more hours* on it]",
    "canvas_card": "[canvas: teenager gaming late at night, monitor glow | Me at age 14]",
    "pill_labels": "[pills: Financially free; Retire her parents; Pay off the mortgage]",
    "numbered_point": "[point: 1 | Super friendly for beginners]",
    "name_title": "[name: James Clear | Author of Atomic Habits]",
    "source_quote": "[source_quote: opindia.com | He went undercover as ==Iftikhar Bhatt== to reach "
                    "the militants | a quiet village street in Kashmir at night]",
    "document": "[document: web | www.thesentinel.com | The Hidden Story of ==Operation Rakshak== | "
                "Operations were led by the Army's ==Para Special Forces== units]",
    "timeline": "[timeline: 1975, 1980, *1985*, 1990 | 60 KG | weight gained in four weeks]",
    "kinetic_text": "[kinetic: This is the *moment* everything changed | style=slam]",
    "transition": "[fx: whiteflash dur=0.5]",
    "stick_scene": "[stick: action=swim | scene=crossing a dark sea at night | prop=ship | figures=2 "
                   "| caption=Three hours in the water]",
    "paper_collage": "[collage: a torn train ticket on a wooden table ; a rain-streaked window at dusk "
                     "| caption=The last clue]",
    "flow_diagram": "[flow: Water heats up ; Steam rises ; Clouds form ; Rain falls | layout=cycle]",
    "icon_list": "[icons: + Easy to learn ; - Takes longer to master | mode=pros_cons]",
    "ui_mockup": "[ui: chat | text=Did you hear about the ship? // > No, what happened | name=Alex "
                 "| handle=@alex99]",
    "callout": "[callout: a muddy boot print beside the fence | mark=circle | at=bottom_right | label=The print]",
}


@pytest.mark.parametrize("effect", E.CATALOG, ids=lambda e: e.kind)
def test_every_catalog_example_writes_its_golden_directive(effect):
    assert E.directive_for(effect.example) == GOLDEN[effect.kind]


def test_every_catalog_kind_has_a_golden_directive():
    assert set(GOLDEN) == set(E.BY_KIND)


def test_every_directive_name_is_one_buzzedit_parses():
    names = set(buzzedit_script._DIRECTIVES)
    for directive in GOLDEN.values():
        assert re.match(r"\[(\w+):", directive).group(1) in names


def test_buzzedit_really_knows_the_new_directives():
    """Read BuzzEdit's own vocabulary when the sibling checkout is there."""
    path = Path(__file__).resolve().parents[3] / "BuzzEdit" / "backend" / "asr" / "script_align.py"
    if not path.exists():
        pytest.skip("BuzzEdit checkout not beside this repo")
    source = path.read_text(encoding="utf-8")
    for name in E.NEW_DIRECTIVES:
        assert f'"{name}"' in source, name


def test_the_directive_writer_uses_the_catalog():
    beat = {"kind": "pill_labels", "items": ["A one", "B two"]}
    assert buzzedit_script._directive_for(beat) == "[pills: A one; B two] "


# --- repair ------------------------------------------------------------------------------

def test_aliases_resolve_to_catalog_kinds():
    assert E.resolve_kind("Pills") == "pill_labels"
    assert E.resolve_kind("web-article") == "document"
    assert E.resolve_kind("lower third") == "name_title"
    assert E.resolve_kind("broll_video") == "broll_video"


def test_a_string_of_items_becomes_a_list_and_is_capped():
    beat, _ = E.normalize_beat({"kind": "chips", "items": "One; Two; Three; Four; Five"})
    assert beat["kind"] == "pill_labels"
    assert beat["items"] == ["One", "Two", "Three", "Four"]


def test_missing_highlights_are_added():
    statement, _ = E.normalize_beat({"kind": "statement_card", "text": "Consistency beats intensity every time"})
    assert "*" in statement["text"]
    quote, _ = E.normalize_beat({"kind": "source_quote", "source": "BBC", "text": "The dam failed overnight"})
    assert "==" in quote["text"]


def test_a_starred_tick_becomes_the_active_one():
    beat, _ = E.normalize_beat({"kind": "timeline", "ticks": "1990, *2001*, 2010", "text": "9/11"})
    assert beat["ticks"] == ["1990", "2001", "2010"] and beat["active"] == 1


@pytest.mark.parametrize("beat,why", [
    ({"kind": "source_quote", "text": "a claim"}, "source"),
    ({"kind": "pill_labels", "items": ["only one"]}, "2-4"),
    ({"kind": "timeline", "ticks": ["1990"], "text": "x"}, "ticks"),
    ({"kind": "canvas_card"}, "image_prompt"),
    ({"kind": "transition", "effect": "explode"}, "transition"),
    ({"kind": "kinetic_text", "text": "too short"}, "kinetic_text"),
])
def test_unrenderable_beats_are_dropped_with_a_reason(beat, why):
    fixed, reason = E.normalize_beat(beat)
    assert fixed is None and why in reason
    assert E.directive_for(beat) is None


def test_an_unknown_look_is_removed_not_passed_on():
    beat, _ = E.normalize_beat({"kind": "broll_image", "image_prompt": "a", "look": "vaporwave"})
    assert beat["look"] == ""
    assert E.directive_for(beat) == "[broll: a]"


def test_directive_syntax_characters_are_cleaned_out_of_fields():
    directive = E.directive_for({"kind": "name_title", "text": "A [B] | C", "subtext": "x"})
    assert directive == "[name: A (B) / C | x]"


# --- M4: kinetic_text + the five new shape transitions ------------------------------------

def test_kinetic_text_default_style_and_word_limits():
    beat, _ = E.normalize_beat({"kind": "kinetic", "text": "Everything changed in a single heartbeat"})
    assert beat["kind"] == "kinetic_text" and beat["style"] == "slam"
    long_text = " ".join(f"word{i}" for i in range(20))
    beat, _ = E.normalize_beat({"kind": "kinetic_text", "text": long_text, "style": "typewriter"})
    assert len(beat["text"].split()) == 14 and beat["style"] == "typewriter"
    beat, _ = E.normalize_beat({"kind": "kinetic_text", "text": "He never saw it coming", "style": "nonsense"})
    assert beat["style"] == "slam", "an unknown style falls back to the default"


def test_kinetic_text_highlight_is_added_when_missing():
    beat, _ = E.normalize_beat({"kind": "kinetic_text", "text": "Everything changed in one moment"})
    assert "*" in beat["text"]


def test_new_shape_transitions_hold_0_8s_and_old_ones_are_unchanged():
    for name in ("shape_wipe", "iris", "ink", "bars", "paper_tear"):
        beat, _ = E.normalize_beat({"kind": "transition", "effect": name})
        assert E.directive_for(beat) == f"[fx: {name} dur=0.8]"
    assert E.directive_for({"kind": "transition", "effect": "whiteflash"}) == "[fx: whiteflash dur=0.5]"
    assert E.directive_for({"kind": "transition", "effect": "glitch"}) == "[fx: glitch dur=0.5]"
    assert E.directive_for({"kind": "transition", "effect": "flash"}) == "[fx: flash dur=0.4]"
    assert E.directive_for({"kind": "transition", "effect": "shutter"}) == "[fx: shutter dur=0.4]"


def test_documentary_still_defaults_to_whiteflash_first():
    """TRANSITIONS lists whiteflash first; the new favourites below must not
    reorder it away from being documentary's (and every other genre's) default."""
    assert E.TRANSITIONS[0] == "whiteflash"


def test_explainer_ish_genres_favour_kinetic_text_and_transitions():
    for genre in ("vlog", "motivational", "education", "finance", "documentary"):
        favourites = E.favourites_for(genre)
        assert "kinetic_text" in favourites and "transition" in favourites
    # Untouched genres stay as they were.
    assert "kinetic_text" not in E.favourites_for("horror")


# --- M8: stick_scene + paper_collage -------------------------------------------------------

def test_stick_scene_and_paper_collage_pin_buzzedits_grammar():
    beat, _ = E.normalize_beat({"kind": "stick", "action": "SWIM", "scene": "crossing a dark sea at night",
                                 "prop": "ship", "figures": 2, "caption": "Three hours in the water"})
    assert E.directive_for(beat) == GOLDEN["stick_scene"]
    beat, _ = E.normalize_beat({
        "kind": "collage",
        "prompts": "a torn train ticket on a wooden table; a rain-streaked window at dusk",
        "caption": "The last clue"})
    assert E.directive_for(beat) == GOLDEN["paper_collage"]
    # An unknown action/prop is a reason to drop, or repaired to "none".
    assert E.normalize_beat({"kind": "stick_scene", "action": "fly", "scene": "x"})[0] is None
    beat, _ = E.normalize_beat({"kind": "stick_scene", "action": "idle", "scene": "x", "prop": "spaceship"})
    assert beat["prop"] == "none"
    assert E.normalize_beat({"kind": "paper_collage", "prompts": "only one"})[0] is None


# --- M12: flow_diagram + icon_list + ui_mockup + callout -----------------------------------

def test_m12_flow_icons_ui_callout_pin_buzzedits_grammar():
    beat, _ = E.normalize_beat({"kind": "flow", "steps": "Water heats up; Steam rises; Clouds form; Rain falls",
                                 "layout": "CYCLE"})
    assert E.directive_for(beat) == GOLDEN["flow_diagram"]
    beat, _ = E.normalize_beat({"kind": "icons", "labels": ["+ Easy to learn", "- Takes longer to master"],
                                 "mode": "pros_cons"})
    assert E.directive_for(beat) == GOLDEN["icon_list"]
    beat, _ = E.normalize_beat({"kind": "ui", "type": "CHAT",
                                 "text": "Did you hear about the ship? // > No, what happened",
                                 "name": "Alex", "handle": "@alex99"})
    assert E.directive_for(beat) == GOLDEN["ui_mockup"]
    beat, _ = E.normalize_beat({"kind": "callout", "image_prompt": "a muddy boot print beside the fence",
                                 "mark": "CIRCLE", "at": "bottom_right", "label": "The print"})
    assert E.directive_for(beat) == GOLDEN["callout"]
    # Too few steps/labels, an unknown ui type, and a missing image_prompt are each a reason to drop.
    assert E.normalize_beat({"kind": "flow_diagram", "steps": ["only one"]})[0] is None
    assert E.normalize_beat({"kind": "icon_list", "labels": ["only one"]})[0] is None
    assert E.normalize_beat({"kind": "ui_mockup", "type": "carrier_pigeon", "text": "hi"})[0] is None
    assert E.normalize_beat({"kind": "callout"})[0] is None


# --- the planner sees the catalog ---------------------------------------------------------

def test_the_menu_lists_every_kind_with_its_example():
    menu = E.prompt_section("vlog", "motivational")
    for effect in E.CATALOG:
        assert f"**{effect.kind}**" in menu
    assert "Best fits for this video: statement_card" in menu


def test_documentary_genres_lead_with_documentary_graphics():
    assert E.favourites_for("horror")[0] == "source_quote"


def _window(words):
    return Window(index=0, word_start=0, word_end=len(words), start=0.0, end=10.0,
                  words=[{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate(words)])


def test_the_window_prompt_carries_the_catalog():
    prompt = build_window_prompt(_window(["hello", "world"]), [], "vlog", None, ["flicker"], 4.0)
    assert "### Effect catalog" in prompt and "statement_card" in prompt


def test_window_beats_are_repaired_and_broken_ones_dropped():
    words = ["main", "financially", "free", "hona", "chahta", "hoon"]
    window = _window(words)
    raw = ('{"beats": ['
           '{"word_start": 1, "word_end": 3, "kind": "chips", "items": "Financially free; Retire parents"},'
           '{"word_start": 3, "word_end": 5, "kind": "source_quote", "text": "no source here"}]}')
    beats = parse_window_beats(raw, window, window.words)
    assert [b["kind"] for b in beats] == ["pill_labels"]
    assert beats[0]["items"] == ["Financially free", "Retire parents"]
    assert beats[0]["prompt"] == "Financially free; Retire parents"


def test_designed_effects_are_spaced_out():
    beats = [{"kind": "statement_card", "start": 10.0}, {"kind": "statement_card", "start": 40.0},
             {"kind": "broll_image", "start": 41.0}, {"kind": "statement_card", "start": 90.0},
             {"kind": "numbered_point", "start": 95.0}, {"kind": "point", "start": 99.0}]
    kept = E.space_beats(beats)
    assert [(b["kind"], b["start"]) for b in kept] == [
        ("statement_card", 10.0), ("broll_image", 41.0), ("statement_card", 90.0),
        ("numbered_point", 95.0)]


def test_the_menu_says_prompts_are_english():
    assert "ALWAYS written in English" in E.prompt_section()


def test_a_sentence_is_not_a_name_title():
    fixed, reason = E.normalize_beat({"kind": "name_title", "text": "Main ek software engineer"})
    assert fixed is None and "name" in reason
    fixed, _ = E.normalize_beat({"kind": "name_title", "text": "Major Mohit Sharma", "subtext": "1 PARA SF"})
    assert fixed["text"] == "Major Mohit Sharma"


# --- SW3: stick_scene gains era/outfit/bg (Stick World) --------------------------------------

def test_stick_scene_era_outfit_bg_pin_the_contract_grammar():
    beat, _ = E.normalize_beat({
        "kind": "stick", "action": "point", "scene": "a Greek library court", "era": "ANCIENT_GREECE",
        "outfit": "chiton+laurel+scroll+beard; toga+staff",
        "bg": "the camera pans across ancient Greek library courtyard, marble columns, scroll shelves",
        "caption": "Athens, 399 BC"})
    # figures defaults to the number of outfit specs given, era/outfit lower-cased,
    # and the bg prompt has its camera wording rewritten out (story_visuals.without_camera).
    assert beat["era"] == "ancient_greece" and beat["figures"] == 2
    assert beat["outfit"] == "chiton+laurel+scroll+beard ; toga+staff"
    assert "camera" not in beat["bg"]
    directive = E.directive_for(beat)
    assert directive.startswith("[stick: action=point | scene=a Greek library court | "
                                "era=ancient_greece | outfit=chiton+laurel+scroll+beard ; toga+staff | ")
    assert "caption=Athens, 399 BC" in directive
    # An unknown era/outfit token is dropped, not passed on, and the
    # untouched example still pins the old GOLDEN directive exactly.
    beat2, _ = E.normalize_beat({"kind": "stick", "action": "idle", "scene": "x",
                                  "era": "atlantis", "outfit": "spacesuit+laurel+nonsense_hat"})
    # "nonsense_hat" is outside the vocabulary (dropped); "spacesuit" (body)
    # and "laurel" (head) are different categories, so both are kept.
    assert beat2["era"] == "" and beat2["outfit"] == "spacesuit+laurel"
    assert E.directive_for({"kind": "stick_scene", "action": "swim", "scene": "crossing a dark sea at night",
                            "prop": "ship", "figures": 2, "caption": "Three hours in the water"}) == \
        GOLDEN["stick_scene"]


def test_stick_world_vocabulary_pinned_against_buzzedit():
    """`integrations/stick_world.json` is a byte-identical copy of BuzzEdit's
    `motion/src/stick_world.json` (STICK_WORLD_PLAN.md); compared only when
    the sibling checkout is there."""
    buzzedit_path = Path(__file__).resolve().parents[3] / "BuzzEdit" / "motion" / "src" / "stick_world.json"
    if not buzzedit_path.is_file():
        pytest.skip("BuzzEdit checkout not beside this repo")
    assert buzzedit_path.read_bytes() == E._STICK_WORLD_PATH.read_bytes()
    assert "ancient_greece" in E.STICK_ERAS and len(E.STICK_ERAS) >= 20
