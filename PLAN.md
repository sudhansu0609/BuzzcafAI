# Buzzcaf Studio — Plan v5 (Studio side)

**Status date:** 2026-09-06 · **Supersedes:** `IMPROVEMENTS.md` (repair pass, complete) ·
**Progress log:** `PROGRESS.md` · **Cross-project contract:** `ECOSYSTEM.md`

## Why v5

The owner's assistant is **Dexter**; this repo is the YouTube studio Dexter
controls. It must become a **desktop app** (one window, no console), open on a
real Studio Assistant chat, stop fabricating data, drop voice, and expose a
control API that Dexter's tools call. Dexter-side items live in `dexter/PLAN.md`.

Acceptance ids (I1–I13) are defined in `ECOSYSTEM.md`'s companion plan; the
Studio owns **I2, I11, I12** and shares **I5, I9**.

## Phase 0 — Freeze and tracking

| # | Item | Effort | Acceptance |
|---|---|---|---|
| 0.1 | Commit the dirty tree in logical groups, `git tag pre-v5` | S | `git status` clean, tag exists |
| 0.3 | This file + `PROGRESS.md`; `IMPROVEMENTS.md` marked superseded | S | files exist |
| 0.4 | `ECOSYSTEM.md` identical to `dexter/ECOSYSTEM.md` | S | `diff` empty |
| 0.5 | `backend/tests/conftest.py` sandboxes KNOWLEDGE/PROJECTS/LOGS paths | S | suite green; real `knowledge/*_memory.json` hashes unchanged |

## Phase 2 — Desktop app with chat as the front door

| # | Item | Effort | Acceptance |
|---|---|---|---|
| 2.1 | `vite build` outputs to `backend/app/static` (`vite.config.ts` `build.outDir`) | S | `npm run build` refreshes `static/index.html`; uvicorn serves it at `/` |
| 2.2 | `backend/desktop_app.py` (pywebview + in-process uvicorn on 8000, `--dev` flag), `backend/preflight.py`, `Buzzcaf Studio.vbs`, `start_buzzcafai.bat` as dev variant, `pywebview` in requirements, file log `logs/studio.log` | M | **I2**: double-click → only the window; no `cmd.exe`; closing ends `pythonw.exe` |
| 2.3 | Remove voice: `voice_intent.py`, `voice_engine.py`, `/api/jarvis/voice`, `/api/voice/config`, clone routes, dictation tab, jarvis handlers, voice modals, mic buttons | S | `grep -rni "jarvis\|voice_intent\|webkitSpeech\|voice_engine" backend/app frontend/src` empty; tests + build green |
| 2.4 | `services/studio_chat.py` `run_chat()`: structured messages (persona + roster once + channel guide, last 8 turns), `BaseAgent.execute_messages`, `LLMService.generate_chat`, query-aware `memory.retrieve(query=)` ≤ 6 items once, Hinglish only for content steps, HTTP 502 on failure, full replies stored | M | `tests/test_studio_chat.py` green |
| 2.5 | `App.tsx`: land on Studio Assistant tab; all `fetch` → `apiFetch`; `alert/confirm` → Toast; no fabricated projects/topics; mock tabs removed; real health; header titles fixed; Group Chat in sidebar with error toasts | M | **I11**; `grep -n "alert(\|confirm(\| fetch(" App.tsx` empty |

## Phase 3 — Control API for Dexter

| # | Item | Effort | Acceptance |
|---|---|---|---|
| 3.1 | `api/studio_api.py` + `services/events.py`: `/health` adds `app:"buzzcaf"`; `GET /api/studio/state`; `POST /api/studio/chat`; `GET /api/studio/events` (SSE); `POST /api/projects/{id}/approve`; events published from create/execute | M | `tests/test_studio_api.py` green; `curl -N /api/studio/events` shows a frame on project create; **I5** with Dexter 3.2 |

## Phase 5 — BuzzBrain store and cleanup

