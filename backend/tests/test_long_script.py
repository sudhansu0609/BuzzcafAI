"""
Long scripts written section by section (runtime/long_script.py): the plan,
continuation of short sections, checkpoint/resume, repetition retry, and the
chunked rewrite that never loses text.
"""

import itertools
import json
import os
import re

import pytest

from runtime import long_script as ls

_counter = itertools.count()


def fresh_words(n: int) -> str:
    """n words that never repeat anywhere (so repetition checks stay quiet)."""
    return " ".join(f"shabd{next(_counter)}" for _ in range(n))


class FakeLLM:
    def __init__(self, sections=6, first_short=False, repeat_once_at=None, truncate_parts=()):
        self.config = {}
        self.calls = []
        self.sections = sections
        self.first_short = first_short
        self.repeat_once_at = repeat_once_at
        self.truncate_parts = set(truncate_parts)
        self.first_text = None

    def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
        self.calls.append(user_prompt)
        if require_json:
            return json.dumps({"bible": {"characters": [{"name": "Raghav"}], "rules": ["1. Never look back"]},
                               "sections": [{"title": f"S{i}", "purpose": "p", "beats": ["b"], "words": 100}
                                            for i in range(self.sections)]})
        m = re.search(r"This is PART (\d+) of", user_prompt)
        if m:
            chunk = user_prompt.rsplit("<<<", 1)[1].rsplit(">>>", 1)[0]
            return "ok" if int(m.group(1)) in self.truncate_parts else chunk.upper()
        if "It is unfinished" in user_prompt:
            return fresh_words(600) + "\nSUMMARY: finished it"
        m = re.search(r"Write SECTION (\d+) of", user_prompt)
        i = int(m.group(1))
        if i == 1 and self.first_short and not any("It is unfinished" in c for c in self.calls):
            return fresh_words(100) + "\nSUMMARY: started"
        if i == 1:
            self.first_text = fresh_words(700)
            return self.first_text + "\nSUMMARY: opening"
        if self.repeat_once_at == i:
            self.repeat_once_at = None
            return self.first_text + "\nSUMMARY: repeated"
        return f"## [SECTION {i}]\n" + fresh_words(700) + f"\nSUMMARY: section {i}"


class FakeAgent:
    def __init__(self, llm):
        self.llm_service = llm
        self.system_prompt = "persona"
        self.model_tier = "strong"
        self.temperature = 0.7

    def refresh_prompt(self):
        pass


def test_thresholds():
    assert not ls.should_section({}, 12 * 140)
    assert ls.should_section({}, 60 * 140)
    assert not ls.should_section({"long_script_mode": "off"}, 90 * 140)
    assert ls.should_section({"long_script_mode": "always"}, 700)


def test_writes_every_section_and_hits_the_length(tmp_path):
    llm = FakeLLM(sections=6)
    w = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), lambda m: None)
    text = w.write("CONTEXT", 30, 4200)
    assert ls.words(text) >= 4200 * 0.9
    assert "SUMMARY" not in text
    assert len(list(tmp_path.glob("section_*.json"))) == 6
    # Later sections see the running summaries and the verbatim tail of the script.
    last = [c for c in llm.calls if "Write SECTION 6 of 6" in c][0]
    assert "Section 5: section 5" in last and "FINAL section" in last


def test_short_section_gets_continued(tmp_path):
    llm = FakeLLM(sections=3, first_short=True)
    w = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), lambda m: None)
    text = w.write("CONTEXT", 15, 2100)
    assert any("It is unfinished" in c for c in llm.calls)
    first = json.loads((tmp_path / "section_01.json").read_text(encoding="utf-8"))
    assert ls.words(first["text"]) >= 700


def test_repeated_section_is_rewritten(tmp_path):
    llm = FakeLLM(sections=3, repeat_once_at=2)
    logs = []
    ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), logs.append).write("CONTEXT", 15, 2100)
    assert any("repeated earlier material" in m for m in logs)
    second = json.loads((tmp_path / "section_02.json").read_text(encoding="utf-8"))
    assert ls.repetition_ratio(second["text"], [llm.first_text]) < 0.2


