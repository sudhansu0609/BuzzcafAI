# Automation Department Guide (`AutomationDepartment.md`)

**Department Name**: Automation Department  
**Python Module**: `backend/app/departments/automation.py`  
**Department Manager**: AutomationManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Automation Department** manages background job queues (Redis/Celery), event dispatchers, API integration webhooks, workflow execution transitions, and user alert notifications.

---

## 2. Department Hierarchy & Agent Roster

```text
Automation Department
├── AutomationManager ... Automation Operations Lead [Manager]
├── QueueManager ........ Task Queue Operator (Redis/Celery)
├── EventManager ........ Pub/Sub Event Dispatcher
├── WorkflowExecutor .... DAG Execution Runner & Agent Handoff Operator
├── IntegrationManager .. External API Webhook Operator
└── NotificationManager . Alert & Multi-Channel Notification Operator
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Automation Manager (`AutomationManager.md`)
- **Role**: Head of Automation
- **Mission**: Manages automated job schedules, event pipelines, and integration webhooks.
- **Specification**: [backend/prompts/agents/AutomationManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/AutomationManager.md)

### 3.2 Queue Manager (`QueueManager.md`)
- **Role**: Task Queue Operator
- **Mission**: Monitors and balances background job queues across worker threads.
- **Specification**: [backend/prompts/agents/QueueManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/QueueManager.md)

### 3.3 Event Manager (`EventManager.md`)
- **Role**: Event Dispatcher
- **Mission**: Handles internal pub/sub event triggers, system webhooks, and status notifications.
- **Specification**: [backend/prompts/agents/EventManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/EventManager.md)

### 3.4 Workflow Executor (`WorkflowExecutor.md`)
- **Role**: Workflow Executor
- **Mission**: Runs step transitions in active project DAGs and manages agent handoffs.
- **Specification**: [backend/prompts/agents/WorkflowExecutor.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/WorkflowExecutor.md)

### 3.5 Integration Manager (`IntegrationManager.md`)
- **Role**: Integration Operator
- **Mission**: Manages connections to YouTube, Notion, Google Drive, and AI API endpoints.
- **Specification**: [backend/prompts/agents/IntegrationManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/IntegrationManager.md)

### 3.6 Notification Manager (`NotificationManager.md`)
- **Role**: Alerts Dispatcher
- **Mission**: Sends alerts via Discord, Telegram, Email, or Web Dashboard when workflows complete or fail.
- **Specification**: [backend/prompts/agents/NotificationManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/NotificationManager.md)

---

## 4. Python Integration Example

```python
from app.departments.automation import AutomationDepartment

dept = AutomationDepartment()
auto_mgr = dept.manager_agent
result = auto_mgr.execute("Schedule background job for video render pipeline")
print(result)
```