| # | Item | Effort | Acceptance |
|---|---|---|---|
| 5.1 | `api/buzzbrain_api.py`: `POST /api/buzzbrain/snapshot` → `knowledge/buzzbrain/snapshots.jsonl` + `index.json`, `mine` via settings `owner_channel_ids`; `GET /latest`, `/channels`, `/videos/{id}` | M | `tests/test_buzzbrain_api.py`; **I9** with BuzzBrain + Dexter |
| 5.4 | Split `App.tsx` into `src/pages/*` + `src/state/studio.tsx`; delete stub trees per `ARCHITECTURE.md`; `docs/` → `docs/legacy/` | L | green after each slice; `App.tsx` < 400 lines |
| 5.5 | Optional: streaming `POST /api/studio/chat/stream` | M | only if chat still feels slow |

## v6 — Video intelligence (owner's ask, 2026-09-06)

| # | Item | Design | Acceptance |
|---|---|---|---|
| S1 | Analyze a video or channel link | `app/services/video_intel.py`: yt-dlp (no API key) for metadata, captions, the "most replayed" heatmap and the channel's last 30 uploads; metrics (views/day, like rate, comments per 1k, views ÷ subs, outlier multiple vs the channel median, hook transcript, replay peaks with what was said, title signals); one model call with the target channel's brand guide → why it works + blueprint (titles, hook script, outline, thumbnail, tags, length, CTA, differentiator, do-not-copy); `POST /api/video-intel/analyze`, `GET /recent`, `/{id}`; cached; `simulated` when no model answered; Analyze tab with "Save as topic" and "Start a project" | **J3** paste a link → breakdown in under a minute; a channel link → outliers + what to borrow; nothing invented when no model is up |

## v9 — Staff activation (owner's ask, 2026-09-09)

**Why.** 115 personas load and register, but only 8 ever run: `core/workflow.py:73`
hard-codes six `valid_agents` (the comment above it claims it reads the registry),
the chat UI hard-codes five strategists (`frontend/src/lib/channels.ts`), and the
12 `app/departments` classes — a verified 79-agent ownership map — have no
caller outside a test. Delegation exists only as `[INVOKE_AGENT: X]` tags the
model may emit, run silently by `studio_chat.process_agent_invocations`.
Frontmatter `inputs/outputs/dependencies/permissions` do nothing at runtime.
Numbering: Dexter took v7/v8, so the Studio's next shared number is v9.

Order of work: **A → C → D → B → E → F → G.** Each phase ends green
(`pytest tests -q` in `backend/`, `tsc` + `vite build` in `frontend/`) before
the next starts. Nothing is marked done in `PROGRESS.md` without evidence.

### Phase A — Unlock the roster

| # | Item | Design | Acceptance |
|---|---|---|---|
| A1 | Validator reads the registry | `core/workflow.py` `WorkflowRegistry.validate`: replace the literal list with `{k for k in agent_registry.agents}` (import the singleton from `core.agent`), compare `step.agent_role.lower().strip()`. Unknown names still raise so a typo cannot silently drop a workflow. | `tests/test_router.py`+new test: a workflow whose step names `ScriptWriter` registers; one naming `NoSuchAgent` raises `ValueError`; the 6 shipped workflows still load |
| A2 | `/api/agents` carries the frontmatter | `app/main.py` `list_agents`: build from `agent_registry.agents.values()` → `{name, department, role, inputs, outputs, dependencies, version, file}`; `?department=` filter; `status` becomes `"registered"` (the old `"Active & Idle"` was invented). `pages/Workforce.tsx`: group by department, show role, filter by name or department, count per group. | `GET /api/agents` returns 115 rows with non-empty `department` and `role`; Personas tab shows 19 groups |
| A3 | Any persona in chat | `pages/StudioChat.tsx`: persona picker fed by `/api/agents` grouped by department, default = the channel strategist from `lib/channels.ts`, choice remembered per channel in `localStorage`; sends `agent_name` to `POST /api/topics/agent_chat` (backend unchanged — it already accepts any name, `main.py:600`). Reply header names the persona that answered. | pick `FactChecker` on Beyond3Baje, ask a question, reply arrives in that persona's voice; `knowledge/agent_factchecker_memory.json` appears |
| A4 | Prune the duplicate generation | Merge into one canonical file each: `CTRAnalyst`/`CTRAnalyzer`, `RetentionAnalyst`/`RetentionAnalyzer`, `RecommendationAgent`/`RecommendationEngine`, `TrendAnalyst`/`TrendAnalyzer`/`TrendResearcher`, `Editor`/`EditorAgent` (keep `EditorAgent`, workflows use it), `ThumbnailSpecialist`/`ThumbnailPlanner`, `SEOSpecialist`/`SEOManagerAgent` (keep `SEOManagerAgent`), `ScheduleManager`/`PublishingScheduleManager`/`SchedulerAgent`. Fold the `"X Department"` namespaces into `"X"` so departments match the 12 classes + `Creative`. Update `EXPECTED_PERSONAS` in `preflight.py`, `dependencies:` lines that pointed at a removed name, and the "19 departments" text in `core/base_agent.py:50`. Keep the better prose of each pair. | `python -c "from core.agent import AgentRegistry; print(len(AgentRegistry().agents))"` matches `EXPECTED_PERSONAS`; no `dependencies` warning in the log; `pytest` green |

