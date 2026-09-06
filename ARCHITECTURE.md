# Architecture

What the code actually does, as of 2026-08-12. Line counts and paths were read
from this checkout.

> **Read this first:** the repository contains ~766 tracked files, but roughly
> 162 of 243 Python files and 100 of 108 frontend `.ts`/`.tsx` files are empty
> scaffolding (`class Foo: pass`) that nothing imports. Several subsystems exist
> in three or four parallel copies, only one of which is live. The tables below
> mark which copy is real. Grep results outside these modules are almost
> certainly dead code.

---

## The modules that run

| Module | Lines | Responsibility |
|---|---:|---|
| `frontend/src/App.tsx` | 3581 | The entire UI: dashboard, projects, topic vault, chat, voice dictation, settings, health |
| `backend/app/main.py` | 1195 | FastAPI app — every HTTP route, CORS, in-memory log buffer |
| `backend/integrations/llm.py` | 491 | Provider fallback chain and the simulated-response generator |
| `backend/runtime/workflow.py` | 338 | Executes workflow steps, approval gates, error classification |
| `backend/core/agent.py` | 233 | `AgentRegistry` — discovers and validates the 115 personas |
| `backend/knowledge/knowledge.py` | 186 | Knowledge base read/write |
| `backend/memory/memory.py` | 180 | Per-agent JSON memory on disk |
| `backend/core/base_agent.py` | 148 | Loads a persona's prompt, calls the LLM, records memory |
| `backend/core/config.py` | 136 | Config resolution and validation |
| `backend/executive/project.py` | 106 | Project creation and listing |
| `backend/core/paths.py` | — | **Single source of truth for every filesystem location** |

Also live: `backend/app/api/agents_api.py` (Agents Workbench + group chat),
`backend/app/services/` (`agents_registry`, `local_llm`, `voice_engine`),
`frontend/src/pages/ai/` (`AgentCreatorStudio`, `AgentsGroupChat`),
`frontend/src/services/http.ts`, `backend/apps/cli/main.py`.

## Which copy is real

| Concern | Live | Dead duplicates |
|---|---|---|
| LLM routing | `backend/integrations/llm.py` | `backend/app/llm/`, `backend/integrations/ai/`, `llm_engine/` |
| Agent runtime | `backend/runtime/`, `backend/core/agent.py` | `agent_runtime/`, `backend/app/runtime/` |
| API app | `backend/app/main.py` | `backend/apps/api/main.py` |
| Dashboard | `frontend/` | `backend/apps/dashboard/`, `backend/app/static/` (stale prebuilt bundle) |
| Auth | `app/api/auth.py` (mounted, a stub) | `app/auth/`, `apps/api/auth/`, `admin/` |
| Knowledge/memory | `backend/knowledge/`, `backend/memory/` | `backend/knowledge_engine/`, `backend/app/knowledge/`, `backend/memory_engine/` |

`frontend/src/router.tsx` is never imported — `main.tsx` renders `App` directly,
so everything under `frontend/src/pages/` except `pages/ai/` is unreachable.

---

## Request path

```
Browser (5173)
  └─ /api/... ──► Vite dev proxy ──► FastAPI (127.0.0.1:8000)
                                       └─ app/main.py route
                                            ├─ Project.load(id)          core/models/project.py
                                            ├─ WorkflowEngine            runtime/workflow.py
                                            │    └─ BaseAgent.execute    core/base_agent.py
                                            │         ├─ prompts/agents/<Name>.md
                                            │         ├─ memory/memory.py (prior context)
                                            │         └─ LLMService      integrations/llm.py
                                            │              └─ Gemini → OpenAI → LM Studio → simulated
                                            └─ JSON on disk (backend/projects/<id>/)
```

Nothing uses a database. Every route reads and writes JSON files.

### Paths

`backend/core/paths.py` derives every location from its own file position, so
the checkout can be renamed or moved freely. Environment overrides
(`PROJECTS_PATH`, `KNOWLEDGE_PATH`, `PROMPTS_PATH`, `LOGS_PATH`) are honoured
**only if the target directory already exists** — a stale override silently
creating a phantom tree was a real bug, and this is the guard against its return.

Do not hardcode absolute paths anywhere. Import from `core.paths`.

### Provider fallback

`LLMService.generate_text()` tries the selected provider, then Gemini, OpenAI,
and LM Studio in turn. If all fail it returns hand-written text from
`_generate_simulated_response()` and sets `last_response_simulated = True`.

**Every caller must propagate that flag.** API responses carry
`"status": "simulated"` / `"simulated": true`, and the UI renders an amber
banner. An error path must never report `"status": "success"`.

### Workflows

`backend/prompts/workflows/*.json` define ordered steps:

```json
{
  "name": "Research",
  "agent_role": "ResearchAgent",
  "requires_approval": true,
  "input_assets": [],
  "output_asset_type": "research"
}
```

`WorkflowEngine.execute_next()` runs one step per call, resolves `agent_role`
through `AgentRegistry`, writes the output asset into the project directory, and
pauses at `requires_approval` for human sign-off. Asset lineage flows through
`input_assets` / `output_asset_type`.

Known weakness: step failures are classified `RETRYABLE` / `RECOVERABLE` /
`HUMAN_INTERVENTION_REQUIRED` by string-matching the exception message
(`runtime/workflow.py`). A genuine bug in our own code gets laundered into a
workflow state. Prefer exception types when touching this.

### Agents

See [AGENTS.md](AGENTS.md).

### Logging

`InMemoryLogHandler` (`app/main.py`) keeps a capped 500-line `deque` per project
so a long-running server cannot grow without bound. Records are attributed via a
`project_id` attribute; unattributed lines are assigned only when exactly one
execution is in flight, and dropped otherwise rather than copied into every
project's log.

---

## Conventions

- **Paths** — always from `core.paths`, never absolute literals.
- **Frontend HTTP** — always relative `/api/...` through `services/http.ts`.
  Never hardcode a hostname; the backend port changes.
- **Pydantic v2** — `model_dump()`, not the deprecated `.dict()`.
- **Secrets** — never returned by an endpoint, never written to `localStorage`.
- **Fallbacks** — must be labelled at every layer they cross.

## Known debt

Tracked in `IMPROVEMENTS.md` with file:line references. The largest open items:
the stub/duplicate file tree above, `App.tsx` at 3581 lines in a single
component, synchronous blocking LLM calls with no streaming, and `docs/`
(185 files) describing behavior that the stub modules never implemented.
