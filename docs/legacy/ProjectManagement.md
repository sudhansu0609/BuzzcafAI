# Project Management Department Guide (`ProjectManagement.md`)

**Department Name**: Project Management  
**Python Module**: `backend/app/departments/project_management.py`  
**Department Manager**: ProjectManagerAgent  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Project Management Department** converts user goals and channel strategies into executable project pipelines, DAG workflow definitions, production schedules, and delivery release packages.

---

## 2. Department Hierarchy & Agent Roster

```text
Project Management Department
├── ProjectManagerAgent .. Project Manager & Milestone Tracker [Manager]
├── WorkflowManager ...... DAG Workflow Definition & Sequencing Specialist
├── ScheduleManager ...... Production & Upload Scheduler
├── ResourcePlanner ...... LLM & Worker Agent Load Balancer
├── RiskManager .......... Risk & Compliance Specialist
└── DeliveryManager ...... Final Delivery & Release Handoff Manager
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Project Manager (`ProjectManagerAgent.md`)
- **Role**: Project Manager
- **Mission**: Creates, tracks, and manages video project lifecycles and milestone schedules.
- **Specification**: [backend/prompts/agents/ProjectManagerAgent.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ProjectManagerAgent.md)

### 3.2 Workflow Manager (`WorkflowManager.md`)
- **Role**: Workflow Manager
- **Mission**: Defines, validates, and sequences multi-agent workflow DAGs for active projects.
- **Specification**: [backend/prompts/agents/WorkflowManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/WorkflowManager.md)

### 3.3 Scheduler (`ScheduleManager.md`)
- **Role**: Production Scheduler
- **Mission**: Schedules pipeline execution times, job queue placements, and publishing windows.
- **Specification**: [backend/prompts/agents/ScheduleManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ScheduleManager.md)

### 3.4 Resource Planner (`ResourcePlanner.md`)
- **Role**: Resource Allocator
- **Mission**: Balances worker agent load and API rate limits during parallel batch processing.
- **Specification**: [backend/prompts/agents/ResourcePlanner.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ResourcePlanner.md)

### 3.5 Risk Manager (`RiskManager.md`)
- **Role**: Risk & Compliance Specialist
- **Mission**: Identifies copyright risks, production bottlenecks, or policy violations prior to publishing.
- **Specification**: [backend/prompts/agents/RiskManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/RiskManager.md)

### 3.6 Delivery Manager (`DeliveryManager.md`)
- **Role**: Delivery & Release Manager
- **Mission**: Verifies final deliverable packages prior to distribution handoffs.
- **Specification**: [backend/prompts/agents/DeliveryManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/DeliveryManager.md)

---

## 4. Python Integration Example

```python
from app.departments.project_management import ProjectManagementDepartment

dept = ProjectManagementDepartment()
pm = dept.manager_agent
plan = pm.execute("Initialize new project: Mesopotamian Myths Ep 1")
print(plan)
```
