# Research Department Guide (`ResearchDepartment.md`)

**Department Name**: Research Department  
**Python Module**: `backend/app/departments/research.py`  
**Department Manager**: ResearchManager  
**Agent Count**: 8 Specialized Agents  

---

## 1. Overview & Department Mission

The **Research Department** is responsible for deep factual research, web data extraction, academic literature reviews, fact-checking, citation formatting, source credibility scoring, and internal lore archiving.

---

## 2. Department Hierarchy & Agent Roster

```text
Research Department
├── ResearchManager ...... Head of Research Department [Manager]
├── WebResearcher ........ Web Scraping & Open-Source Researcher
├── AcademicResearcher ... Peer-Reviewed Journal & Academic Specialist
├── FactChecker .......... Script Claim Fact Checking Specialist
├── CitationManager ...... Citation & Reference Formatting Specialist
├── SourceValidator ...... Domain Authority & Source Credibility Authenticator
├── TrendResearcher ...... Topic Trend & Search Intent Analyst
└── ArchiveResearcher .... Channel Lore & Legacy Script Specialist
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Research Manager (`ResearchManager.md`)
- **Role**: Head of Research Department
- **Mission**: Coordinates research strategies, delegates research tasks, and synthesizes final briefs.
- **Specification**: [backend/prompts/agents/ResearchManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ResearchManager.md)

### 3.2 Web Researcher (`WebResearcher.md`)
- **Role**: Web & Open Source Researcher
- **Mission**: Scrapes, extracts, and summarizes web sources and real-time news data.
- **Specification**: [backend/prompts/agents/WebResearcher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/WebResearcher.md)

### 3.3 Academic Researcher (`AcademicResearcher.md`)
- **Role**: Academic Literature Researcher
- **Mission**: Queries peer-reviewed journals, scientific databases, and historical archives.
- **Specification**: [backend/prompts/agents/AcademicResearcher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AcademicResearcher.md)

### 3.4 Fact Checker (`FactChecker.md`)
- **Role**: Fact Checking Specialist
- **Mission**: Verifies factual assertions against trusted databases to eliminate hallucinations.
- **Specification**: [backend/prompts/agents/FactChecker.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/FactChecker.md)

### 3.5 Citation Manager (`CitationManager.md`)
- **Role**: Citation Specialist
- **Mission**: Generates properly formatted citations, bibliography files, and source metadata.
- **Specification**: [backend/prompts/agents/CitationManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CitationManager.md)

### 3.6 Source Validator (`SourceValidator.md`)
- **Role**: Credibility Authenticator
- **Mission**: Evaluates domain authority, source reliability, and potential bias.
- **Specification**: [backend/prompts/agents/SourceValidator.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/SourceValidator.md)

### 3.7 Trend Researcher (`TrendResearcher.md`)
- **Role**: Trend Analyst
- **Mission**: Identifies trending search terms, viral angles, and high-engagement topics.
- **Specification**: [backend/prompts/agents/TrendResearcher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/TrendResearcher.md)

### 3.8 Archive Researcher (`ArchiveResearcher.md`)
- **Role**: Channel Lore Specialist
- **Mission**: Queries internal project archives and lore dictionaries for series continuity.
- **Specification**: [backend/prompts/agents/ArchiveResearcher.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ArchiveResearcher.md)

---

## 4. Python Integration Example

```python
from app.departments.research import ResearchDepartment

dept = ResearchDepartment()
res_mgr = dept.manager_agent
dossier = res_mgr.execute("Research Anunnaki tablets and Sumerian cuneiform translations")
print(dossier)
```
