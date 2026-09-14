import os
import shutil
import pytest
import json
import requests
from types import SimpleNamespace
from core.models.project import Project, StepExecution
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.agent import AgentFactory
from core.errors import ApprovalRequired, AssetMissing
from runtime.workflow import WorkflowEngine, classify_error
from integrations.llm import LLMService
from core.paths import ASSETS_DIR, PROJECTS_DIR


TEST_PROJECTS_DIR = PROJECTS_DIR

@pytest.fixture(autouse=True)
def cleanup_test_projects():
    # Setup test configuration or backup directories
    yield
    # We can clean up test project dirs if we want, or leave them.

def test_project_model():
    p = Project(
        id="test_proj_123",
        name="Test Project",
        brand="Beyond3Baje",
        workflow_name="youtube_production",
        current_step="Research"
    )
    p.save()
    
    # Assert JSON file was written
    project_file = os.path.join(TEST_PROJECTS_DIR, "test_proj_123", "project.json")
    assert os.path.exists(project_file)
    
    # Assert reload works
    loaded = Project.load("test_proj_123")
    assert loaded.name == "Test Project"
    assert loaded.brand == "Beyond3Baje"
    assert loaded.current_step == "Research"
    
    # Clean up test project directory
    shutil.rmtree(os.path.join(TEST_PROJECTS_DIR, "test_proj_123"))

def test_agent_factory():
    agent = AgentFactory.get_agent("ResearchAgent")
    assert agent.agent_name == "ResearchAgent"
    
    # CEO Agent type
    ceo = AgentFactory.get_agent("CEO")
    assert ceo.agent_name == "CEO"

def test_workflow_engine_load():
    engine = WorkflowEngine()
    assert "beyond3baje_documentary" in engine.workflows
    wf = engine.get_workflow("beyond3baje_documentary")
    assert wf is not None
    assert len(wf.steps) > 0
    assert wf.steps[0].name == "Research"
    assert wf.steps[0].requires_approval is True

def test_workflow_execution_flow():
    engine = WorkflowEngine()
    
    # 1. Create a dummy test project
    p = Project(
        id="test_exec_flow",
        name="Engine Test Flow",
        brand="Beyond3Baje",
        workflow_name="beyond3baje_documentary",
        current_step="Research"
    )
    p.save()
    
    # 2. Run first step (Research) - should pause for approval
    p = engine.execute_next("test_exec_flow")
    
    assert p.current_step == "Research"
    assert len(p.steps_history) == 1
    assert p.steps_history[0].step_name == "Research"
    assert p.steps_history[0].status == "paused_for_approval"
    assert "research" in p.assets
    
    # 3. Simulate Human Approval (execute again without feedback)
    p = engine.execute_next("test_exec_flow")
    assert p.current_step == "Scripting"
    assert p.steps_history[0].status == "completed"
    
    # Clean up
    shutil.rmtree(os.path.join(TEST_PROJECTS_DIR, "test_exec_flow"))


def _run_research_step(monkeypatch, project_id, reply):
    """Run just the Research step of a throwaway documentary project."""
    monkeypatch.setattr(
        LLMService,
        "generate_text",
        lambda self, system_prompt, user_prompt, require_json=False, **kwargs: reply,
    )
    p = Project(
        id=project_id,
        name="Research honesty probe",
        brand="Beyond3Baje",
        workflow_name="beyond3baje_documentary",
        current_step="Research",
    )
    p.save()
    return WorkflowEngine().execute_next(project_id), os.path.join(TEST_PROJECTS_DIR, project_id, "research")


def test_research_step_writes_a_file_per_json_section(monkeypatch):
    """v9 D1: a JSON dossier becomes the five section files, no filler."""
    reply = json.dumps({
        "timeline": ["1923 - the mill burns down"],
        "facts": ["Seventeen workers were on shift"],
        "sources": ["District gazetteer 1924 - archive.org/x"],
        "media": ["Fire brigade photograph, state archive"],
        "unanswered_questions": ["Who reported the fire?"],
    })
    project_id = "test_research_json"
    try:
        p, research_dir = _run_research_step(monkeypatch, project_id, reply)
        written = sorted(f for f in os.listdir(research_dir) if f != "research.md")
        assert written == ["facts.md", "media.md", "sources.md", "timeline.md", "unanswered_questions.md"]
        with open(os.path.join(research_dir, "timeline.md"), encoding="utf-8") as f:
            assert "1923 - the mill burns down" in f.read()
        assert p.assets["research"] == "research/research.md"
        assert p.steps_history[-1].simulated_sections == []
    finally:
        shutil.rmtree(os.path.join(TEST_PROJECTS_DIR, project_id), ignore_errors=True)


