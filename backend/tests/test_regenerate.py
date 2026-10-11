"""
Regenerate a project from a chosen step, and the guard that stops a rewrite
step (edit / narration) from saving a truncated or JSON-wrapped script.
"""

import os

import pytest

from core.models.project import Project
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.workflow import workflow_registry
from executive.project import project_manager
from runtime.workflow import WorkflowEngine, _unwrap_script

SCRIPT = "Raat ke do baje. " * 100  # 400 words


def test_unwrap_pulls_the_script_out_of_a_json_wrapper():
    wrapped = '```json\n{"status": "success", "results": {"script_final": "# Title\nline two"}}\n```'
    assert _unwrap_script(wrapped) == "# Title\nline two"
    assert _unwrap_script("# Plain\ntext") == "# Plain\ntext"
    # Broken JSON is returned as-is so the length check can reject it.
    assert _unwrap_script('{"status": "success", "results": {"script_final":_').startswith("{")


class FakeAgent:
    def __init__(self, reply):
        self.reply = reply

    def execute(self, instruction, require_json=False):
        return self.reply


@pytest.fixture
def engine():
    # Built first: its constructor re-discovers workflows, which resets the registry.
    return WorkflowEngine()


@pytest.fixture
def two_step_project(engine):
    wf = WorkflowDefinition(
        id="regen_test_wf", name="Regen Test", description="draft then narration",
        steps=[
            WorkflowStep(name="Draft", agent_role="WriterAgent", description="d", requires_approval=False,
                         input_assets=[], output_asset_type="script"),
            WorkflowStep(name="Narration", agent_role="EditorAgent", description="n", requires_approval=False,
                         input_assets=["script"], output_asset_type="narration_optimized"),
        ],
    )
    workflow_registry.register(wf)
    project = project_manager.create_project("Regen Probe", "Raat3Baje", "regen_test_wf")
    try:
        yield project
    finally:
        workflow_registry.unregister("regen_test_wf")
        try:
            project_manager.delete_project(project.id)
        except Exception:
            pass


def test_truncated_narration_fails_and_saves_nothing(monkeypatch, engine, two_step_project):
    monkeypatch.setattr(engine, "_resolve_agent", lambda role: FakeAgent(SCRIPT))
    engine.execute_next(two_step_project.id)  # Draft

    monkeypatch.setattr(engine, "_resolve_agent",
                        lambda role: FakeAgent('```json\n{"status": "success", "results": {"script_final":_'))
    with pytest.raises(ValueError, match="nothing was saved"):
        engine.execute_next(two_step_project.id)
    p = Project.load(two_step_project.id)
    assert p.steps_history[-1].status == "failed"
    assert "narration_optimized" not in p.assets


def test_wrapped_narration_is_unwrapped(monkeypatch, engine, two_step_project):
    monkeypatch.setattr(engine, "_resolve_agent", lambda role: FakeAgent(SCRIPT))
    engine.execute_next(two_step_project.id)
    monkeypatch.setattr(engine, "_resolve_agent",
                        lambda role: FakeAgent('{"results": {"script_final": "' + SCRIPT + '"}}'))
    engine.execute_next(two_step_project.id)
    p = Project.load(two_step_project.id)
    with open(os.path.join(p.get_project_dir(), p.assets["narration_optimized"]), encoding="utf-8") as f:
        saved = f.read().strip()
    # The script itself, unwrapped -- under the creator's fixed greeting, which
    # every full script opens with (writing_style.ensure_greeting).
    assert saved.endswith(SCRIPT.strip()) and "{" not in saved
    assert saved.startswith("Hello doston, mera naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje.")


def test_restart_rewinds_from_a_step_and_keeps_the_rest(monkeypatch, engine, two_step_project):
    monkeypatch.setattr(engine, "_resolve_agent", lambda role: FakeAgent(SCRIPT))
    engine.execute_all(two_step_project.id)
    p = Project.load(two_step_project.id)
    assert p.status == "completed"
    p.metadata["creative_brief"] = "keep me"
    p.save()

    p = engine.restart(two_step_project.id, "Narration")
    assert p.current_step == "Narration" and p.status == "active"
    assert [h.step_name for h in p.steps_history] == ["Draft"]
    assert p.metadata["creative_brief"] == "keep me"

    p = engine.restart(two_step_project.id)  # everything
    assert p.current_step == "Draft" and p.steps_history == []

    with pytest.raises(ValueError):
        engine.restart(two_step_project.id, "No Such Step")
