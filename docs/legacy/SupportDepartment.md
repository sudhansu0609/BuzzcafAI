# Support Department Guide (`SupportDepartment.md`)

**Department Name**: Support Department  
**Python Module**: `backend/app/departments/support.py`  
**Department Manager**: QAManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Support Department** ensures software quality, automated testing, agent output code reviews, technical documentation maintenance, fine-tuning dataset curation, compliance auditing, and human operator helpdesk guidance.

---

## 2. Department Hierarchy & Agent Roster

```text
Support Department
├── QAManager .......... Quality Assurance Lead [Manager]
├── ReviewAgent ........ Cross-Department Output Reviewer
├── DocumentationAgent . Technical Writer & Docs Specialist
├── TrainingAgent ...... Few-Shot Training Dataset Specialist
├── AuditAgent ......... Compliance & Audit Specialist
└── SupportAgent ....... Operator Helpdesk & Troubleshooting Specialist
```

---

## 3. Agent Specifications & Prompt References

### 3.1 QA Manager (`QAManager.md`)
- **Role**: Head of QA
- **Mission**: Oversees test automation suites, system validation checks, and output quality standards.
- **Specification**: [backend/prompts/agents/QAManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/QAManager.md)

### 3.2 Review Agent (`ReviewAgent.md`)
- **Role**: General Step Reviewer
- **Mission**: Performs cross-department output inspection against quality standards.
- **Specification**: [backend/prompts/agents/ReviewAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ReviewAgent.md)

### 3.3 Documentation Agent (`DocumentationAgent.md`)
- **Role**: Technical Writer
- **Mission**: Generates and maintains system APIs, architecture docs, and agent specifications.
- **Specification**: [backend/prompts/agents/DocumentationAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/DocumentationAgent.md)

### 3.4 Training Agent (`TrainingAgent.md`)
- **Role**: Training Specialist
- **Mission**: Collects high-quality output samples to build fine-tuning datasets and prompt examples.
- **Specification**: [backend/prompts/agents/TrainingAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/TrainingAgent.md)

### 3.5 Audit Agent (`AuditAgent.md`)
- **Role**: Compliance Specialist
- **Mission**: Audits agent execution logs for compliance with company guidelines and security rules.
- **Specification**: [backend/prompts/agents/AuditAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AuditAgent.md)

### 3.6 Support Agent (`SupportAgent.md`)
- **Role**: Operator Support Specialist
- **Mission**: Assists human operators with CLI troubleshooting, error diagnostic explanations, and feature usage.
- **Specification**: [backend/prompts/agents/SupportAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/SupportAgent.md)

---

## 4. Python Integration Example

```python
from app.departments.support import SupportDepartment

dept = SupportDepartment()
qa_mgr = dept.manager_agent
report = qa_mgr.execute("Run QA audit suite on final project assets")
print(report)
```