def test_research_step_labels_a_prose_reply_instead_of_faking_sections(monkeypatch):
    """v9 D1: prose keeps its own file and the five sections stay unwritten."""
    project_id = "test_research_prose"
    try:
        p, research_dir = _run_research_step(
            monkeypatch, project_id, "The mill fire is documented but the cause is disputed."
        )
        assert os.listdir(research_dir) == ["research.md"]
        with open(os.path.join(research_dir, "research.md"), encoding="utf-8") as f:
            assert "cause is disputed" in f.read()
        assert p.steps_history[-1].simulated_sections == [
            "timeline", "facts", "sources", "media", "unanswered_questions",
        ]
    finally:
        shutil.rmtree(os.path.join(TEST_PROJECTS_DIR, project_id), ignore_errors=True)


def test_workflow_step_delegation_lands_in_the_asset(monkeypatch):
    """v9 B3: a step's agent can hand work on, and you can read the result."""
    def fake_text(self, system_prompt, user_prompt, require_json=False, **kwargs):
        self.last_response_simulated = False
        if "You have been invoked by" in user_prompt:
            return "Checked: the 1923 dates hold."
        if require_json:
            return json.dumps({"facts": ["The mill burned in 1923"]})
        return "SCRIPT DRAFT.\n[INVOKE_AGENT: FactChecker]Verify the 1923 dates.[/INVOKE_AGENT]"

    monkeypatch.setattr(LLMService, "generate_text", fake_text)
    project_id = "test_step_delegation"
    try:
        Project(
            id=project_id,
            name="Delegation probe",
            brand="Beyond3Baje",
            workflow_name="beyond3baje_documentary",
            current_step="Research",
        ).save()
        engine = WorkflowEngine()
        engine.execute_next(project_id)   # Research runs and pauses
        engine.execute_next(project_id)   # approved, advances to Scripting
        p = engine.execute_next(project_id)

        with open(os.path.join(TEST_PROJECTS_DIR, project_id, p.assets["script"]), encoding="utf-8") as f:
            content = f.read()
        assert "## Delegated: FactChecker" in content
        assert "Checked: the 1923 dates hold." in content
        assert "[INVOKE_AGENT" not in content

        step = next(h for h in p.steps_history if h.step_name == "Scripting")
        assert step.delegations == [
            {"agent": "FactChecker", "task_preview": "Verify the 1923 dates.", "simulated": False, "skipped": False}
        ]
    finally:
        shutil.rmtree(os.path.join(TEST_PROJECTS_DIR, project_id), ignore_errors=True)
        from memory.memory import memory_system
        memory_system.clear(scope="agent", owner="FactChecker")


def test_asset_service():
    from knowledge.assets import AssetService
    # Temporarily rename actual catalog if it exists for isolation
    actual_catalog_path = os.path.join(ASSETS_DIR, "catalog.json")
    backup_path = os.path.join(ASSETS_DIR, "catalog_backup.json")
    
    if os.path.exists(actual_catalog_path):
        os.rename(actual_catalog_path, backup_path)
        
    try:
        service = AssetService()
        # Register a test asset
        asset = service.register_asset(
            title="Newton Portrait",
            asset_type="ai_image",
            tags=["newton", "portrait", "scientist", "alchemy"],
            file_path="assets/ai_image/newton_portrait.png"
        )
        
        assert asset["title"] == "Newton Portrait"
        assert "portrait" in asset["tags"]
        
        # Test Query
        results = service.query_assets(tag="newton")
        assert len(results) == 1
        assert results[0]["title"] == "Newton Portrait"
        
        # Test Similarity Deduplication check (tag overlap)
        similar = service.find_similar_asset(
            asset_type="ai_image",
            tags=["newton", "portrait", "scientist"],
            threshold=0.5
        )
        assert similar is not None
        assert similar["id"] == asset["id"]

        
    finally:
        # Clean up and restore backup
        if os.path.exists(actual_catalog_path):
            os.remove(actual_catalog_path)
        if os.path.exists(backup_path):
            os.rename(backup_path, actual_catalog_path)

