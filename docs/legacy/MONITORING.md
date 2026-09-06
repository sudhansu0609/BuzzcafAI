# Telemetry, Logging & System Monitoring (`MONITORING.md`)

**Version**: 1.0.0  
**Module**: `backend.monitoring` / `backend.logs`  

---

## 1. Overview

Spilled Coffee AI Studio implements structured JSON logging, execution telemetry, error tracking, and performance metric collection managed by the Infrastructure and Support Departments.

---

## 2. Standard Structured Log Format

All system logs follow the standard JSON telemetry schema:

```json
{
  "timestamp": "2026-07-22T22:49:00Z",
  "level": "INFO",
  "logger": "spilled_coffee_ai.core.base_agent",
  "agent_name": "ScriptWriter",
  "project_id": "proj_khayal_01",
  "workflow_step": "step_3_script_write",
  "message": "Agent 'ScriptWriter' completed execution task successfully in 1420ms.",
  "execution_time_ms": 1420,
  "tokens_consumed": 1850
}
```

---

## 3. Log Levels & Alert Rules

| Log Level | Trigger Condition | Handler Action |
|---|---|---|
| **`DEBUG`** | Verbose step transitions and prompt template substitution details. | Written to file log (`backend/logs/debug.log`). |
| **`INFO`** | Normal step execution start/completion, API endpoint calls. | Standard output and project execution log. |
| **`WARNING`** | Missing optional dependency context, LLM provider retry fallback. | Logged with warning highlight; retry triggered. |
| **`ERROR`** | Agent execution failure, schema validation error, disk write failure. | Alerts `NotificationManager`; escalates to Department Manager. |
| **`CRITICAL`** | System-wide outage, DB connection loss, rate limit blackout. | Triggers high-priority operator alert via Discord/Telegram. |

---

## 4. Telemetry Metric Dashboards

Key performance indicators tracked in real time:
- **Agent Latency**: Average milliseconds per agent execution step.
- **LLM Token Consumption**: Daily and per-project token count breakdown.
- **Queue Depth**: Active jobs waiting in background task queues.
- **Publishing Velocity**: Videos successfully uploaded vs scheduled.