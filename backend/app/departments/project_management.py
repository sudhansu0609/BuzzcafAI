from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class ProjectManagementDepartment(Department):
    """Project Management Department converting user goals into executable DAGs."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Project Management",
            manager_role="ProjectManagerAgent",
            specialist_roles=[
                "WorkflowManager",
                "ScheduleManager",
                "ResourcePlanner",
                "RiskManager",
                "DeliveryManager"
            ],
            llm_service=llm_service
        )
