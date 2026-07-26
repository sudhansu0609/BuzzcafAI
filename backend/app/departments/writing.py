from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class WritingDepartment(Department):
    """Writing Department creating high-quality written scripts and narratives."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Writing",
            manager_role="Editor",
            specialist_roles=[
                "StoryPlanner",
                "OutlineWriter",
                "ScriptWriter",
                "DialogueWriter",
                "HorrorSpecialist",
                "MythologySpecialist",
                "Reviewer"
            ],
            llm_service=llm_service
        )
