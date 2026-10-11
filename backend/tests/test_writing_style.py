"""`app/services/writing_style.py` -- the creator's own style: what the
writing agents are given, and how a draft is scored against it."""
from types import SimpleNamespace

import pytest

from app.services import writing_style as W

# His manner, roughly: short Roman-Hinglish lines, '...' before a turn, talks to "aap".
HIS = """Raat ke teen baje... gaon ki gali khaali thi. Ramesh akela tha. Uske haath mein lantern tha.
Hawa ruk gayi. Peeche se awaaz aayi... "Ramesh."

Aap sochiye. Aadhi raat, sunsaan raasta, aur koi aapka naam leta hai. Ramesh ruk gaya. Usne mud ke nahi dekha.
Kyunki gaon ka pehla niyam yahi tha... peeche mat dekhna. Doston, ye niyam kisi ne likha nahi tha.

Subah tak Ramesh ghar nahi pahuncha. Uska lantern gali ke beech mein mila. Bujha hua. Aur uske paas,
mitti mein, nange pairon ke nishaan the. Ulte. Aap samajh rahe hain na... ulte pair.
"""
HIS_2 = """Ek purani haveli. Teen kamre. Ek kamra hamesha band rehta tha. Aap sochiye, kyun?
Gaon wale kehte the... wahan koi rehta hai. Raat ko diya jalta hai. Doston, haveli mein koi nahi rehta.
Phir bhi diya jalta hai. Har raat. Ek baje. Aur bujhta hai... teen baje. Aap samajh rahe hain na.
"""
OFF = """This is a deeply unsettling story about a village where the night carries an ancient and terrifying
secret that nobody has ever been able to explain in a satisfying or rational manner, and it is a story
that will make you question everything that you think you know about the world and the spirits in it.
The villagers have always believed that there is something waiting in the darkness for anyone who is
foolish enough to wander the lonely roads after midnight without any protection whatsoever.
"""


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "STYLE_DIR", str(tmp_path / "style"))


def test_no_samples_means_no_section_and_no_check():
    assert W.style_section("Raat3Baje") == ""
    assert W.check(HIS, "Raat3Baje") is None


def test_brand_names_map_to_the_channel_folders():
    assert W.canonical_channel("After Dark") == "Raat3Baje"
    assert W.canonical_channel("Raat 3 Baje") == "Raat3Baje"
    assert W.canonical_channel("Beyond 3 Baje") == "Beyond3Baje"


def test_a_sample_is_measured_and_handed_to_the_writers():
    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    W.add_sample("Raat3Baje", "Haveli", HIS_2)
    W.save_text("Raat3Baje", "notes", "- Always end on a question.\nNever use: bhayanak, khaufnak")
    fp = W.targets("Raat3Baje")
    assert fp["source"] == "written" and fp["sentence_avg"] < 8 and fp["devanagari_share"] == 0
    assert fp["english_share"] < 0.2 and fp["address_per_1000"] > 10
    assert "aap samajh rahe hain" in " ".join(fp["phrases"])     # repeated across both pieces
    section = W.style_section("Raat3Baje")
    assert "The Creator's Own Writing Style" in section
    assert "Always end on a question." in section                # his own rules, first
    assert "Roman letters" in section and "words on average" in section
    assert "> " in section                                       # an excerpt of his own words
    assert W.never_words("Raat3Baje") == ["bhayanak", "khaufnak"]


def test_a_draft_in_his_manner_scores_high_and_a_generic_one_low():
    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    W.add_sample("Raat3Baje", "Haveli", HIS_2)
    W.save_text("Raat3Baje", "notes", "Never use: terrifying")
    # His own samples measured against themselves: originality is not the point here.
    good = W.check(HIS_2 + "\n" + HIS, "Raat3Baje", originality=False)
    bad = W.check(OFF, "Raat3Baje")
    assert good["score"] >= 85 and bad["score"] < 50
    assert any("Sentences average" in f for f in bad["fixes"])
    assert any("English" in f for f in bad["fixes"])
    assert any("terrifying" in f for f in bad["fixes"])
    devanagari = W.check("रात के तीन बजे गाँव की गली खाली थी। " * 20, "Raat3Baje")
    assert any("Roman letters" in f for f in devanagari["fixes"])


