import pytest
from core.agent import agent_registry, AgentFactory
from app.departments import (
    ExecutiveDepartment,
    ProjectManagementDepartment,
    ResearchDepartment,
    WritingDepartment,
    ProductionDepartment,
    PublishingDepartment,
    MarketingDepartment,
    AnalyticsDepartment,
    KnowledgeDepartment,
    AutomationDepartment,
    InfrastructureDepartment,
    SupportDepartment
)

DEPARTMENT_CLASSES = [
    ExecutiveDepartment,
    ProjectManagementDepartment,
    ResearchDepartment,
    WritingDepartment,
    ProductionDepartment,
    PublishingDepartment,
    MarketingDepartment,
    AnalyticsDepartment,
    KnowledgeDepartment,
    AutomationDepartment,
    InfrastructureDepartment,
    SupportDepartment
]

CATALOG_AGENTS = [
    # Executive (6)
    "CEO", "COO", "CTO", "CFO", "ChiefKnowledgeOfficer", "ExecutiveAssistant",
    # Project Management (6)
    "ProjectManagerAgent", "WorkflowManager", "ScheduleManager", "ResourcePlanner", "RiskManager", "DeliveryManager",
    # Research (14 - including 6 Channel Strategists & Topic Vault Manager)
    "ResearchManager", "WebResearcher", "AcademicResearcher", "FactChecker", "CitationManager", "SourceValidator", "TrendResearcher", "ArchiveResearcher",
    "SpilledCoffeeStudioStrategist", "AfterDarkStrategist", "Beyond3BajeStrategist", "Life3BajeStrategist", "Khayal3BajeStrategist", "TopicVaultManager",
    # Writing (8)
    "StoryPlanner", "OutlineWriter", "ScriptWriter", "DialogueWriter", "HorrorSpecialist", "MythologySpecialist", "Editor", "Reviewer",
    # Production (8)
    "ProductionManager", "StoryboardPlanner", "ScenePlanner", "PromptEngineer", "CharacterPlanner", "EnvironmentPlanner", "AssetManager", "ProductionReviewer",
    # Publishing (7)
    "PublishingManager", "SEOSpecialist", "MetadataOptimizer", "ThumbnailSpecialist", "UploadManager", "PublishingScheduleManager", "CommunityPublisher",
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
    assert len(CATALOG_AGENTS) == 85

def test_agent_registry_discovery():
    agent_registry.discover_agents()
    registered_names = [a.name for a in agent_registry.list()]
    assert len(registered_names) >= 85

@pytest.mark.parametrize("agent_name", CATALOG_AGENTS)
def test_instantiate_agent(agent_name):
    agent_instance = AgentFactory.get_agent(agent_name)
    assert agent_instance is not None
    assert agent_instance.agent_name is not None
    assert agent_instance.system_prompt is not None
    assert len(agent_instance.system_prompt) > 0

def test_all_12_departments_initialization():
    for dept_cls in DEPARTMENT_CLASSES:
        dept_obj = dept_cls()
        assert dept_obj.name is not None
        assert len(dept_obj.list_agents()) > 0
        manager = dept_obj.manager_agent
        assert manager is not None