### Phase C — Read the work

| # | Item | Design | Acceptance |
|---|---|---|---|
| C1 | Asset viewer | `pages/Projects.tsx`: list `project.assets` (name → file) for the selected project; click opens a right-hand panel that fetches `GET /api/projects/{id}/asset/{name}` (exists, `main.py`) and renders Markdown with a small in-repo renderer (headings, lists, paragraphs, fenced code — no library). | open a project, click `script`, read the script in the window |
| C2 | Workflow step preview | `pages/Dashboard.tsx`: when a workflow is chosen, render its `steps[]` (name, `agent_role`, approval flag) from `/api/workflows` before "Start project". `pages/Projects.tsx`: step timeline for the current project — done / current / pending from `project.history` + the workflow definition, approval steps marked. | the new-project form shows the 13 documentary steps; Projects shows the current step highlighted |
| C3 | Real approve | Approve button calls `POST /api/projects/{id}/approve` (409-aware) instead of `execute` with an empty body; "Revise" keeps `execute` with `feedback`. | `approval_needed` → click Approve → `step_started` on `/api/studio/events` |

### Phase D — Nothing lies, continued

| # | Item | Design | Acceptance |
|---|---|---|---|
| D1 | Research output is real or labelled | `runtime/workflow.py:202-309`: the research step asks `ResearchAgent` for JSON with keys `timeline, facts, sources, media, unanswered_questions` (`require_json=True`, schema in the instruction); each key → its file. Non-JSON reply → raw text to `research.md`, the five files are **not** written, `history_step` records `simulated_sections: [...]`. Delete the literal "Information gathered from research." filler. | `grep -rn "Information gathered from research" backend` empty; `tests/test_workflow_engine`: JSON reply → 5 files; prose reply → 1 file + label |
| D2 | Discover uses a model | `POST /api/topics/discover`: run `TopicVaultManager` (via `AgentFactory` + `LLMService`, `require_json`) with the channel guide + saved topics as context; `curated_seed` stays only as the labelled fallback when `last_response_simulated`. Response `source: "model" \| "curated_seed"`; `TopicVault.tsx` shows a "seed list, no model" badge on the fallback. | with a model up, discover returns fresh topics with `source: "model"`; without, the badge shows |
| D3 | One source of truth | Delete `prompts/standards/AgentRegistry.json` (nothing loads it); `AGENTS.md` says `permissions` is unenforced — keep that sentence until F1 lands. | `grep -rn AgentRegistry.json backend docs *.md` → only history |

### Phase B — Delegation you can see

