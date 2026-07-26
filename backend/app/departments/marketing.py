from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class MarketingDepartment(Department):
    """Marketing Department driving channel growth, cross-platform promotion, and newsletters."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Marketing",
            manager_role="MarketingManager",
            specialist_roles=[
                "CampaignPlanner",
                "TrendAnalyst",
                "SocialMediaManager",
                "NewsletterManager",
                "AudienceResearcher"
            ],
            llm_service=llm_service
        )