def test_a_recording_teaches_openings_but_not_sentence_numbers():
    rendered = ("# Intro\n\nHello doston mera naam hai Sudhanshu aur aap dekh rahe hain Raat 3 Baje "
                "[music: eerie drone] " + " ".join(["aaj ki kahani bahut alag hai aap sochiye"] * 12))
    assert W.save_recording("Raat3Baje", "p1", "Ep 1", rendered, pairs=[])
    fp = W.targets("Raat3Baje")
    assert fp["source"] == "spoken" and "sentence_avg" not in fp
    assert fp["openings"][0].startswith("Hello doston mera naam hai Sudhanshu")
    assert "[music" not in W._read(W._dir("Raat3Baje", "recordings", "p1.md"))


def test_only_real_rephrasings_are_kept_from_a_recording():
    script = "Arjun ne dheere se darwaza khola aur andar dekha . Phir woh ruk gaya".split()
    said = "Arjun ne aahista se darwaza khola aur andar jhaanka . Phir woh ruk gaya".split()
    pairs = W.rewrite_pairs(script, said, {0: 0, 1: 1, 4: 4, 5: 5, 6: 6, 9: 9, 10: 10, 11: 11})
    assert {"script": "dheere se", "said": "aahista se"} in pairs
    # A skipped passage lined up with a misheard ad-lib is not a rephrasing.
    junk = W.rewrite_pairs("Ab ek interesting sawaal hai rules horror ka . Aage".split(),
                           "to doshton ramadar rijistar chauradhava kaisi laga . Aage".split(),
                           {0: 0, 10: 10})
    assert junk == []


def test_the_workflow_rewrites_a_draft_that_is_off_style_and_keeps_the_better_one():
    from runtime.workflow import WorkflowEngine

    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    W.add_sample("Raat3Baje", "Haveli", HIS_2)
    asked = []

    class Agent:
        def execute(self, task, require_json=False):
            asked.append(task)
            return HIS + "\n" + HIS_2

    project = SimpleNamespace(brand="Raat3Baje", metadata={})
    step = SimpleNamespace(output_asset_type="script")
    log = SimpleNamespace(logs=[])
    engine = WorkflowEngine.__new__(WorkflowEngine)
    out = engine._match_creator_style(project, step, Agent(), OFF * 2, log, may_revise=True)
    assert asked and "The Creator's Own Writing Style" in asked[0] and "Sentences average" in asked[0]
    assert out.startswith("Raat ke teen baje")
    assert project.metadata["style_match"]["script"]["score"] >= 75
    # A long (sectioned) script is only scored, never rewritten in one call.
    asked.clear()
    engine._match_creator_style(project, step, Agent(), OFF * 2, log, may_revise=False)
    assert asked == [] and project.metadata["style_match"]["script"]["score"] < 50


def test_a_never_word_he_actually_uses_is_dropped_from_the_profile_but_not_from_his_notes():
    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    W.save_text("Raat3Baje", "profile", "## Never\nNever use: doston, delve, formal literary phrasing of any kind")
    assert W.never_words("Raat3Baje") == ["delve"]          # he says "doston"; the last is a description
    W.save_text("Raat3Baje", "notes", "Never use: doston")
    assert "doston" in W.never_words("Raat3Baje")            # his own rule always stands


def test_the_toggle_switches_between_his_style_and_the_agents_own():
    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    mine = SimpleNamespace(metadata={"writing_style": "mine"})
    agent = SimpleNamespace(metadata={"writing_style": "agent"})
    inherit = SimpleNamespace(metadata={})

    assert W.channel_mode("Raat3Baje") == "mine"                       # the default
    assert W.style_section("Raat3Baje") and W.style_section("Raat3Baje", inherit)
    assert W.style_section("Raat3Baje", agent) == ""                   # a project opts out

    W.set_channel_mode("Raat3Baje", "agent")
    assert W.overview("Raat3Baje")["mode"] == "agent"
    assert W.style_section("Raat3Baje") == "" and W.style_section("Raat3Baje", inherit) == ""
    assert W.style_section("Raat3Baje", mine)                          # a project opts back in
    assert "The Creator's Own Writing Style" in W.revise_task("Raat3Baje", HIS, {"fixes": []}, mine)
    with pytest.raises(ValueError):
        W.set_channel_mode("Raat3Baje", "robot")


