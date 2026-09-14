# Architecture

What the code actually does, as of 2026-09-09 (v9). Line counts and paths were
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
| `backend/app/main.py` | 814 | FastAPI app: projects, workflows, topics, brands, agents, settings, diagnostics, static mount |
| `backend/desktop_app.py` | 415 | The window: fast preflight, in-process uvicorn, WebView2, remembered size, `--dev` |
| `backend/app/services/video_intel.py` | 591 | Video/channel intelligence: yt-dlp fetch, metrics, model read with brand guide, cache (v6) |
| `backend/runtime/workflow.py` | 494 | Executes workflow steps, approval gates, step delegation, error classification |
| `backend/integrations/llm.py` | 489 | Provider fallback chain, model tiers, and the simulated-response generator |
| `backend/app/api/buzzbrain_api.py` | 254 | BuzzBrain snapshot store (`knowledge/buzzbrain/`) and `GET /api/buzzbrain/*` |
| `backend/app/services/studio_chat.py` | 271 | Chat as a messages list: persona + roster once, channel guide, ≤6 relevant memories, 8 turns, delegation |
| `backend/core/agent.py` | 250 | `AgentRegistry` — discovers and validates the 105 personas |
| `frontend/src/App.tsx` | 201 | Shell only: sidebar, header, toasts; pages live in `src/pages/*` |
| `backend/core/base_agent.py` | 198 | Loads a persona's prompt, tier and temperature; calls the LLM; records memory |
| `backend/knowledge/knowledge.py` | 186 | Knowledge base read/write |
| `backend/memory/memory.py` | 180 | Per-agent JSON memory on disk |
| `backend/app/api/studio_api.py` | 148 | Control API for Dexter: `/api/studio/state`, `/chat`, `/events` (SSE) |
| `backend/core/config.py` | 136 | Config resolution and validation |
| `backend/executive/project.py` | 106 | Project creation and listing |
| `backend/app/departments/__init__.py` | 90 | The 13 department classes, cached and lazily built (v9) |
| `backend/app/api/departments_api.py` | 85 | `GET /api/departments`, `POST /api/departments/{name}/execute` (v9) |
| `backend/app/api/video_intel_api.py` | 64 | `POST /api/video-intel/analyze`, `GET /recent`, `GET /{id}` (v6) |
| `backend/core/paths.py` | — | **Single source of truth for every filesystem location** |

Also live: `backend/app/api/agents_api.py` (Agents Workbench + group chat),
`backend/app/services/` (`agents_registry`, `local_llm`, `events`),
`backend/app/departments/*.py` (one class per department),
`backend/preflight.py`, `frontend/src/pages/` (`StudioChat`, `Dashboard`,
`Projects`, `TopicVault`, `Analyze`, `Workforce`, `Departments`, `Health`,
`Settings`, `ai/*`), `frontend/src/components/Markdown.tsx` (the in-repo asset
renderer), `frontend/src/state/studio.tsx`,
`frontend/src/services/{http,api}.ts`, `backend/apps/cli/main.py`.

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
WebView2 window (backend/desktop_app.py)  or  our Vite dev server (5173 or next free, pinned; --dev)
  └─ /api/... ──► FastAPI (127.0.0.1:8099, or the next free port; see studio.runtime.json)
                                       └─ app/main.py route
                                            ├─ Project.load(id)          core/models/project.py
                                            ├─ WorkflowEngine            runtime/workflow.py
                                            │    └─ BaseAgent.execute    core/base_agent.py
                                            │         ├─ prompts/agents/<Name>.md
                                            │         ├─ memory/memory.py (prior context)
                                            │         └─ LLMService      integrations/llm.py
                                            │              └─ tier provider → selected → Gemini → OpenAI
                                            │                 → LM Studio → llama.cpp → simulated (labelled)
                                            ├─ app/services/studio_chat.py   (Studio Assistant, /api/studio/chat)
                                            ├─ app/departments/*             (/api/departments, manager or specialist)
                                            ├─ app/services/events.py        (SSE bus → /api/studio/events)
                                            └─ JSON on disk (backend/projects/<id>/)
```

### Events

`app/services/events.py` carries `project_created`, `step_started`,
`step_completed`, `approval_needed`, `step_failed`, `buzzbrain_snapshot`, and
since v9 `agent_invoked` (one agent delegated to another) and `department_task`
(a department ran a task). `GET /api/studio/events` streams all of them.

Nothing uses a database. Every route reads and writes JSON files.

### Paths

`backend/core/paths.py` derives every location from its own file position, so
the checkout can be renamed or moved freely. Environment overrides
(`PROJECTS_PATH`, `KNOWLEDGE_PATH`, `PROMPTS_PATH`, `LOGS_PATH`) are honoured
**only if the target directory already exists** — a stale override silently
creating a phantom tree was a real bug, and this is the guard against its return.

Do not hardcode absolute paths anywhere. Import from `core.paths`.

### Provider fallback

`LLMService.generate_text()` / `generate_chat()` try, in order: the provider the
persona's **tier** maps to (v9), then the selected provider, then Gemini,
OpenAI, LM Studio and llama.cpp. If all fail they return hand-written text from
`dev/fixtures.generate_simulated_response()` and set
`last_response_simulated = True`.

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
through `AgentRegistry` — or, if the name is a department, to that department's
manager (v9) — writes the output asset into the project directory, and pauses at
`requires_approval` for human sign-off. Asset lineage flows through
`input_assets` / `output_asset_type`. `WorkflowRegistry.validate()` accepts any
registered persona or department name and raises on anything else, so a typo
cannot silently drop a workflow.

The research step asks for a JSON dossier (`timeline`, `facts`, `sources`,
`media`, `unanswered_questions`) and writes one file per key. A prose reply goes
verbatim to `research/research.md` and the five section files are **not**
written; `StepExecution.simulated_sections` names what is missing. There is no
placeholder text anywhere in that path.

Step failures are classified `RETRYABLE` / `RECOVERABLE` /
`HUMAN_INTERVENTION_REQUIRED` by exception **type** (`classify_error` in
`runtime/workflow.py`); anything unrecognised is `BLOCKING` on purpose, so a bug
in our own code is not laundered into a workflow state.

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
