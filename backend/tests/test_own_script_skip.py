"""Own script / recorded video: the script steps are passed by."""
from core.models.workflow import WorkflowDefinition, WorkflowStep
from executive.project import project_manager
from runtime.workflow import OWN_SCRIPT_SKIPPED, RECORDED_SKIPPED, WorkflowEngine


def _wf():
    kinds = ["research", "script", "script_final", "visual_plan", "seo_package"]
    steps = [WorkflowStep(name=f"S{i}", agent_role="ResearchAgent", description="d", input_assets=[],
                          output_asset_type=k) for i, k in enumerate(kinds)]
    return WorkflowDefinition(id="t_own", name="t_own", description="t", steps=steps)


def _project(name):
    wf = _wf()
    engine = WorkflowEngine()
    engine.workflows["t_own"] = wf
    p = project_manager.create_project(name=name, brand="Raat3Baje", workflow_name="t_own")
    return engine, wf, p


def test_skip_steps_moves_current_step():
    engine, wf, p = _project("Skip one")
    p = engine.skip_steps(p, wf, {"research", "script"}, "test")
    assert p.current_step == "S2"
    assert all(h.logs[0].startswith("Skipped") for h in p.steps_history)


def test_use_own_script_sets_assets():
    engine, wf, p = _project("Skip two")
    p = engine.use_own_script(p.id, "Hello doston. " * 20)
    assert p.assets["script"] == p.assets["script_final"] == "script/draft.md"
    assert p.metadata["script_source"] == "creator"
    assert p.current_step == "S3"


def test_recorded_leaves_only_planless_steps():
    engine, wf, p = _project("Skip three")
    p = engine.skip_steps(p, wf, RECORDED_SKIPPED, "the video is already recorded")
    assert p.current_step == "S4"
    assert OWN_SCRIPT_SKIPPED < RECORDED_SKIPPED
