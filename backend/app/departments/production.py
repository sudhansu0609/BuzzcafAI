from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class ProductionDepartment(Department):
    """Production Department transforming scripts into storyboards, visual prompts, and media assets."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Production",
            manager_role="ProductionManager",
            specialist_roles=[
                "StoryboardPlanner",
                "ScenePlanner",
                "PromptEngineer",
                "CharacterPlanner",
                "EnvironmentPlanner",
                "AssetManager",
                "ProductionReviewer"
            ],
            llm_service=llm_service
        )