def test_resume_skips_finished_sections(tmp_path):
    llm = FakeLLM(sections=4)
    w = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), lambda m: None)
    w.write("CONTEXT", 20, 2800)
    os.remove(tmp_path / "section_04.json")
    llm2 = FakeLLM(sections=4)
    ls.LongScriptWriter(FakeAgent(llm2), {}, str(tmp_path), lambda m: None).write("CONTEXT", 20, 2800)
    assert len(llm2.calls) == 1 and "Write SECTION 4 of 4" in llm2.calls[0]


def test_chunked_rewrite_keeps_text_the_model_truncates():
    script = "\n\n".join(f"## [SCENE {i}]\n" + " ".join(f"line{i}w{k}" for k in range(500)) for i in range(4))
    llm = FakeLLM(truncate_parts={2})
    logs = []
    out = ls.rewrite_in_chunks(FakeAgent(llm), {}, "CONTEXT", script, logs.append)
    parts = ls.split_script(script, 900)
    assert len(parts) > 1
    assert ls.words(out) >= ls.words(script) * 0.95
    assert parts[1] in out  # part 2 was truncated twice -> original kept
    assert parts[0].upper() in out  # the others were rewritten
    assert any("kept the original" in m for m in logs)


def test_engine_writes_a_60_minute_script_in_sections_and_narrates_it_in_parts(monkeypatch):
    from core.models.project import Project
    from core.models.workflow import WorkflowDefinition, WorkflowStep
    from core.workflow import workflow_registry
    from executive.project import project_manager
    from runtime.workflow import WorkflowEngine

    engine = WorkflowEngine()  # first: its constructor resets the workflow registry
    workflow_registry.register(WorkflowDefinition(
        id="long_test_wf", name="Long Test", description="draft then narration",
        steps=[
            WorkflowStep(name="Draft", agent_role="WriterAgent", description="d", requires_approval=False,
                         input_assets=[], output_asset_type="script"),
            WorkflowStep(name="Narration", agent_role="EditorAgent", description="n", requires_approval=False,
                         input_assets=["script"], output_asset_type="narration_optimized"),
        ],
    ))
    project = project_manager.create_project("Long Probe", "Raat3Baje", "long_test_wf")
    try:
        project.metadata["target_duration_minutes"] = 60
        project.save()
        llm = FakeLLM(sections=12)
        monkeypatch.setattr(engine, "_resolve_agent", lambda role: FakeAgent(llm))
        p = engine.execute_all(project.id)
        assert p.status == "completed"
        with open(os.path.join(p.get_project_dir(), p.assets["script"]), encoding="utf-8") as f:
            draft = f.read()
        with open(os.path.join(p.get_project_dir(), p.assets["narration_optimized"]), encoding="utf-8") as f:
            narration = f.read()
        assert ls.words(draft) >= 60 * 140 * 0.9
        assert ls.words(narration) >= ls.words(draft) * 0.95
        assert any("section by section" in line for line in p.steps_history[0].logs)
        assert any("in parts" in line for line in p.steps_history[1].logs)
    finally:
        workflow_registry.unregister("long_test_wf")
        try:
            project_manager.delete_project(project.id)
        except Exception:
            pass


def test_clean_section_drops_a_chatbot_preamble():
    raw = ("Hello! I am your **Originals Strategist**. I am your primary partner.\n\n"
           "Here is how I can help you:\n- **Story Architecture**: x\n- **Original Fiction**: y\n\n"
           "What literary breakdown shall we refine today?\n\n"
           "Aryan ki zindagi koi ordinary kahani nahi thi. (slow)")
    out = ls.clean_section(raw, "## [SECTION 2: Setup]")
    assert out.startswith("## [SECTION 2: Setup]")
    assert "Originals Strategist" not in out and "help you" not in out
    assert "Aryan ki zindagi" in out
    # With the heading present, anything before it goes.
    assert ls.clean_section("Sure! Here it is:\n## [SECTION 3: X]\nline", "## [SECTION 3: X]") == "## [SECTION 3: X]\nline"


