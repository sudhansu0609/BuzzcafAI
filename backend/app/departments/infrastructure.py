from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class InfrastructureDepartment(Department):
    """Infrastructure Department maintaining runtime monitors, security, backups, and configs."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Infrastructure",
            manager_role="InfrastructureManager",
            specialist_roles=[
                "RuntimeMonitor",
                "HealthMonitor",
                "ConfigurationManager",
                "SecurityMonitor",
                "BackupManager"
            ],
            llm_service=llm_service
        )
