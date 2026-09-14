import pytest
from core.agent import agent_registry, AgentFactory
from app.departments import DEPARTMENT_CLASSES

CATALOG_AGENTS = [
    # Executive (6)
    "CEO", "COO", "CTO", "CFO", "ChiefKnowledgeOfficer", "ExecutiveAssistant",
    # Project Management (5)
    "ProjectManagerAgent", "WorkflowManager", "ResourcePlanner", "RiskManager", "DeliveryManager",
    # Research (13 - including 5 Channel Strategists & Topic Vault Manager)
    "ResearchManager", "WebResearcher", "AcademicResearcher", "FactChecker", "CitationManager", "SourceValidator", "ArchiveResearcher",
    "SpilledCoffeeStudioStrategist", "AfterDarkStrategist", "Beyond3BajeStrategist", "Life3BajeStrategist", "Khayal3BajeStrategist", "TopicVaultManager",
    # Writing (8)
    "StoryPlanner", "OutlineWriter", "ScriptWriter", "DialogueWriter", "HorrorSpecialist", "MythologySpecialist", "EditorAgent", "Reviewer",
    # Production (8)
    "ProductionManager", "StoryboardPlanner", "ScenePlanner", "PromptEngineer", "CharacterPlanner", "EnvironmentPlanner", "AssetManager", "ProductionReviewer",
    # Publishing (7)
    "PublishingManager", "SEOManagerAgent", "MetadataOptimizer", "ThumbnailSpecialist", "UploadManager", "ScheduleManager", "CommunityPublisher",
    # Marketing (6)
    "MarketingManager", "CampaignPlanner", "TrendAnalyst", "SocialMediaManager", "NewsletterManager", "AudienceResearcher",
    # Analytics (6)
    "AnalyticsManager", "PerformanceAnalyst", "CTRAnalyst", "RetentionAnalyst", "RecommendationAgent", "CompetitorAnalyst",
    # Knowledge (6)
    "KnowledgeManager", "MemoryManager", "KnowledgeCurator", "Librarian", "TaxonomyManager", "CitationArchivist",
    # Automation (6)
    "AutomationManager", "QueueManager", "EventManager", "WorkflowExecutor", "IntegrationManager", "NotificationManager",
    # Infrastructure (6)
    "InfrastructureManager", "RuntimeMonitor", "HealthMonitor", "ConfigurationManager", "SecurityMonitor", "BackupManager",
    # Support (6)
    "QAManager", "ReviewAgent", "DocumentationAgent", "TrainingAgent", "AuditAgent", "SupportAgent"
]

def test_total_catalog_agent_count():
    assert len(CATALOG_AGENTS) == 83

def test_agent_registry_discovery():
    agent_registry.discover_agents()
    registered_names = [a.name for a in agent_registry.list()]
    assert len(registered_names) >= 83

def test_catalog_agents_are_all_registered():
    """Every catalogued role must be a real persona file, not a GenericAgent
    falling back to a one-line prompt (roadmap v9, A4)."""
    agent_registry.discover_agents()
    missing = [n for n in CATALOG_AGENTS if n.lower() not in agent_registry.agents]
    assert missing == []

@pytest.mark.parametrize("agent_name", CATALOG_AGENTS)
def test_instantiate_agent(agent_name):
    agent_instance = AgentFactory.get_agent(agent_name)
    assert agent_instance is not None
    assert agent_instance.agent_name is not None
    assert agent_instance.system_prompt is not None
    assert len(agent_instance.system_prompt) > 0

def test_all_departments_initialize_their_manager():
    for dept_cls in DEPARTMENT_CLASSES:
        dept_obj = dept_cls()
        assert dept_obj.name is not None
        assert len(dept_obj.list_agents()) > 0
        # Agents are built on first use since v9 (E1), so ask for one.
        manager = dept_obj.get_agent(dept_obj.manager_role)
        assert manager is not None
        assert dept_obj.manager_agent is not None
