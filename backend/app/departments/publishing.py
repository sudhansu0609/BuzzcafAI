from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class PublishingDepartment(Department):
    """Publishing Department preparing and distributing video content to YouTube and media platforms."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Publishing",
            manager_role="PublishingManager",
            specialist_roles=[
                "SEOManagerAgent",
                "MetadataOptimizer",
                "ThumbnailSpecialist",
                "UploadManager",
                "ScheduleManager",
                "CommunityPublisher",
                "TitleGenerator",
                "DescriptionWriter",
                "TagGenerator",
                "PublishingChecklist",
                "AnalyticsHandoff"
            ],
            llm_service=llm_service
        )