def test_agent_style_is_neither_scored_nor_rewritten():
    from runtime.workflow import WorkflowEngine

    W.add_sample("Raat3Baje", "Ulte pair", HIS)
    W.add_sample("Raat3Baje", "Haveli", HIS_2)
    asked = []
    agent = SimpleNamespace(execute=lambda task, require_json=False: asked.append(task) or HIS)
    project = SimpleNamespace(brand="Raat3Baje", metadata={"writing_style": "agent"})
    engine = WorkflowEngine.__new__(WorkflowEngine)
    out = engine._match_creator_style(project, SimpleNamespace(output_asset_type="script"), agent,
                                      OFF * 2, SimpleNamespace(logs=[]), may_revise=True)
    assert out == OFF * 2 and asked == [] and "style_match" not in project.metadata


# His written manner when he tells a story as the person it happened to:
# long paragraphs, first person, no cues.
NARRATED = """Yeh un dinon ki baat hai jab main naya naya duty par join hua tha. Meri pehli posting mere ghar se bahut door ki gayi thi aur mujhe wahan bas do mahine hue the. Us din dopahar ko humein ek khabar mili ki jungle ke raste se kisi cheez ki taskari hone wali hai. Isliye main aur mere saath do vanrakshak us ilaake mein gasht laga rahe the. Maine socha ki aaj raat main chowki par hi ruk jaunga. Mere saathi ne mujhe roka aur kaha, "Sir, yahan raat mein koi nahi rukta." Par maine uski baat nahi maani kyunki mujhe us par shak ho raha tha. Doston, aap sochiye ki us waqt mere dimaag mein kya chal raha hoga.

Raat ke gyarah baje mujhe bahar se kisi ke chalne ki awaaz aayi. Maine khidki se bahar dekha par wahan koi nahi tha. Mera dil zor zor se dhadakne laga aur mere haath thande pad gaye. Maine apni torch uthayi aur darwaze ke paas jaakar khada ho gaya. Mujhe laga ki shayad koi jaanwar hoga, isliye maine darwaza nahi khola. Par phir wahi awaaz dobara aayi aur is baar woh bilkul mere darwaze ke paas thi. Maine dheere se poochha ki kaun hai, lekin kisi ne jawab nahi diya. Us raat maine pehli baar mehsoos kiya ki main us jungle mein akela nahi tha.
"""
SCREENPLAY = """## [SECTION 1: The Call]

[SOUND: Heavy crunching of dry leaves under boots.]

[VISUAL: Close-up of a hand holding a cracked smartphone.]

**ARJUN (V.O.)**
(slow)
Tumhari awaaz...
(pause)
Kyun yahan se aa rahi hai?

[VISUAL: Cut to Arjun's face, sweat on his forehead.]

**ARJUN (V.O.)**
(normal)
Raat ka waqt... Sahyadri ki pahadiyan.
(pause)
Arjun ek experienced forest officer tha.
""" * 6


def test_only_the_words_that_are_said_are_counted():
    assert W.narration_words("**ARJUN (V.O.)**\n(slow)\nTumhari awaaz... [SOUND: static]\n(pause)\nKyun aa rahi hai?") == 6
    assert W.narration_words("## Heading\n\nNARRATOR: Raat ka waqt tha.") == 4
    assert W.stage_share(SCREENPLAY) > 0.5 and W.stage_share(NARRATED) == 0


def test_his_narration_format_is_asked_for_and_a_screenplay_is_marked_down():
    W.add_sample("Raat3Baje", "Chowki", NARRATED)
    assert W.narration_format("Raat3Baje")
    section = W.style_section("Raat3Baje")
    assert "continuous narration" in section and "Point of view: first person" in section
    assert "overrides the task" in W.format_override("Raat3Baje")
    bad = W.check(SCREENPLAY, "Raat3Baje")
    assert bad["score"] < 50
    assert any("stage directions" in f for f in bad["fixes"])
    assert any("First-person" in f for f in bad["fixes"])
    assert "Turn every stage direction" in W.revise_task("Raat3Baje", SCREENPLAY, bad)
    assert W.check(NARRATED, "Raat3Baje", originality=False)["score"] >= 85
    # Agent style, or a channel with recordings only, keeps the cue format.
    assert not W.narration_format("Raat3Baje", SimpleNamespace(metadata={"writing_style": "agent"}))
    assert not W.narration_format("Life3Baje") and W.format_override("Life3Baje") == ""


