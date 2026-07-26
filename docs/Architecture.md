# Spilled Coffee AI Studio: System Architecture Specification

**Version**: 1.0.0  
**Status**: Production Architecture  
**Corpus / Workspace**: `SpilledCoffeeAI`  

---

## 1. Executive Summary & System Blueprint

**Spilled Coffee AI Studio** is an enterprise-grade autonomous AI workforce and video production pipeline designed for automated content creation across YouTube, Shorts, and digital media channels (including *Beyond3Baje* dark mystery and *Khayal3Baje* mythological folklore channels).

The system operates on a **12-department corporate hierarchy** housing **79 specialized AI agents**, orchestrated by dynamic DAG workflow engines, vector-backed knowledge stores, and multi-model LLM routers.

```mermaid
graph TD
    User["Human Studio Operator"] --> CEO["CEO Agent (Executive Office)"]
    CEO --> PM["Project Management Department"]
    PM --> RD["Research Department"]
    PM --> WD["Writing Department"]
    PM --> PD["Production Department"]
    PM --> PB["Publishing Department"]
    PM --> MK["Marketing Department"]
    PM --> AN["Analytics Department"]
    
    subgraph Core Engines
        LLM["LLM Router Service (Gemini/OpenAI/Ollama)"]
        KM["Knowledge & Memory Engine (ChromaDB Vector Store)"]
        WF["Workflow Execution Engine (DAG Runner)"]
    end
    
    RD --> Core Engines
    WD --> Core Engines
    PD --> Core Engines
    PB --> Core Engines
    MK --> Core Engines
    AN --> Core Engines
```

---

## 2. 12-Department Corporate Hierarchy

Every agent in Spilled Coffee AI Studio belongs to exactly one department and executes tasks mapped by its manager agent:

```text
Spilled Coffee AI Studio
├── 1. Executive Office ........ (CEO, COO, CTO, CFO, CKO, Executive Assistant) [6 Agents]
├── 2. Project Management ...... (Project Manager, Workflow Manager, Scheduler, Resource Planner, Risk Manager, Delivery Manager) [6 Agents]
├── 3. Research Department ..... (Research Manager, Web & Academic Researchers, Fact Checker, Citation/Source Validators, Trend/Archive Researchers) [8 Agents]
├── 4. Writing Department ...... (Story Planner, Outline Writer, Script Writer, Dialogue Writer, Horror & Mythology Specialists, Editor, Reviewer) [8 Agents]
├── 5. Production Department ... (Production Manager, Storyboard/Scene Planners, Prompt Engineer, Character/Environment Planners, Asset Manager, Reviewer) [8 Agents]
├── 6. Publishing Department ... (Publishing Manager, SEO Specialist, Metadata Optimizer, Thumbnail Specialist, Upload/Schedule Managers, Community Publisher) [7 Agents]
├── 7. Marketing Department .... (Marketing Manager, Campaign Planner, Trend Analyst, Social Media Manager, Newsletter Manager, Audience Researcher) [6 Agents]
├── 8. Analytics Department .... (Analytics Manager, Performance Analyst, CTR Analyst, Retention Analyst, Recommendation Agent, Competitor Analyst) [6 Agents]
├── 9. Knowledge Department .... (Knowledge Manager, Memory Manager, Knowledge Curator, Librarian, Taxonomy Manager, Citation Archivist) [6 Agents]
├── 10. Automation Department .. (Automation Manager, Queue Manager, Event Manager, Workflow Executor, Integration/Notification Managers) [6 Agents]
├── 11. Infrastructure Department (Infrastructure Manager, Runtime Monitor, Health Monitor, Configuration/Security/Backup Monitors) [6 Agents]
└── 12. Support Department ..... (QA Manager, Review Agent, Documentation Agent, Training/Audit/Support Agents) [6 Agents]
```

Total Workforce: **79 Specialized Agents**.

---

## 3. Technology Stack & Component Layers

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        React Dashboard Frontend                        │
│                 (Vite, TypeScript, TailwindCSS UI)                     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / REST API
┌───────────────────────────────────▼────────────────────────────────────┐
│                         FastAPI Backend Gateway                        │
│            (Authentication, RBAC, Rate Limiting, Routers)              │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                    Python Department Execution Engine                  │
│       (12 Department Classes, AgentRegistry, AgentFactory)             │
└───────┬───────────────────────────┬────────────────────────────┬───────┘
        │                           │                            │
┌───────▼─────────────┐   ┌─────────▼────────────┐   ┌───────────▼───────┐
│ Dynamic Prompt      │   │ Knowledge Engine     │   │ Multi-Model Router│
│ Loader (Markdown)   │   │ (ChromaDB / Memory)  │   │ (Gemini/OpenAI)   │
└─────────────────────┘   └──────────────────────┘   └───────────────────┘
```

---

## 4. Key Architectural Patterns

1. **29-Part Standard Specification Architecture**:
   All 79 prompt specifications live as structured Markdown documents in `backend/prompts/agents/`, ensuring prompt versioning, strict JSON input/output schemas, and clear operational guardrails.

2. **Lazy Dynamic Agent Discovery**:
   The `AgentRegistry` scans `backend/prompts/agents/` on startup, parsing frontmatter metadata and instantiating Python agent classes on demand via `AgentFactory.get_agent()`.

3. **Isolated Workspace Storage**:
   Project assets, script outputs, image prompts, and video deliverables are strictly isolated within `projects/{project_id}/` workspace subdirectories.

---

## 5. Security & Isolation

- **Role-Based Access Control (RBAC)**: REST API endpoints enforce role permissions (`admin`, `editor`, `viewer`, `system`).
- **File System Boundary**: Agents write files strictly inside project output folders, preventing arbitrary file write vulnerabilities.
- **Secrets Management**: API keys for YouTube, Gemini, and OpenAI are loaded exclusively via environment variables (`.env`).
