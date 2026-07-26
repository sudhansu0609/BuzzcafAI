import os
import shutil
import tempfile
import pytest
from core.config import ConfigurationManager, config_manager
from core.logger import LoggingManager
from core.markdown import MarkdownLoader, MarkdownDocument
from executive.project import ProjectManager
from core.workflow import WorkflowRegistry
from core.diagnostics import Diagnostics
from core.models.workflow import WorkflowDefinition, WorkflowStep


def test_config_manager_validation():
    # Verify singleton configuration manager
    cm1 = ConfigurationManager()
    cm2 = ConfigurationManager()
    assert cm1 is cm2
    
    # Assert default values loaded
    assert cm1.get("APP_NAME") == "Spilled Coffee AI Studio"
    assert cm1.get("LOG_LEVEL") in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

def test_markdown_loader_and_parser():
    loader = MarkdownLoader()
    
    # Create temporary markdown file
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
        f.write("---\ntitle: \"Test Spec\"\nversion: \"2.1.0\"\n---\n# Overview\nThis is the overview section.\n## Setup\nDetailed step details here.")
        temp_path = f.name
        
    try:
        # Load and parse
        doc = loader.load(temp_path)
        assert doc.metadata["id"] == os.path.splitext(os.path.basename(temp_path))[0]
        assert doc.frontmatter["title"] == "Test Spec"
        assert doc.frontmatter["version"] == "2.1.0"
        
        # Verify heading section splits
        assert "overview" in doc.sections
        assert "setup" in doc.sections
        assert "This is the overview section." in doc.sections["overview"]
        
        # Verify caching
        doc2 = loader.load(temp_path)
        assert doc is doc2 # same reference
        
    finally:
        os.remove(temp_path)
        loader.invalidate_cache(temp_path)

def test_project_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Override PROJECTS_PATH for isolation
        old_path = config_manager.get("PROJECTS_PATH")
        config_manager.settings["PROJECTS_PATH"] = tmp_dir
        
        try:
            pm = ProjectManager(projects_dir=tmp_dir)
            
            # Test Naming: YYYY-MM-DD_Channel_ShortTitle
            project_id = pm.generate_project_id("Beyond 3 Baje", "Ghost of Bhangarh")
            assert "Beyond3Baje" in project_id
            assert "GhostOfBhangarh" in project_id
            
            # Test creation of template folders
            project = pm.create_project("Ghost of Bhangarh", "Beyond 3 Baje", "beyond3baje_documentary")
            p_dir = os.path.join(tmp_dir, project.id)
            assert os.path.exists(p_dir)
            
            # Check required folder templates
            assert os.path.exists(os.path.join(p_dir, "research"))
            assert os.path.exists(os.path.join(p_dir, "seo"))
            assert os.path.exists(os.path.join(p_dir, "analytics"))
            
            # Assert validation
            assert pm.validate_project(project.id) is True
        finally:
            config_manager.settings["PROJECTS_PATH"] = old_path


def test_workflow_registry_validation():
    registry = WorkflowRegistry()
    
    # 1. Valid test definition
    valid_wf = WorkflowDefinition(
        id="test_registry_wf",
        name="Test Registry",
        description="Demo workflow details",
        steps=[
            WorkflowStep(
                name="Research",
                agent_role="ResearchAgent",
                description="Gathers notes",
                requires_approval=True,
                input_assets=[],
                output_asset_type="research_package"
            ),
            WorkflowStep(
                name="Scripting",
                agent_role="WriterAgent",
                description="Writes draft",
                requires_approval=False,
                input_assets=["research_package"],
                output_asset_type="script_package"
            )
        ]
    )
    # Registry should validate and load it without raising error
    registry.register(valid_wf)
    assert registry.get("test_registry_wf") is not None
    
    # 2. Check circular dependency verification
    invalid_wf = WorkflowDefinition(
        id="test_circular_wf",
        name="Circular Workflow",
        description="Will fail validation",
        steps=[
            WorkflowStep(
                name="Research",
                agent_role="ResearchAgent",
                description="Needs script first",
                requires_approval=False,
                input_assets=["script_package"], # input depends on step running later
                output_asset_type="research_package"
            ),
            WorkflowStep(
                name="Scripting",
                agent_role="WriterAgent",
                description="Writes script",
                requires_approval=False,
                input_assets=["research_package"],
                output_asset_type="script_package"
            )
        ]
    )
    with pytest.raises(ValueError) as exc:
        registry.register(invalid_wf)
    assert "circular or backward dependency" in str(exc.value)
    
    # Clean up registry
    registry.unregister("test_registry_wf")