def test_the_greeting_is_his_name_and_the_channel_word_for_word():
    line = "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje."
    assert W.greeting("Raat3Baje") == line
    assert W.greeting("Beyond 3 Baje").endswith("aap dekh rahe hain Beyond 3 Baje.")
    W.add_sample("Raat3Baje", "Chowki", NARRATED)
    assert line in W.style_section("Raat3Baje")
    # A greeting borrowed from a sample (another host, another show) is replaced.
    borrowed = ("## Kahani\n\nNamaskar doston, main hoon Shivraj aur aap sun rahe hain Horror Podcast Shivraj ke saath. "
                "Doston, aaj ki kahani ek subscriber ki hai.\n\n" + NARRATED)
    fixed, changed = W.ensure_greeting(borrowed, "Raat3Baje")
    assert changed and "Shivraj" not in fixed and fixed.startswith("## Kahani\n\n" + line + " Doston, aaj ki kahani")
    # None at all: it becomes the first spoken line. Already there: untouched.
    fixed, changed = W.ensure_greeting("## Kahani\n\n" + NARRATED, "Raat3Baje")
    assert changed and fixed.startswith("## Kahani\n\n" + line + "\n\nYeh un dinon")
    assert W.ensure_greeting(fixed, "Raat3Baje") == (fixed, False)
    # His own `Greeting:` rule replaces the default.
    W.save_text("Raat3Baje", "notes", "Greeting: Namaste doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje.")
    assert W.greeting("Raat3Baje").startswith("Namaste doston, mera naam hai Sudhansu")


def test_a_guide_older_than_his_samples_is_rebuilt_before_writing(monkeypatch):
    assert W.ensure_current("Raat3Baje") is None                       # nothing to learn from yet
    W.save_recording("Raat3Baje", "p1", "Ep 1", "Hello doston " + "aaj ki kahani bahut alag hai aap sochiye " * 20)
    W.save_text("Raat3Baje", "profile", "## Sentence rhythm\nShort fragments, then a '...' pause.")
    W._write(W._dir("Raat3Baje", "state.json"), '{"stale": false, "written": 0, "spoken": 1}')
    assert W.ensure_current("Raat3Baje") is None                       # up to date
    W.add_sample("Raat3Baje", "Chowki", NARRATED)                      # he adds his own writing
    assert W.needs_rebuild("Raat3Baje")
    assert "Short fragments" not in W.style_section("Raat3Baje")       # the outdated guide is not handed out
    built = []

    def fake_build(channel, llm=None):
        built.append(channel)
        W.save_text(channel, "profile", "## Sentence rhythm\nLong flowing sentences.")
        W._write(W._dir(channel, "state.json"), '{"stale": false, "written": 1, "spoken": 1}')
        return W.overview(channel)

    monkeypatch.setattr(W, "build_profile", fake_build)
    assert "rebuilt" in W.ensure_current("Raat3Baje")
    assert built == ["Raat3Baje"] and "Long flowing sentences" in W.style_section("Raat3Baje")
    assert W.ensure_current("Raat3Baje") is None
    assert W.ensure_current("Raat3Baje", SimpleNamespace(metadata={"writing_style": "agent"})) is None

    def broken(channel, llm=None):
        raise RuntimeError("no model")

    W.add_sample("Raat3Baje", "Chowki 2", NARRATED)
    monkeypatch.setattr(W, "build_profile", broken)
    assert "could not be rebuilt" in W.ensure_current("Raat3Baje")     # never raises into a step


