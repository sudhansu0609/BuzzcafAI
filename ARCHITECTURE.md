# Architecture

What the code actually does, as of 2026-09-06 (v5). Line counts and paths were
read from this checkout.

> The v5 purge removed the empty scaffolding that used to make up two thirds of
> this repository: 26 dead trees, 128 stub files and 185 legacy design documents
> (now under `docs/legacy/`, kept for history only). What remains is what runs.
> The Studio is a desktop app (`backend/desktop_app.py` + pywebview) whose
> front door is the Studio Assistant chat, and it is driven by Dexter over the
> control API in `ECOSYSTEM.md`.

---

## The modules that run

| Module | Lines | Responsibility |
|---|---:|---|
| `backend/app/main.py` | 706 | FastAPI app: projects, workflows, topics, brands, settings, diagnostics, static mount |
| `backend/desktop_app.py` | 370 | The window: fast preflight, in-process uvicorn, WebView2, remembered size, `--dev` |
| `backend/app/api/buzzbrain_api.py` | 254 | BuzzBrain snapshot store (`knowledge/buzzbrain/`) and `GET /api/buzzbrain/*` |
| `backend/app/services/studio_chat.py` | 206 | Chat as a messages list: persona + roster once, channel guide, ≤6 relevant memories, 8 turns |
| `backend/app/api/studio_api.py` | 148 | Control API for Dexter: `/api/studio/state`, `/chat`, `/events` (SSE) |
| `frontend/src/App.tsx` | 193 | Shell only: sidebar, header, toasts; pages live in `src/pages/*` |
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
`backend/app/services/` (`agents_registry`, `local_llm`, `events`),
`backend/preflight.py`, `frontend/src/pages/` (`StudioChat`, `Dashboard`,
`Projects`, `TopicVault`, `Workforce`, `Health`, `Settings`, `ai/*`),
`frontend/src/state/studio.tsx`, `frontend/src/services/{http,api}.ts`,
`backend/apps/cli/main.py`.

## What was removed in v5 (so nobody looks for it)

`backend/app/{llm,runtime,knowledge,markdown,production,publishing,repositories,
auth,models,db}`, `backend/apps/api`, `backend/integrations/{ai,notion,youtube}`,
`backend/{knowledge_engine,memory_engine,project_engine,workflow_engine,
monitoring,publishing}`, `backend/markdown_engine`, the root
`agent_runtime/ event_system/ llm_engine/ production/ research/ writing/`, the
voice engine and Jarvis routes, `frontend/src/{layout,store,theme,router.tsx}`
and every stub page. `git show pre-v5:<path>` retrieves any of it.

## Request path

```
WebView2 window (backend/desktop_app.py)  or  Vite dev server (5173, --dev)
  └─ /api/... ──► FastAPI (127.0.0.1:8000)
                                       └─ app/main.py route
                                            ├─ Project.load(id)          core/models/project.py
                                            ├─ WorkflowEngine            runtime/workflow.py
                                            │    └─ BaseAgent.execute    core/base_agent.py
                                            │         ├─ prompts/agents/<Name>.md
                                            │         ├─ memory/memory.py (prior context)
                                            │         └─ LLMService      integrations/llm.py
                                            │              └─ Gemini → OpenAI → LM Studio → simulated (labelled)
                                            ├─ app/services/studio_chat.py   (Studio Assistant, /api/studio/chat)
                                            ├─ app/services/events.py        (SSE bus → /api/studio/events)
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

Tracked in `PLAN.md` / `PROGRESS.md`. Open: synchronous LLM calls with no
streaming in the Studio chat (5.5, optional), and `backend/apps/dashboard/`
(an old static dashboard nothing serves).
