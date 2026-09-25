"""
Video duration control (v12): the target-length directive text, and that the
workflow engine injects it into a script step's prompt and logs the result.
"""

import pytest

from core.models.project import Project
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.workflow import workflow_registry
from executive.project import project_manager
from runtime.workflow import WorkflowEngine, WORDS_PER_MINUTE, _duration_directive


class _Proj:
    """Minimal stand-in with the one attribute _duration_directive reads."""

    def __init__(self, minutes):
        self.metadata = {} if minutes is None else {"target_duration_minutes": minutes}


def test_directive_is_empty_without_a_target():
    assert _duration_directive(_Proj(None), "script") == ""
    assert _duration_directive(_Proj(0), "script") == ""
    assert _duration_directive(_Proj("nonsense"), "script") == ""


def test_directive_gives_a_word_budget_for_scripts():
    text = _duration_directive(_Proj(5), "script")
    assert "Target runtime" in text
    assert "5 minutes" in text
    assert f"{5 * WORDS_PER_MINUTE:,}" in text  # ~700 words


def test_directive_asks_for_minute_budgets_on_outlines():
    text = _duration_directive(_Proj(8), "outline")
    assert "8 minutes" in text and "minute budget" in text


class FakeAgent:
    def __init__(self):
        self.seen = None

    def execute(self, instruction, require_json=False):
        self.seen = instruction
        return "This is a short script sentence. " * 20  # 120 words


def test_engine_injects_target_runtime_into_the_script_prompt(monkeypatch):
    engine = WorkflowEngine()
    wf = WorkflowDefinition(
        id="dur_test_wf",
        name="Duration Test",
        description="one script step",
        steps=[
            WorkflowStep(
                name="Draft",
                agent_role="ScriptWriter",
                description="Writes the draft",
                requires_approval=False,
                input_assets=[],
                output_asset_type="script",
            )
        ],
    )
    workflow_registry.register(wf)
    project = None
    try:
        project = project_manager.create_project("Duration Probe", "Beyond3Baje", "dur_test_wf")
        project.current_step = "Draft"
        project.metadata["target_duration_minutes"] = 5
        project.save()

        fake = FakeAgent()
        monkeypatch.setattr(engine, "_resolve_agent", lambda role: fake)

        engine.execute_next(project.id)

        assert fake.seen is not None
        assert "Target runtime" in fake.seen
        assert f"{5 * WORDS_PER_MINUTE:,}" in fake.seen  # the 700-word budget

        updated = Project.load(project.id)
        logs = updated.steps_history[-1].logs
        assert any("Target runtime: 5 min" in line for line in logs)
        assert any("Script length" in line for line in logs)
    finally:
        workflow_registry.unregister("dur_test_wf")
        if project is not None:
            try:
                project_manager.delete_project(project.id)
            except Exception:
                pass