def test_a_channel_keeps_several_saved_styles_and_writes_in_the_selected_one():
    W.add_sample("Raat3Baje", "Ulte pair", HIS)                       # the default style: short lines
    W.add_sample("Raat3Baje", "Haveli", HIS_2)
    W.set_channel_mode("Raat3Baje", "mine")
    assert [s["id"] for s in W.list_styles("Raat3Baje")] == ["default"]
    assert W.narration_format("Raat3Baje") and "first person" not in W.style_section("Raat3Baje")

    view = W.create_style("Raat3Baje", "Podcast storyteller")         # a new, empty style, selected at once
    assert view["style"] == "podcast_storyteller" and view["samples"] == []
    assert W.style_section("Raat3Baje").count("In his own words") == 0
    W.add_sample("Raat3Baje", "Chowki", NARRATED)
    assert "Point of view: first person" in W.style_section("Raat3Baje")
    assert W.targets("Raat3Baje")["sentence_avg"] > 10

    back = W.select_style("Raat3Baje", "default")                     # the first one is untouched
    assert [(s["name"], s["active"], s["written"]) for s in back["styles"]] == [
        ("Default", True, 2), ("Podcast storyteller", False, 1)]
    assert W.targets("Raat3Baje")["sentence_avg"] < 8
    assert W.channel_mode("Raat3Baje") == "mine"                      # the channel's settings survive

    copy = W.create_style("Raat3Baje", "Short lines v2", copy=True)   # a copy of the style in use
    assert copy["style"] == "short_lines_v2" and len(copy["samples"]) == 2
    W.delete_sample("Raat3Baje", copy["samples"][0]["id"])            # editing the copy leaves the original
    assert len(W.select_style("Raat3Baje", "default")["samples"]) == 2

    W.rename_style("Raat3Baje", "default", "My recordings")
    W.rename_style("Raat3Baje", "podcast_storyteller", "Storyteller")
    assert [s["name"] for s in W.list_styles("Raat3Baje")] == ["My recordings", "Storyteller", "Short lines v2"]
    with pytest.raises(ValueError):
        W.create_style("Raat3Baje", "storyteller")                    # names are unique
    with pytest.raises(ValueError):
        W.delete_style("Raat3Baje", "default")
    with pytest.raises(ValueError):
        W.select_style("Raat3Baje", "../../etc")

    W.select_style("Raat3Baje", "podcast_storyteller")
    gone = W.delete_style("Raat3Baje", "podcast_storyteller")         # deleting the selected one falls back
    assert gone["style"] == "default" and len(gone["styles"]) == 2
    assert W.list_styles("Beyond3Baje")[0]["id"] == "default"         # every channel has its own


# --- the greeting once, and his examples as manner only ---------------------------------

GREETING = "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje."
OPENING = (GREETING + " Doston, aaj ki yeh kahani ek subscriber ke anubhav par aadharit hai. Aap sabhi se request hai "
           "ki agar aap channel par naye hain toh subscribe karein. Toh chaliye ab bina waqt zaya kiye aaj ki kahani "
           "ko sunte hain. Yeh baat 1999 ki hai.")


def test_a_greeting_repeated_in_the_middle_is_removed_with_its_opening_lines():
    body = "Main chowki par akela tha. Raat ke do baje the."
    script = ("## Pehli raat\n\n" + OPENING + "\n\n" + body + "\n\n## Doosri raat\n\n" + OPENING + "\n\n" + body
              + "\n\n" + GREETING + "\n\nDoston, aaj ki yeh kahani ek officer ke anubhav par aadharit hai. "
              "Toh chaliye ab bina waqt zaya kiye aaj ki kahani ko sunte hain.\n\nUs raat ki baat hai.")
    out, removed = W.strip_repeated_intro(script)
    assert removed == 2 and out.count(GREETING) == 1
    assert out.count("subscribe karein") == 1 and out.count("aadharit") == 1 and out.count("chaliye") == 1
    assert out.count(body) == 2 and "Us raat ki baat hai." in out and "## Doosri raat" in out
    # A middle piece keeps none at all.
    out, removed = W.strip_repeated_intro(OPENING + "\n\n" + body, keep_first=False)
    assert removed == 1 and GREETING not in out and out.startswith("Yeh baat 1999 ki hai.")
    # Nothing to do: untouched.
    assert W.strip_repeated_intro(body) == (body, 0)
    # ensure_greeting does the same before it checks the first one.
    fixed, changed = W.ensure_greeting(script, "Raat3Baje")
    assert changed and fixed.count(GREETING) == 1


def test_a_repeated_greeting_and_copied_sample_lines_score_down():
    W.add_sample("Raat3Baje", "Chowki", NARRATED)
    clean = W.check(NARRATED.replace("Yeh un dinon", "Woh un dinon"), "Raat3Baje")
    twice = W.check(GREETING + " " + NARRATED + "\n\n" + GREETING + " Doston, aaj ki kahani.", "Raat3Baje")
    assert twice["score"] < clean["score"] and any("Greets the viewer 2 times" in f for f in twice["fixes"])
    # The sample retold word for word is flagged; its manner in new words is not.
    ratio, runs = W.sample_copy_ratio(NARRATED, "Raat3Baje")
    assert ratio > 0.5 and runs
    copied = W.check(NARRATED, "Raat3Baje")
    assert any("copied word for word from his examples" in f for f in copied["fixes"])
    own = "Main us raat chowki par akela tha. " * 30
    assert W.sample_copy_ratio(own, "Raat3Baje")[0] == 0.0
    # The guide and the rewrite task say the greeting is said once.
    assert "ONCE" in W.style_section("Raat3Baje")
    assert "do not add the\ngreeting" in W.revise_task("Raat3Baje", own, {"fixes": []})
