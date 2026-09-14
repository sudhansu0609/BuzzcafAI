from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class CreativeDepartment(Department):
    """Creative Department owning visual direction and the look of a channel."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Creative",
            manager_role="CreativeDirectorAgent",
            specialist_roles=[],
            llm_service=llm_service
        )
