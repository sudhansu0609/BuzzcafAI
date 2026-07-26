from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class ExecutiveDepartment(Department):
    """Executive Department governing strategic planning and governance."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Executive Office",
            manager_role="CEO",
            specialist_roles=[
                "COO",
                "CTO",
                "CFO",
                "ChiefKnowledgeOfficer",
                "ExecutiveAssistant"
            ],
            llm_service=llm_service
        )
