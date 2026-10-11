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
    "transition": "[fx: whiteflash dur=0.5]",
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
