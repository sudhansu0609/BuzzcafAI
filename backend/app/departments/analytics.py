from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class AnalyticsDepartment(Department):
    """Analytics Department analyzing performance metrics, CTR, retention, and algorithm recommendations."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Analytics",
            manager_role="AnalyticsManager",
            specialist_roles=[
                "PerformanceAnalyst",
                "CTRAnalyst",
                "RetentionAnalyst",
                "RecommendationAgent",
                "CompetitorAnalyst"
            ],
            llm_service=llm_service
        )
