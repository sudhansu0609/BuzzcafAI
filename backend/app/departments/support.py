from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class SupportDepartment(Department):
    """Support Department managing QA validation, step reviews, documentation, and user help."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Support",
            manager_role="QAManager",
            specialist_roles=[
                "ReviewAgent",
                "DocumentationAgent",
                "TrainingAgent",
                "AuditAgent",
                "SupportAgent"
            ],
            llm_service=llm_service
        )