| # | Item | Design | Acceptance |
|---|---|---|---|
| B1 | Structured invocations | `services/studio_chat.py` `process_agent_invocations` returns `[{agent, task, output, simulated}]`; cap 3 per reply, depth 1 (an invoked agent's output is not scanned again); `run_chat` response gains `invocations`; each publishes `agent_invoked {agent, task_preview, simulated}` on `services/events.py`; memory rows tagged `delegated`. Pass the caller's `LLMService` instead of constructing a new one. | `tests/test_studio_chat.py`: a reply with two tags → two records, event bus sees two frames; a reply with four → three run, one logged as skipped |
| B2 | Invocation cards | `StudioChat.tsx`: under a reply, one card per invocation ("Delegated to FactChecker", task, expandable output, simulated badge). | visible in the window; Dexter receives `agent_invoked` |
| B3 | Delegation inside workflow steps | `runtime/workflow.py`: after `agent.execute`, run the same invocation pass on the output; append each result under `## Delegated: <Agent>` in the step's asset; record in `history_step`. The step's own `requires_approval` gates the assembled output — no new gate. | a documentary run where the strategist delegates shows the section in the asset and in the history |

### Phase E — Departments

| # | Item | Design | Acceptance |
|---|---|---|---|
| E1 | Departments API | Make `Department.__init__` lazy (`_initialize_agents` on first `get_agent`). `app/api/departments_api.py`: `GET /api/departments` → `[{name, manager, specialists[]}]`; `POST /api/departments/{name}/execute {task, role?, require_json?}` → `Department.execute_task` (manager unless `role` given); publishes `department_task` event; 404 unknown department, 502 on `LLMUnavailable`, `simulated` flag carried. Mount in `main.py`. | `tests/test_departments_api.py`: list has 13 entries; execute routes to the manager; unknown → 404 |
| E2 | Departments tab | `pages/Departments.tsx`: one card per department (manager, specialists), "Ask this department" box, result with simulated badge; sidebar entry under Agents. | ask Research for sources on a topic; the manager answers |
| E3 | Workflow steps may name a department | `WorkflowRegistry.validate` accepts a department name; `WorkflowEngine` resolves `agent_role` against the registry first, else the department's manager. | a test workflow with `"agent_role": "Research"` runs |
| E4 | Every persona has a home | The 36 personas outside any class get added to the right class (or a new `creative.py`); `Department.list_agents()` union across classes == registry keys. | test asserting the union equality |

### Phase F — Right model for the job

| # | Item | Design | Acceptance |
|---|---|---|---|
| F1 | Model tiers | Frontmatter `model_tier: fast \| strong` (default `strong`; `fast` for `TagGenerator`, `TitleGenerator`, `DescriptionWriter`, `MetadataOptimizer`, `PublishingChecklist`, `TaxonomyManager`, `CitationArchivist`); `AgentDefinition.model_tier`; settings gain `tiers: {fast: {provider, model}, strong: {provider, model}}`; `LLMService.generate_text/generate_chat(..., tier=)` picks the tier's provider first, then the existing global fallback order; `BaseAgent` passes its tier. Add a `llamacpp` provider (OpenAI-compatible, `LLAMACPP_URL`, default `http://127.0.0.1:8089/v1`) so the local 27B is first-class. `Settings.tsx`: editable model names, tier mapping, `owner_channel_ids`. | `tests/test_llm.py`: tier `fast` hits the fast provider, falls back when it's down; settings round-trip |
| F2 | Temperature per persona | Frontmatter `temperature:` (default 0.7) → `AgentDefinition` → `LLMService` call. | `HorrorWriter` at 0.9 and `FactChecker` at 0.2 reach the provider payload in a test |

### Phase G — Docs and contract

| # | Item | Design | Acceptance |
|---|---|---|---|
| G1 | Docs match the code | `AGENTS.md` (counts, tiers, departments, delegation), `ARCHITECTURE.md` (departments API, events), `README.md` (agent count, Departments tab), `ECOSYSTEM.md` (new events `agent_invoked`, `department_task`; routes `/api/departments*` for Dexter tools) — copy `ECOSYSTEM.md` to `../dexter/ECOSYSTEM.md` so 0.4 still holds. | `diff ECOSYSTEM.md ../dexter/ECOSYSTEM.md` empty |

### v9 acceptance bar (felt experience)

| # | Felt experience | Proof |
|---|---|---|
| K1 | Every persona is one click away | pick any of the personas in chat and get an answer in that voice |
| K2 | I can see who did what | delegation cards in chat; `agent_invoked` on the event bus |
| K3 | I can read the script in the app | asset panel on Projects |
| K4 | Nothing lies, still | no filler text in research assets; discover fallback is badged |
| K5 | Departments answer | "Ask Research" routes to the manager and specialists |
| K6 | Cheap work goes to the local model | `fast` tier → `llamacpp` on 8089 when it is up |

### v9 not doing

- A visual workflow editor — JSON is fine while there are six workflows; C2 shows what a workflow will do.
- Merging the Agents Workbench (`custom_agents.json`, 3 presets) into the personas — separate toy system, leave it.
- Enforcing `permissions` — nothing calls tools yet; a label with no consequence is honest as long as `AGENTS.md` says so.
- Streaming chat (5.5) — still deferred.

## v11 — BuzzEdit video-production bridge (owner's ask, 2026-09-16)

**Why.** BuzzcafAI's agents write scripts and "AI image prompts" as free
Markdown, but nothing ever calls ComfyUI or produces an image/clip. BuzzEdit
is a talking-head auto-editor built around a recording (Whisper transcribe →
auto-cut → ComfyUI B-roll → FFmpeg render). Full plan:
`C:\Users\singh\.claude\plans\buzzcafai-has-agents-and-velvety-fog.md` (+
its line-referenced verification file alongside it). Owner's ask, verbatim:
"Record myself saying the script, then give it to either BuzzcafAI or
BuzzEdit, and the rest is taken care of."

Both script flows are in scope (script-first and record-first) and either app
may be the entry point; style is auto-derived from brand with a per-video
override. Phase 1 (items 1–7, 9, core of 10) is the priority; Phases 2–3
(8, 11, 12) build on it.

| # | Item | Effort | Acceptance |
|---|---|---|---|
| 1 | `integrations/buzzedit_client.py` (new): `BuzzEditClient` wrapping BuzzEdit's HTTP API, discovered via `buzzcaf_ports.discover("buzzedit", 8099, "/api/health")` | M | imports clean; `health()`/`comfyui_online()` best-effort, never raise |
| 2 | `integrations/buzzedit_script.py` (new): `to_directive_script(script_text, visual_plan) -> (annotated_text, skipped_beats)` | M | anchor located exactly or by sentence-level fuzzy match; spoken text untouched outside inserted brackets/headings |
| 3 | `integrations/buzzedit_settings.py` (new): `settings_for_brand(brand, overrides) -> PresentationSettings dict` | S | real BuzzEdit field names; overrides merged last |
| 4 | `runtime/workflow.py`: dedicated `elif output_asset_type == "visual_plan"` → `production/visual_plan.json`; `VISUAL_PLAN_JSON_INSTRUCTION` injected into the prompt (mirrors `RESEARCH_JSON_INSTRUCTION`, required because `_call_local` ignores `require_json`) | S | `python -c "from core.workflow import workflow_registry"` still loads all workflows |
| 5 | `prompts/agents/PromptEngineer.md`: extend output schema with the `visual_plan` shape (`genre`, `beats[{anchor,kind,...}]`) | S | schema documented, version bumped 1.1.0 |
| 6 | Add a "Visual Plan" step (agent `PromptEngineer`, `output_asset_type: "visual_plan"`, `input_assets: ["script"]`) to every brand workflow that produces a `script` asset | S | all 6 workflow JSONs still validate at startup |
| 7 | `app/api/produce_api.py` (new router), mounted in `main.py`: `POST /api/projects/{id}/produce_video` (background thread, module-level status dict, `active_executions`), `GET .../produce_video/status`; `video_progress`/`video_ready`/`video_failed` added to `services/events.py` | L | router import-clean, routes present in `app.openapi()["paths"]` |
| 8 | `POST /api/produce/plan {brand, script_text?, transcript?}` (reverse endpoint, same router) | S | synchronous, returns `{annotated_script, settings, visual_plan}` |
| 9 | Config/docs: `buzzedit_url` in `config.example.json`, `BUZZEDIT_URL` in `.env.example`, `ECOSYSTEM.md` §7a, this PLAN/PROGRESS entry | S | files updated |
| 10 | Frontend `Projects.tsx` (+`services/api.ts`, `lib/types.ts`): attach-recording input, Produce Video button, style-override mini-form, progress poll, output path display, teleprompter view | M | `tsc` type-checks the new code; no `npm run build` run (task instruction) |
| 11 | BuzzEdit `backend/integrations/buzzcaf_client.py` (new): discover `"buzzcaf"`, call `POST /api/produce/plan` | S | imports clean |
| 12 | BuzzEdit route + "Plan visuals with BuzzcafAI" button in `AgentPanel.tsx` (server-side round trip) | M | button visible, gated on a transcript existing |

## Not doing

- Voice (any form) until text chat, memory and control are solid.
- Deleting the `MidnightBuzz` sibling folder (owner's call; references are removed instead).
- Authentication: single-user, loopback only. Dexter's per-run token model can be copied later if the bind ever changes.