def test_simulated_replies_are_retried_never_written(monkeypatch, tmp_path):
    monkeypatch.setattr(ls.time, "sleep", lambda s: None)

    class Flaky(FakeLLM):
        def __init__(self, fail_times):
            super().__init__(sections=2)
            self.fail_times = fail_times
            self.last_response_simulated = False

        def generate_text(self, *a, **k):
            if self.fail_times:
                self.fail_times -= 1
                self.last_response_simulated = True
                return "Hello! I am your Originals Strategist."
            self.last_response_simulated = False
            return super().generate_text(*a, **k)

    text = ls.LongScriptWriter(FakeAgent(Flaky(2)), {}, str(tmp_path / "a"), lambda m: None).write("C", 10, 1400)
    assert "Originals Strategist" not in text

    with pytest.raises(RuntimeError, match="re-run the step to resume"):
        ls.LongScriptWriter(FakeAgent(Flaky(99)), {}, str(tmp_path / "b"), lambda m: None).write("C", 10, 1400)


def test_budgets_count_spoken_words_not_cues():
    cue_heavy = "[VISUAL: a long description of a dark forest at night]\n**ARJUN (V.O.)**\n(pause)\nRaat ka waqt tha."
    assert ls.words(cue_heavy) == 4


class StyleLLM(FakeLLM):
    """Writes screenplay sections; rewrites them as narration when asked to revise."""

    def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
        if user_prompt.startswith("REVISE"):
            self.calls.append(user_prompt)
            return "narrated " + fresh_words(700)
        return super().generate_text(system_prompt, user_prompt, require_json, tier, temperature)


def _gate():
    return ls.StyleGate(check=lambda text: {"score": 90 if "narrated" in text else 40, "fixes": ["x"]},
                        revise_task=lambda text, result: "REVISE " + text[:50], below=75, narration=True)


def test_each_section_is_rewritten_toward_the_creators_style(tmp_path):
    llm = StyleLLM(sections=3)
    logs = []
    text = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), logs.append, _gate()).write("CONTEXT", 15, 2100)
    assert sum(1 for c in llm.calls if c.startswith("REVISE")) == 3
    assert sum(1 for m in logs if "40 -> 90/100" in m) == 3
    assert text.count("narrated ") == 3
    # His format is asked for, not the screenplay one, and the plan follows his way of telling.
    section_prompt = [c for c in llm.calls if "Write SECTION 1 of 3" in c][0]
    assert "continuous narration" in section_prompt and "V.O. lines" not in section_prompt
    assert "his fixed greeting" in section_prompt
    assert "creator's own writing style" in llm.calls[0]
    # Chapters carry a plain title, not a [SECTION n: ...] slug.
    assert "## S0" in text and "[SECTION" not in text


def test_without_a_style_gate_the_cue_format_is_unchanged(tmp_path):
    llm = FakeLLM(sections=2)
    text = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), lambda m: None).write("CONTEXT", 10, 1400)
    section_prompt = [c for c in llm.calls if "Write SECTION 1 of 2" in c][0]
    assert "V.O. lines, [VISUAL]/[SOUND] cues" in section_prompt and "[SECTION 1:" in text


def test_a_rewritten_part_is_brought_back_to_his_style():
    script = "\n\n".join(f"## Scene {k}\n" + fresh_words(700) for k in range(3))
    llm = StyleLLM()
    out = ls.rewrite_in_chunks(FakeAgent(llm), {}, "CONTEXT", script, lambda m: None, _gate())
    assert out.count("narrated ") >= 2
    part_prompt = [c for c in llm.calls if "This is PART 1 of" in c][0]
    assert "stays so" in part_prompt and "every [VISUAL]/[SOUND] cue --" not in part_prompt


def test_the_hosts_greeting_is_not_taken_for_chat_preamble():
    out = ls.clean_section("Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje.\n\nKahani.",
                           "## [SECTION 1: X]")
    assert "Hello doston, mera naam hai Sudhansu" in out


# --- the greeting once, and a layered plan -------------------------------------------

GREETING = "Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje."
INTRO = (GREETING + " Doston, aaj ki yeh kahani ek subscriber ke anubhav par aadharit hai. Agar aap channel par "
         "naye hain toh subscribe karein. Toh chaliye ab bina waqt zaya kiye aaj ki kahani ko sunte hain. ")


