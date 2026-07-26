# Knowledge Department Guide (`KnowledgeDepartment.md`)

**Department Name**: Knowledge Department  
**Python Module**: `backend/app/departments/knowledge.py`  
**Department Manager**: KnowledgeManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Knowledge Department** governs corporate memory, vector store indexing (ChromaDB), research curation, file taxonomy, metadata standards, and historical citation archiving.

---

## 2. Department Hierarchy & Agent Roster

```text
Knowledge Department
├── KnowledgeManager ... Knowledge Operations Lead [Manager]
├── MemoryManager ...... Agent Context & Long-Term Memory Specialist
├── KnowledgeCurator ... Information Curator & Article Summarizer
├── Librarian .......... Workspace Directory & File Taxonomist
├── TaxonomyManager .... Metadata Tagging & Categorization Specialist
└── CitationArchivist .. Citation & Fair-Use Legal Archivist
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Knowledge Manager (`KnowledgeManager.md`)
- **Role**: Head of Knowledge
- **Mission**: Oversees corporate memory, vector database indexing, and documentation standards.
- **Specification**: [backend/prompts/agents/KnowledgeManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/KnowledgeManager.md)

### 3.2 Memory Manager (`MemoryManager.md`)
- **Role**: Memory Specialist
- **Mission**: Manages short-term session context and long-term agent memory persistence.
- **Specification**: [backend/prompts/agents/MemoryManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/MemoryManager.md)

### 3.3 Knowledge Curator (`KnowledgeCurator.md`)
- **Role**: CKO Summarizer
- **Mission**: Distills raw research dossiers into clean, reusable channel knowledge articles.
- **Specification**: [backend/prompts/agents/KnowledgeCurator.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/KnowledgeCurator.md)

### 3.4 Librarian (`Librarian.md`)
- **Role**: File Taxonomist
- **Mission**: Maintains workspace folder structures, file naming conventions, and asset indexing.
- **Specification**: [backend/prompts/agents/Librarian.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/Librarian.md)

### 3.5 Taxonomy Manager (`TaxonomyManager.md`)
- **Role**: Metadata Specialist
- **Mission**: Defines standardized metadata tags, categories, and lore schemas across projects.
- **Specification**: [backend/prompts/agents/TaxonomyManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/TaxonomyManager.md)

### 3.6 Citation Archivist (`CitationArchivist.md`)
- **Role**: Citation Keeper
- **Mission**: Archives all citations, source permissions, and fair-use documentation permanently.
- **Specification**: [backend/prompts/agents/CitationArchivist.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CitationArchivist.md)

---

## 4. Python Integration Example

```python
from app.departments.knowledge import KnowledgeDepartment

dept = KnowledgeDepartment()
km = dept.manager_agent
result = km.execute("Index research dossier into ChromaDB vector store")
print(result)
```
