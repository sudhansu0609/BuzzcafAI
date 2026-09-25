"""
BuzzcafAI -> BuzzEdit effect directives: fx / atmos / grade visual-plan beats
become `[fx: ...]` / `[atmos: ...]` / `[grade: ...]` directives in the script,
and each brand carries a genre-appropriate effect palette.
"""

from integrations.buzzedit_script import to_directive_script
from integrations.buzzedit_settings import fx_palette_for, settings_for_brand


def test_fx_beat_becomes_a_directive():
    script = "The town went dark that night. Nobody spoke of it again."
    plan = {"beats": [{"anchor": "went dark", "kind": "fx", "effect": "flicker",
                       "intensity": 0.6, "duration": 0.5}]}
    out, skipped = to_directive_script(script, plan)
    assert "[fx: flicker" in out and "intensity=0.6" in out and "dur=0.5" in out
    assert skipped == []


def test_atmos_and_grade_beats():
    script = "It fell apart slowly over the years."
    plan = {"beats": [
        {"anchor": "fell apart", "kind": "atmos", "effect": "fog", "intensity": 0.4},
        {"anchor": "over the years", "kind": "grade", "data": {"saturation": 0.6, "vignette": 0.3}},
    ]}
    out, _ = to_directive_script(script, plan)
    assert "[atmos: fog" in out
    assert "[grade: saturation=0.6 vignette=0.3]" in out


def test_fx_palette_per_brand():
    assert settings_for_brand("Beyond3Baje")["genre"] == "documentary"
    assert "grain" in fx_palette_for("Beyond3Baje")       # documentary
    assert "flicker" in fx_palette_for("Raat3Baje")        # horror
    assert "redaction" in fx_palette_for("anything", genre="mystery")
    # The per-call override still merges after the settings refactor.
    assert settings_for_brand("Raat3Baje", {"target_coverage": 0.7})["target_coverage"] == 0.7