def test_diagnostics_report():
    report = Diagnostics.get_report()
    assert "startup_time_seconds" in report
    assert report["app_name"] == "Spilled Coffee AI Studio"
    assert report["registered_agents_count"] >= 79





def test_agent_registry():
    from core.agent import agent_registry, AgentDefinition
    
    # Check CEO is discovered
    ceo = agent_registry.get("CEO")
    assert ceo is not None
    assert ceo.department == "Executive Office"
    assert "write_assets" in ceo.permissions
    
    # Try registering invalid agent
    with pytest.raises(ValueError):
        invalid_agent = AgentDefinition(name="", department="None", role="")
        agent_registry.register(invalid_agent)

def test_knowledge_manager():
    from knowledge.knowledge import knowledge_manager
    
    # Save test document
    knowledge_manager.save_document(
        category="research",
        doc_id="mock_gravity",
        title="Gravity Research Notes",
        content="Newton published his findings in 1687. Gravity pulls objects together.",
        tags=["newton", "gravity", "physics"]
    )
    
    # Search check
    results = knowledge_manager.search(query="Newton")
    assert len(results) > 0
    assert results[0]["id"] == "mock_gravity"
    
    # Search missing query
    results_missing = knowledge_manager.search(query="Einstein")
    assert len(results_missing) == 0
    
    # Clean up test file
    import os
    filepath = os.path.join(r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\knowledge", "research", "mock_gravity.md")
    if os.path.exists(filepath):
        os.remove(filepath)
    knowledge_manager.rebuild_index()

def test_prompt_manager_inheritance():
    from core.prompt import PromptTemplate, PromptManager
    
    # 1. Test variable substitution
    raw_prompt = "# Role\nYou are a {role_name}.\n# Objective\nDo {task}."
    template = PromptTemplate(raw_prompt, {"id": "test", "version": "1"})
    
    # Test valid replacement
    rendered = template.render(role_name="Writer", task="scriptwriting")
    assert "You are a Writer." in rendered
    assert "Do scriptwriting." in rendered
    
    # Test missing placeholder throws ValueError
    with pytest.raises(ValueError) as exc:
        template.render(role_name="Writer")
    assert "Missing required rendering variables" in str(exc.value)

def test_health_checker():
    from core.doctor import HealthChecker
    report = HealthChecker.run_checks()
    assert report["status"] in ["healthy", "unhealthy"]
    assert len(report["logs"]) > 0
    assert "config" in report["details"]

def test_memory_system():
    from memory.memory import memory_system
    # Session memory test
    item = memory_system.save(scope="session", owner="CEO", tags=["test"], content="Hello Memory")
    assert item is not None
    assert item.content == "Hello Memory"
    
    retrieved = memory_system.retrieve(scope="session", tags=["test"])
    assert len(retrieved) > 0
    assert retrieved[0].content == "Hello Memory"
    
    # Clean up
    memory_system.clear(scope="session")
    assert len(memory_system.retrieve(scope="session")) == 0

def test_tool_registry():
    from integrations.tools import tool_registry
    assert tool_registry.check_permissions("CEO", "YouTubePublish") is True
    assert tool_registry.check_permissions("WriterAgent", "YouTubePublish") is False
    
    reports = tool_registry.run_health_checks()
    assert "OpenAIGPT" in reports



