# Infrastructure Department Guide (`InfrastructureDepartment.md`)

**Department Name**: Infrastructure Department  
**Python Module**: `backend/app/departments/infrastructure.py`  
**Department Manager**: InfrastructureManager  
**Agent Count**: 6 Specialized Agents  

---

## 1. Overview & Department Mission

The **Infrastructure Department** monitors system health, CPU/GPU runtime performance, environment settings, security access logs, container health, and automated data backups.

---

## 2. Department Hierarchy & Agent Roster

```text
Infrastructure Department
├── InfrastructureManager ... Infrastructure Operations Lead [Manager]
├── RuntimeMonitor .......... Real-Time Engine & CPU/GPU Telemetry Monitor
├── HealthMonitor ........... Health Probe & Heartbeat Operator
├── ConfigurationManager .... System Settings & Env Config Operator
├── SecurityMonitor ......... Access Control & Audit Guard
└── BackupManager ........... Data Backup & Disaster Recovery Specialist
```

---

## 3. Agent Specifications & Prompt References

### 3.1 Infrastructure Manager (`InfrastructureManager.md`)
- **Role**: Head of Infrastructure
- **Mission**: Oversees system uptime, container health, environment configs, and runtime stability.
- **Specification**: [backend/prompts/agents/InfrastructureManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/InfrastructureManager.md)

### 3.2 Runtime Monitor (`RuntimeMonitor.md`)
- **Role**: Telemetry Monitor
- **Mission**: Monitors memory consumption, active process threads, and LLM runtime speed.
- **Specification**: [backend/prompts/agents/RuntimeMonitor.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/RuntimeMonitor.md)

### 3.3 Health Monitor (`HealthMonitor.md`)
- **Role**: Health Operator
- **Mission**: Runs periodic health checks on database connections, API gateways, and disk space.
- **Specification**: [backend/prompts/agents/HealthMonitor.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/HealthMonitor.md)

### 3.4 Configuration Manager (`ConfigurationManager.md`)
- **Role**: Config Operator
- **Mission**: Manages environment variables, feature flags, and model provider settings.
- **Specification**: [backend/prompts/agents/ConfigurationManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/ConfigurationManager.md)

### 3.5 Security Monitor (`SecurityMonitor.md`)
- **Role**: Security Guard
- **Mission**: Audits authentication, RBAC permissions, and file isolation safety.
- **Specification**: [backend/prompts/agents/SecurityMonitor.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/SecurityMonitor.md)

### 3.6 Backup Manager (`BackupManager.md`)
- **Role**: Backup Specialist
- **Mission**: Executes automated project data backups, database snapshots, and emergency restores.
- **Specification**: [backend/prompts/agents/BackupManager.md](file:///b:/youtubeProjects/Buzzcaf%20Media/SpilledCoffeeAI/backend/prompts/agents/BackupManager.md)

---

## 4. Python Integration Example

```python
from app.departments.infrastructure import InfrastructureDepartment

dept = InfrastructureDepartment()
infra_mgr = dept.manager_agent
report = infra_mgr.execute("Run system health probe and disk space check")
print(report)
```
