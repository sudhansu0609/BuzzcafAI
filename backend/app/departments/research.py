from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class ResearchDepartment(Department):
    """Research Department for information gathering, verification, and academic dossiers."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Research",
            manager_role="ResearchManager",
            specialist_roles=[
                "WebResearcher",
                "AcademicResearcher",
                "FactChecker",
                "CitationManager",
                "SourceValidator",
                "ArchiveResearcher",
                "ResearchAgent",
                "DocumentaryResearcher",
                "HorrorResearcher",
                "TopicVaultManager",
                "Beyond3BajeStrategist",
                "AfterDarkStrategist",
                "SpilledCoffeeStudioStrategist",
                "Life3BajeStrategist",
                "Khayal3BajeStrategist"
            ],
            llm_service=llm_service
        )
