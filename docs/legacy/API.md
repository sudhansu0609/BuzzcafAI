# Spilled Coffee AI Studio: REST API Specification (`API.md`)

**Version**: 1.0.0  
**Protocol**: REST / JSON over HTTP  
**Default Base URL**: `http://localhost:8000/api/v1`  

---

## 1. Authentication & Security Headers

All protected API endpoints require a valid JWT bearer token in the `Authorization` header:

```http
Authorization: Bearer <jwt_access_token>
Content-Type: application/json
```

---

## 2. API Endpoint Matrix

### 2.1 Agent & Department Endpoints (`/api/v1/agents`, `/api/v1/departments`)

| Method | Endpoint | Description | Auth / Role |
|---|---|---|---|
| `GET` | `/api/v1/agents` | List all 79 registered agents and metadata | Required (`viewer`) |
| `GET` | `/api/v1/agents/{role}` | Get specific agent definition & prompt spec | Required (`viewer`) |
| `POST` | `/api/v1/agents/{role}/execute` | Trigger direct execution of an agent task | Required (`editor`) |
| `GET` | `/api/v1/departments` | List all 12 corporate departments & managers | Required (`viewer`) |
| `GET` | `/api/v1/departments/{dept}/agents` | List agents belonging to a specific department | Required (`viewer`) |

### 2.2 Project Management Endpoints (`/api/v1/projects`)

| Method | Endpoint | Description | Auth / Role |
|---|---|---|---|
| `GET` | `/api/v1/projects` | List all active video projects | Required (`viewer`) |
| `POST` | `/api/v1/projects` | Create a new video project pipeline | Required (`editor`) |
| `GET` | `/api/v1/projects/{id}` | Fetch project status, assets, and logs | Required (`viewer`) |
| `DELETE` | `/api/v1/projects/{id}` | Delete a project workspace | Required (`admin`) |

### 2.3 Workflow Execution Endpoints (`/api/v1/workflows`)

| Method | Endpoint | Description | Auth / Role |
|---|---|---|---|
| `GET` | `/api/v1/workflows` | List available DAG workflow templates | Required (`viewer`) |
| `POST` | `/api/v1/workflows/{id}/execute` | Launch a DAG workflow execution | Required (`editor`) |
| `GET` | `/api/v1/workflows/executions/{exec_id}` | Check active workflow step status & DAG progress | Required (`viewer`) |

### 2.4 Knowledge & Memory Endpoints (`/api/v1/knowledge`)

| Method | Endpoint | Description | Auth / Role |
|---|---|---|---|
| `POST` | `/api/v1/knowledge/query` | Perform vector similarity search on knowledge base | Required (`viewer`) |
| `POST` | `/api/v1/knowledge/index` | Ingest and index new research document | Required (`editor`) |

---

## 3. Sample Execution Payload & Response

### Request: `POST /api/v1/agents/ResearchManager/execute`

```json
{
  "project_id": "proj_khayal_ep01",
  "task": {
    "research_topic": "The Anunnaki Tablets and Mesopotamian Cosmology",
    "depth_level": "deep_dive"
  },
  "require_json": true
}
```

### Response: `200 OK`

```json
{
  "status": "success",
  "agent": "ResearchManager",
  "execution_time_ms": 1420,
  "results": {
    "master_research_brief": {
      "topic": "The Anunnaki Tablets and Mesopotamian Cosmology",
      "summary": "Synthesized research analysis of Enuma Elish and Sumerian cuneiform tablets...",
      "key_findings": [
        "Primary deities: Anu, Enlil, and Enki.",
        "Earliest recorded flood myths in Eridu Genesis."
      ],
      "sources_count": 12
    }
  }
}
```
