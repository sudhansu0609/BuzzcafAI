from typing import Optional
from app.departments.base import Department
from integrations.llm import LLMService

class KnowledgeDepartment(Department):
    """Knowledge Department managing corporate memory, vector store indexing, and taxonomy."""

    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__(
            name="Knowledge",
            manager_role="KnowledgeManager",
            specialist_roles=[
                "MemoryManager",
                "KnowledgeCurator",
                "Librarian",
                "TaxonomyManager",
                "CitationArchivist"
            ],
            llm_service=llm_service
        )
