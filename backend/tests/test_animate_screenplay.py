import pytest

from app.services import animate_screenplay as asp

SCRIPT = ('Us raat main akela tha. Ek budhi aurat ne kaha, "Itni raat ko yahan kya kar rahe ho, beta?" '
          'Main chup raha.')
CAST = [{"id": "MAIN", "name": "Ramesh", "first_person": True, "look": "thin", "age": "30", "clothes": "kurta"},
        {"id": "AMMA", "name": "Budhi Amma", "first_person": False, "look": "frail", "age": "70"}]


def _labels(units):
    return {"scenes": {1: "EXT. LANE - NIGHT"}, "speakers": {3: "AMMA"},
            "tags": {3: [{"character": "Budhi Amma", "pose": "sitting", "position": "right"}]}, "actions": {}}


def test_units_keep_exact_text():
    u = asp.split_units(SCRIPT)
    assert [x["kind"] for x in u] == ["narr", "narr", "quote", "narr"]
    assert u[2]["text"] == "Itni raat ko yahan kya kar rahe ho, beta?"
    assert " ".join(x["text"] for x in u) == asp.source_spoken(SCRIPT)


def test_assemble_and_verify():
    u = asp.split_units(SCRIPT)
    sp = asp.assemble(u, CAST, _labels(u))
    assert "## SCENE 1 — LANE" in sp and "**BUDHI AMMA**  \n" in sp and "[Budhi Amma: sitting, right]" in sp
    asp.verify(sp, SCRIPT)


def test_reworded_line_fails():
    u = asp.split_units(SCRIPT)
    sp = asp.assemble(u, CAST, _labels(u)).replace("kya kar rahe ho", "kya kar rahi ho")
    with pytest.raises(asp.ScreenplayError):
        asp.verify(sp, SCRIPT)