def test_config_priority():
    from integrations.llm import load_config
    # Backup and set mock env
    old_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "mock_env_gemini_key"
    
    try:
        config = load_config()
        assert config["gemini_api_key"] == "mock_env_gemini_key"
    finally:
        if old_key:
            os.environ["GEMINI_API_KEY"] = old_key
        else:
            del os.environ["GEMINI_API_KEY"]

def test_naming_compliance():
    import datetime
    from knowledge.assets import AssetService
    
    # Verify Project Naming: YYYY-MM-DD_Channel_ShortTitle
    date_str = datetime.date.today().isoformat()
    brand = "Beyond 3 Baje"
    name = "The lost bhangarh fort history"
    brand_clean = brand.replace(" ", "")
    words = [w.capitalize() for w in name.split() if w]
    title_clean = "".join([c for c in "".join(words) if c.isalnum()])
    project_id = f"{date_str}_{brand_clean}_{title_clean}"
    
    assert project_id.startswith(date_str)
    assert "Beyond3Baje" in project_id
    assert "TheLostBhangarhFortHistory" in project_id
    
    # Verify Asset Naming: asset_type_subject_version.ext
    actual_catalog_path = os.path.join(ASSETS_DIR, "catalog.json")
    backup_path = os.path.join(ASSETS_DIR, "catalog_backup.json")
    if os.path.exists(actual_catalog_path):
        os.rename(actual_catalog_path, backup_path)
        
    try:
        service = AssetService()
        asset = service.register_asset(
            title="Isaac Newton",
            asset_type="ai_image",
            tags=["newton"],
            file_path="assets/ai_image/original_name.png"
        )
        assert asset["id"] == "ai_image_isaac_newton_v1"
        assert asset["file_path"] == "assets/ai_image/ai_image_isaac_newton_v1.png"
    finally:
        if os.path.exists(actual_catalog_path):
            os.remove(actual_catalog_path)
        if os.path.exists(backup_path):
            os.rename(backup_path, actual_catalog_path)

def test_error_handling_compliance():
    # Setup test project
    p = Project(
        id="test_error_flow",
        name="Error Test",
        brand="Beyond3Baje",
        workflow_name="beyond3baje_documentary",
        current_step="Research"
    )
    p.save()
    
    engine = WorkflowEngine()

    # A real transport failure, not a string that happens to say "timeout" --
    # classification is by exception type.
    class BrokenLLM:
        def generate_text(self, *args, **kwargs):
            raise requests.ConnectionError("upstream unreachable")

    engine.llm_service = BrokenLLM()

    # Execute next step - should throw and fail
    with pytest.raises(Exception):
        engine.execute_next("test_error_flow")

    # Reload project and check error categorization logs
    loaded = Project.load("test_error_flow")
    assert len(loaded.steps_history) == 1
    assert loaded.steps_history[0].status == "failed"
    assert any("[RETRYABLE]" in log for log in loaded.steps_history[0].logs)

    # Clean up test directories
    shutil.rmtree(loaded.get_project_dir())


def test_error_classification_by_type():
    """Our own bugs must not be laundered into workflow states."""
    # A NameError mentioning "connection" used to be classified RETRYABLE
    # purely because of the word in its message.
    assert classify_error(NameError("name 'connection' is not defined")) == "BLOCKING"
    assert classify_error(requests.Timeout()) == "RETRYABLE"
    assert classify_error(requests.ConnectionError()) == "RETRYABLE"
    assert classify_error(ApprovalRequired("needs sign-off")) == "HUMAN_INTERVENTION_REQUIRED"
    assert classify_error(AssetMissing("research")) == "RECOVERABLE"
    assert classify_error(FileNotFoundError("script.md")) == "RECOVERABLE"

    rate_limited = requests.HTTPError("429 Too Many Requests")
    rate_limited.response = SimpleNamespace(status_code=429)
    assert classify_error(rate_limited) == "RETRYABLE"

    bad_request = requests.HTTPError("400 Bad Request")
    bad_request.response = SimpleNamespace(status_code=400)
    assert classify_error(bad_request) == "BLOCKING"


