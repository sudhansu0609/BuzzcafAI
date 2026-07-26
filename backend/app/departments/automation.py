from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class AutomationDepartment(Department):
    """Automation Department managing job queues, event pipelines, and integration webhooks."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Automation",
            manager_role="AutomationManager",
            specialist_roles=[
                "QueueManager",
                "EventManager",
                "WorkflowExecutor",
                "IntegrationManager",
                "NotificationManager"
            ],
            llm_service=llm_service
        )