class ReopeningLLM(FakeLLM):
    """A model that re-opens the video at the start of every section and part."""

    def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
        out = super().generate_text(system_prompt, user_prompt, require_json, tier, temperature)
        if require_json:
            return out
        m = re.search(r"This is PART (\d+) of", user_prompt)
        if m:
            return INTRO + out
        if re.search(r"Write SECTION (\d+) of", user_prompt):
            return INTRO + out
        return out


def test_only_the_opening_section_keeps_the_greeting(tmp_path):
    llm = ReopeningLLM(sections=3)
    logs = []
    text = ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path), logs.append).write("CONTEXT", 15, 2100)
    assert text.count("mera naam hai Sudhansu") == 1 and text.count("subscribe karein") == 1
    assert text.index("mera naam hai Sudhansu") < text.index("SECTION 2")
    assert sum(1 for m in logs if "repeated greeting" in m) == 2
    # The prompts say so too: the opening is told to greet once, the others not at all.
    first = [c for c in llm.calls if "Write SECTION 1 of 3" in c][0]
    second = [c for c in llm.calls if "Write SECTION 2 of 3" in c][0]
    assert "begins INSIDE the story" not in first and "begins INSIDE the story" in second


def test_a_rewrite_part_from_the_middle_loses_the_greeting_it_was_given():
    script = GREETING + " Kahani shuru.\n\n" + "\n\n".join(f"## Scene {k}\n" + fresh_words(700) for k in range(3))
    llm = ReopeningLLM()
    logs = []
    out = ls.rewrite_in_chunks(FakeAgent(llm), {}, "CONTEXT", script, logs.append)
    assert out.count("mera naam hai Sudhansu") == 1
    parts = [c for c in llm.calls if "This is PART" in c]
    assert "OPENING part" in parts[0] and all("MIDDLE or the END" in p for p in parts[1:])
    assert any("repeated greeting" in m for m in logs)


def test_the_plan_is_reviewed_as_a_layered_story_and_an_unusable_review_keeps_it(tmp_path):
    class Reviewing(FakeLLM):
        def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
            if "JUDGE and STRENGTHEN" in user_prompt:
                self.calls.append(user_prompt)
                plan = json.loads(super().generate_text(system_prompt, "x", True))
                plan["bible"]["twist"] = "the note was his own voice"
                return json.dumps(plan)
            return super().generate_text(system_prompt, user_prompt, require_json, tier, temperature)

    llm = Reviewing(sections=2)
    logs = []
    ls.LongScriptWriter(FakeAgent(llm), {}, str(tmp_path / "a"), logs.append).write("CONTEXT", 10, 1400)
    plan = json.loads((tmp_path / "a" / "plan.json").read_text(encoding="utf-8"))
    assert plan["bible"]["twist"] == "the note was his own voice" and plan["bible"]["rules"] == ["1. Never look back"]
    assert any("strengthened" in m for m in logs)
    review = [c for c in llm.calls if "JUDGE and STRENGTHEN" in c][0]
    assert "Is it layered" in review and "plants" in review
    # The plan prompt itself asks for layers, plants, escalation and an earned twist.
    assert '"layers"' in llm.calls[0] and '"plants"' in llm.calls[0] and "LAYERED story" in llm.calls[0]

    class Unusable(FakeLLM):
        def generate_text(self, system_prompt, user_prompt, require_json=False, tier=None, temperature=None):
            if "JUDGE and STRENGTHEN" in user_prompt:
                return "not json"
            return super().generate_text(system_prompt, user_prompt, require_json, tier, temperature)

    logs = []
    ls.LongScriptWriter(FakeAgent(Unusable(sections=2)), {}, str(tmp_path / "b"), logs.append).write("CONTEXT", 10, 1400)
    plan = json.loads((tmp_path / "b" / "plan.json").read_text(encoding="utf-8"))
    assert len(plan["sections"]) == 2 and any("unusable" in m for m in logs)
    # And it can be switched off.
    llm = FakeLLM(sections=2)
    ls.LongScriptWriter(FakeAgent(llm), {"long_script_plan_review": False}, str(tmp_path / "c"), lambda m: None).write("C", 10, 1400)
    assert not any("JUDGE and STRENGTHEN" in c for c in llm.calls)
