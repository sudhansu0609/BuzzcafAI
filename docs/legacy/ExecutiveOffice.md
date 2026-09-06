# Executive Office Department Guide (`ExecutiveOffice.md`)

**Department Name**: Executive Office  
**Python Module**: `backend/app/departments/executive.py`  
**Department Manager**: CEO Agent  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Executive Office** provides strategic leadership, company-wide governance, operational oversight, financial budgeting, tech stack architecture, and knowledge management for Spilled Coffee AI Studio.

---

## 2. Department Hierarchy & Agent Roster

```text
Executive Office
├── CEO Agent ................. Strategic Orchestrator & Task Allocator [Manager]
├── COO Agent ................. Chief Operating Officer (Production Velocity)
├── CTO Agent ................. Chief Technology Officer (Architecture & LLM Router)
├── CFO Agent ................. Chief Financial Officer (Token Budgeting & API Costs)
├── Chief Knowledge Officer ... CKO (Corporate Memory & Domain Taxonomy)
└── Executive Assistant ....... Executive Assistant (User Notifications & Scheduling)
```

---

## 3. Agent Specifications & Prompt References

### 3.1 CEO Agent (`CEO.md`)
- **Role**: Executive Orchestrator & Strategic Planning
- **Mission**: Orchestrates high-level workflow transitions and step assignments across all departments.
- **Specification**: [backend/prompts/agents/CEO.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CEO.md)

### 3.2 COO Agent (`COO.md`)
- **Role**: Chief Operating Officer
- **Mission**: Monitors production speed, department handoffs, and workflow execution bottlenecks.
- **Specification**: [backend/prompts/agents/COO.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/COO.md)

### 3.3 CTO Agent (`CTO.md`)
- **Role**: Chief Technology Officer
- **Mission**: Governs technical infrastructure standards, model selection policies, and system stability.
- **Specification**: [backend/prompts/agents/CTO.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CTO.md)

### 3.4 CFO Agent (`CFO.md`)
- **Role**: Chief Financial Officer
- **Mission**: Monitors LLM token consumption budgets and API costs per video project.
- **Specification**: [backend/prompts/agents/CFO.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/CFO.md)

### 3.5 Chief Knowledge Officer (`ChiefKnowledgeOfficer.md`)
- **Role**: Chief Knowledge Officer (CKO)
- **Mission**: Ensures knowledge organization standards and vector store taxonomy integrity.
- **Specification**: [backend/prompts/agents/ChiefKnowledgeOfficer.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ChiefKnowledgeOfficer.md)

### 3.6 Executive Assistant (`ExecutiveAssistant.md`)
- **Role**: Executive Assistant
- **Mission**: Synthesizes executive briefings and manages human operator alerts.
- **Specification**: [backend/prompts/agents/ExecutiveAssistant.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ExecutiveAssistant.md)

---

## 4. Python Integration Example

```python
from app.departments.executive import ExecutiveDepartment

dept = ExecutiveDepartment()
ceo = dept.manager_agent
result = ceo.execute("Plan next step for Project Khayal Episode 1")
print(result)
```
