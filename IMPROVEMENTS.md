# BuzzcafAI / MidnightBuzz — Code Review & Improvement Plan

**Reviewed:** 2026-08-12 · branch `main` @ `ba10a13`
**Scope:** full repo (backend FastAPI + frontend React/Vite + prompts/docs)

Everything below was verified against the code — file:line references are exact, and the
"Evidence" lines are real command output, not inference. Two findings were reproduced by
actually importing the app and running the test suite.

---

## TL;DR — the five things that actually matter

| # | Issue | Impact |
|---|-------|--------|
| 1 | Hardcoded absolute paths to a **deleted** `SpilledCoffeeAI` folder in 3 core modules | Agent personas never load; memory/logs written to a phantom directory outside the repo |
| 2 | `json` used but never imported in `core/base_agent.py` | **Every** agent execution raises `NameError` when it has stored memories |
| 3 | `GET /api/settings` returns raw API keys, no auth, `CORS allow_origins=["*"]` | Any website open in your browser can steal your Gemini/OpenAI keys |
| 4 | LLM failures silently fall through to hardcoded fake text | You cannot tell a real model answer from a canned one |
| 5 | ~64% of Python files and ~93% of frontend files are empty stubs | The repo's apparent size is ~10x its real size; navigation and search are poisoned |

---

## Tier 1 — Broken right now (fix first)

### 1.1 Three modules point at a directory that no longer exists

The project was renamed (`SpilledCoffeeAI` → `BuzzcafAI` / `MidnightBuzz`) but three
modules still hold Windows-absolute paths to the old location:

| File | Line | Stale path |
|------|------|-----------|
| `backend/core/config.py` | 9–10, 32–34 | `b:\...\SpilledCoffeeAI\backend\.env`, `...\config\config.json`, `PROJECTS_PATH`, `KNOWLEDGE_PATH`, `PROMPTS_PATH` |
| `backend/core/base_agent.py` | 24 | `b:\...\SpilledCoffeeAI\backend\prompts\agents` |
| `backend/integrations/llm.py` | 11 | `b:\...\SpilledCoffeeAI\backend\config\config.json` |
| `.env` | 4–6 | `PROJECTS_PATH` / `KNOWLEDGE_PATH` / `PROMPTS_PATH` |

Three separate consequences, all bad:

**(a) Agent personas silently never load.** `BaseAgent._load_system_prompt()`
(`core/base_agent.py:23`) looks for `{agent_name}.md` at the dead path, fails, and falls
back to a one-line generic prompt:

```
WARNING  System prompt file for agent ResearchAgent not found at
         b:\...\SpilledCoffeeAI\backend\prompts\agents\ResearchAgent.md. Using default.
```

The 115 carefully written persona files in `backend/prompts/agents/` are **never read by
the thing that builds the LLM prompt**. `AgentRegistry` (`core/agent.py:9`) does use a
correct relative path, so the UI counts 115 agents and the roster looks healthy — the
agents just all behave identically because they share the default prompt. This is the
single highest-value fix in the repo: the product's core differentiator is currently
inert.

**(b) A phantom directory tree gets recreated on import.** `ConfigurationManager.validate()`
(`core/config.py:97-103`) calls `os.makedirs` on any missing configured path. Simply doing
`import app.main` recreates `B:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\{knowledge,logs,projects,prompts}`
and writes agent memory JSON, `app.log`, and project state there. I reproduced this during
review (the folder did not exist beforehand; I removed the tree I created afterwards).
So all persistent memory the app writes lands **outside the repo**, in a directory nobody
knows exists, and is invisible to git.

**(c) Settings never persist.** `save_config()` (`integrations/llm.py:58`) writes to the
same dead path, so `POST /api/settings` reports `"status": "success"` while writing your
API keys into the phantom tree instead of `backend/config/config.json`.

**Fix:** derive every path from the module location, once.

```python
# backend/core/paths.py  (new)
from pathlib import Path
BACKEND_DIR = Path(__file__).resolve().parent.parent   # .../backend
PROMPTS_DIR   = BACKEND_DIR / "prompts"
KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
PROJECTS_DIR  = BACKEND_DIR / "projects"
CONFIG_PATH   = BACKEND_DIR / "config" / "config.json"
DOTENV_PATH   = BACKEND_DIR / ".env"
```

Then import from there in `config.py`, `base_agent.py`, `integrations/llm.py`, and delete
the absolute `PROJECTS_PATH`/`KNOWLEDGE_PATH`/`PROMPTS_PATH` entries from `.env` (keep them
as *optional* overrides, defaulted to the computed values). Add a guard so a stale override
fails loudly rather than silently `makedirs`-ing a new tree:

```python
if not (path.exists() or path.parent.exists()):
    raise ValueError(f"{key} points outside the project: {path}")
```

---

### 1.2 `NameError: name 'json' is not defined` on every agent execution

`backend/core/base_agent.py:95` calls `json.dumps(m.content)`, but the module's imports
(lines 2–8) are `abc`, `os`, `logging`, `typing`, `LLMService`, `Context`, `Result` — no
`json`.

The line only runs when the agent has stored memories (`agent_memories` non-empty), which
is why it isn't caught immediately — but memories accumulate on *every* execution
(`base_agent.py:112-120`), so the second call for any given agent blows up.

**Evidence** — from `python -m pytest tests`:

```
ERROR  [BLOCKING] Error executing agent step 'Research': name 'json' is not defined
FAILED tests/test_studio.py::test_error_handling_compliance
```

**Fix:** add `import json` at the top of `backend/core/base_agent.py`. One line.

Note the failure mode this exposes: `WorkflowEngine` catches the exception, classifies it
as `BLOCKING` (`runtime/workflow.py:337-345`) — string-matching on the message text — and
re-raises. A `NameError` in our own code gets laundered into a user-facing "blocking
workflow error." See §3.3.

---

### 1.3 Test suite is red

```
2 failed, 133 passed in 5.28s
FAILED tests/test_core.py::test_memory_system              - assert 0 > 0
FAILED tests/test_studio.py::test_error_handling_compliance - assert False
```

`test_memory_system` fails because memory writes go to the phantom tree (§1.1b);
`test_error_handling_compliance` fails on the `json` NameError (§1.2). Both should go green
once those two are fixed — a good way to confirm the fixes landed.

Also: there is no CI. 133 passing tests that nobody runs will rot. A 15-line GitHub Actions
workflow (`pytest` + `tsc --noEmit` + `vite build`) would have caught all of the above.

---

### 1.4 Port and path configuration disagree three ways

| Source | Frontend port | Backend port |
|--------|--------------|--------------|
| `start_spilledCoffeeAi.bat:9-10` | 3005 | 8095 |
| `frontend/vite.config.ts:7-12` | 5173 | 8000 (proxy target) |
| `README.md:32,42` | 5173 | 8000 |
| `docker-compose.yml` | 5173 | 8000 |

On top of that, the launcher in *this* repo starts the app from a **different checkout**:

```bat
set "FRONTEND_DIR=%APP_DIR%..\MidnightBuzz\frontend"
set "BACKEND_DIR=%APP_DIR%..\MidnightBuzz\backend"
```

`../MidnightBuzz` exists as a separate, diverged copy (`backend/app/main.py` and
`frontend/src/App.tsx` both differ from this repo's, and it has no `.git`). So editing code
here and running the `.bat` launches *the other tree* — changes appear to have no effect.
This is a trap that will burn hours.

**Fix:** pick one canonical checkout. Point the launcher at `%APP_DIR%frontend` /
`%APP_DIR%backend`, put ports in one place (a root `.env` read by both Vite and uvicorn),
and either merge `../MidnightBuzz`'s divergence back in or delete it. Also rename the
launcher — `start_spilledCoffeeAi.bat` is a third product name, and it's untracked
(`git status` shows `?? start_spilledCoffeeAi.bat`).

---

### 1.5 Cloned-voice audio can never play

`voice_engine.synthesize_cloned_speech()` (`app/services/voice_engine.py:78`) returns
`"audioUrl": f"/api/voice/audio/{output_filename}"` for a file it never wrote, pointing at
a route that does not exist:

```
$ grep -rn "voice/audio" backend/ --include=*.py
backend/app/services/voice_engine.py:78:   "audioUrl": f"/api/voice/audio/{output_filename}",
```

`AgentsGroupChat.tsx:233` renders a play button bound to that URL, so every playback 404s.
The method also claims `"engine": "F5-TTS / XTTS v2 Zero-Shot Local Engine"` and
`"status": "synthesized"` — no synthesis happens anywhere in the file. `process_voice_cloning_sample()`
likewise saves the WAV and writes `"status": "ready"` without extracting any embedding.

**Fix:** either wire up a real TTS backend and add the `GET /api/voice/audio/{filename}`
route (with a filename allowlist — don't join user input into a path), or make the stub
honest: `"status": "not_implemented"`, omit `audioUrl`, and have the UI hide the play
button. Right now the failure is invisible until a user clicks.

---

## Tier 2 — Security

### 2.1 API keys are readable by any origin, unauthenticated

```python
# backend/app/main.py:125-127
@app.get("/api/settings")
def get_settings():
    return load_config()     # includes gemini_api_key, openai_api_key in plaintext
```

with, at `main.py:25-31`:

```python
allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
```

Any page you visit while the studio is running can `fetch('http://localhost:8000/api/settings')`
and read your Gemini and OpenAI keys. "It's localhost" is not a mitigation — localhost is
exactly what a malicious page in your browser can reach. And the `.bat` binds
`--host 0.0.0.0`, exposing it to the whole LAN.

Separately, `allow_origins=["*"]` combined with `allow_credentials=True` is rejected by
browsers per the CORS spec, so the credentialed path silently doesn't work as intended.

**Fix, in order:**
1. Mask secrets on read — return `"sk-…abcd"` or `{"gemini_api_key_set": true}`, never the value.
2. `allow_origins=["http://localhost:5173"]` (explicit list), drop `allow_credentials` unless cookies are actually used.
3. Bind `127.0.0.1` in the launcher, not `0.0.0.0`.
4. Prefer environment variables over a JSON file for keys; the settings UI should write to `.env`, not echo secrets back.

### 2.2 Authentication is a stub that returns a fake token

```python
# backend/app/api/auth.py — the entire file
@router.post('/login')
def login():
    return {'token':'<jwt>'}
```

This router is mounted into the live app (`main.py:19-22`). Meanwhile there are *four*
unused, more serious auth implementations sitting in the repo (`app/auth/jwt.py`,
`apps/api/auth/`, `admin/roles.py`, `frontend/src/hooks/useAuth.ts`) — all stubs too. No
endpoint anywhere checks a token. Every route is fully public.

**Fix:** if the app is single-user and local, delete the auth router and the four dead auth
trees, and say "local single-user, no auth" in the README. If multi-user is planned, build
exactly one implementation. What's there now is worse than nothing: it implies protection
that doesn't exist.

### 2.3 Path traversal in project lookup

`Project.load()` (`core/models/project.py:59-62`) does
`os.path.join(projects_dir, project_id, "project.json")` with no validation, and
`project_id` comes straight from the URL (`main.py:200`, `:208`, `:230`, `:234`).
An encoded `..%2F..%2F` sequence lets a caller read any `project.json` on the drive. Low
severity in isolation, but it composes badly with 2.1's wildcard CORS.

**Fix:** validate against `^[A-Za-z0-9_\-]+$` before joining, and assert the resolved path
stays under `PROJECTS_DIR`:

```python
resolved = (PROJECTS_DIR / project_id).resolve()
if PROJECTS_DIR.resolve() not in resolved.parents:
    raise HTTPException(400, "Invalid project id")
```

### 2.4 Secrets stored in browser localStorage

`App.tsx:155-156` persists `picovoice_key` and `openai_realtime_key` to `localStorage`,
readable by any script on the page. Same fix direction as 2.1 — keep keys server-side.

---

## Tier 3 — Correctness & honesty of behavior

### 3.1 Fake responses are indistinguishable from real ones

Three separate layers fabricate plausible content when the real thing fails:

| Location | Behavior |
|----------|----------|
| `integrations/llm.py:117` → `_generate_simulated_response` (lines 229-464, **235 lines**) | All providers failed → returns hand-written fake scripts and topic lists |
| `app/services/local_llm.py:107-111` | LLM unreachable → `"[Simulated Response from {model}]..."` |
| `app/services/local_llm.py:60-68` | No local models found → invents six model entries |
| `app/main.py:286-587` (**300 lines**) | `/api/topics/discover` ignores the LLM entirely and returns a hardcoded vault |
| `app/main.py:895-902` | Agent chat exception → returns `"status": "success"` with canned greeting |

The last one is the most damaging: an error path that reports success. The frontend has no
way to distinguish "the strategist analyzed your channel" from "the LLM call threw and we
made something up."

Given §1.1a (personas never load) and §1.2 (`NameError` on nearly every execution), it is
likely that **most output the app has ever produced came from these fallbacks**. That would
explain why responses feel consistent across different agents.

**Fix:**
- Every fallback response must carry `"status": "fallback"` (or `"error"`) and the frontend must render it visibly differently — a banner, a muted style, an explicit "simulated" chip.
- Never return `"status": "success"` from an `except` block (`main.py:895`).
- Move the 235-line simulated-response generator to `backend/dev/fixtures.py`, gated behind `APP_ENV=development`. It doesn't belong in the production call path.
- `/api/topics/discover`'s hardcoded vault is fine as *seed data* — load it from a JSON file under `backend/knowledge/seed_topics/`, not from a 300-line dict inside a route handler.

### 3.2 Model IDs that don't exist

`app/main.py:73` defaults `gemini_model` to `"gemini-3.6-flash"`; `integrations/llm.py:18`
uses the same. There is no such model — the real fallback chain at `integrations/llm.py:156`
(`gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-2.0-flash-exp`) is what actually saves this,
by retrying after the bogus first attempt 404s. So every Gemini call currently wastes a
round trip. Set the default to a model that exists and let the chain handle genuine
failures. (The README claims "Gemini API 1.5 Flash" — three names for one setting.)

### 3.3 Error classification by string-matching

`runtime/workflow.py:337-345` decides whether a failure is `RETRYABLE`, `RECOVERABLE`, or
`HUMAN_INTERVENTION_REQUIRED` by searching the exception's *message text* for `"timeout"`,
`"connection"`, `"429"`, `"not found"`, `"approval"`. A `NameError` mentioning a variable
named `connection` would be classified retryable; the real `NameError` from §1.2 became
`BLOCKING`. Use exception types (`requests.Timeout`, `requests.ConnectionError`, a custom
`ApprovalRequired`) instead, and let genuinely unexpected exceptions surface as bugs rather
than being categorized as workflow states.

### 3.4 Log handler leaks memory and misattributes lines

`InMemoryLogHandler` (`main.py:41-56`) appends to an unbounded `defaultdict(list)` — a
long-running server grows without limit — and when a record has no `project_id` it copies
the line into **every** active execution's log (`main.py:50-52`), so concurrent runs see
each other's output. Use a `collections.deque(maxlen=500)` per project, and attach
`project_id` via a `logging.LoggerAdapter` at execution start instead of guessing.

### 3.5 Frontend hardcodes `http://localhost:8000`

`AgentCreatorStudio.tsx:51,64,90,124` and `AgentsGroupChat.tsx:42,128` call
`http://localhost:8000/...` directly, bypassing the Vite proxy that every other call in
`App.tsx` uses (relative `/api/...`). These break the moment the backend moves — including
right now, if you use the `.bat`, which runs it on **8095** (§1.4).

**Fix:** use relative `/api/...` everywhere and let the proxy handle it. Better, add a
single `src/services/http.ts` with a `const BASE = import.meta.env.VITE_API_BASE ?? ''`
and route all calls through it.

### 3.6 Stale prebuilt bundle served in production

`backend/app/main.py:1117` mounts `backend/app/static/` at `/`, serving
`assets/index-CwIcJBdJ.js` — built **2026-07-24**, four days before the last two commits.
Anyone running the backend without the Vite dev server gets a UI that predates the Agents
Studio and Group Chat entirely. Either add a build step that refreshes it (`npm run build`
→ copy to `app/static/`) or drop the mount and document that the frontend runs separately.

---

## Tier 4 — Structure: the repo is ~10x its real size

### 4.1 Empty stubs everywhere

```
Python files with <5 lines:   155 of 243   (64%)
Frontend .ts/.tsx <5 lines:   100 of 107   (93%)
```

Representative samples — these are complete files:

```python
# backend/app/llm/router.py
class LLMRouter: pass

# backend/app/orchestrator.py
class DepartmentOrchestrator: pass

# backend/integrations/ai/provider_router.py
class ProviderRouter: pass
```

```tsx
// frontend/src/router.tsx — entire file
// React Router configuration
```

The real application is five files:

| File | Lines |
|------|-------|
| `frontend/src/App.tsx` | 3,539 |
| `backend/app/main.py` | 1,119 |
| `backend/integrations/llm.py` | 480 |
| `frontend/src/pages/ai/AgentCreatorStudio.tsx` | 430 |
| `backend/runtime/workflow.py` | 338 |

Everything else is scaffolding. The cost is not disk space — it's that grep, IDE
auto-import, and any future agent or teammate reading this repo will surface hundreds of
files that do nothing. `frontend/src/router.tsx` is never imported (`main.tsx` renders
`App` directly), so all 40+ files under `frontend/src/pages/` except the two `ai/` ones are
unreachable.

**Fix:** delete the stubs. If they're a design record, they belong in `docs/` as a
structure diagram, not as importable modules. Keep only what's imported — a five-minute
`git rm` pass removes ~250 files and makes the codebase legible.

### 4.2 Four parallel implementations of the same subsystems

| Concern | Duplicate locations |
|---------|--------------------|
| LLM provider routing | `backend/app/llm/`, `backend/integrations/ai/`, `llm_engine/`, `backend/integrations/llm.py` ← *only this one is real* |
| Agent runtime | `agent_runtime/`, `backend/app/runtime/`, `backend/runtime/` ← *real*, `backend/core/agent.py` ← *real* |
| API app | `backend/app/main.py` ← *real*, `backend/apps/api/main.py`, `backend/main.py` |
| Dashboard UI | `frontend/` ← *real*, `backend/apps/dashboard/`, `backend/app/static/` |
| Auth | `app/api/auth.py` ← *mounted*, `app/auth/`, `apps/api/auth/`, `admin/` |
| Knowledge/memory | `backend/knowledge/`, `backend/knowledge_engine/`, `backend/app/knowledge/`, `backend/memory/` ← *real*, `backend/memory_engine/` |

Root-level `agent_runtime/`, `llm_engine/`, `event_system/`, `production/`, `research/`,
`writing/`, `knowledge/` duplicate `backend/` packages and total 41 lines across 19 files.

**Fix:** keep one of each, delete the rest, and record the choice in `docs/ARCHITECTURE.md`
(which should replace the 189 files currently in `docs/` — see 4.4).

### 4.3 `App.tsx` is a 3,539-line component

56 `useState` calls and 8 `useEffect`s in one function; it contains the dashboard, project
list, topic vault, chat, voice dictation, settings, and health panels. Every keystroke in
any field re-renders all of it.

**Fix, incrementally** — no big-bang rewrite needed:
1. Extract the API layer first: move all 22 `fetch` calls into `src/services/` (files already exist as stubs). Zero render-behavior risk.
2. Extract voice dictation (~15 states, `App.tsx:136-156` + handlers at `:462-730`) into `useVoiceDictation()`. It's the most self-contained cluster.
3. Split by tab into `src/pages/` — `Dashboard`, `TopicVault`, `Settings`, `Health`. The `activeTab` switch already marks the seams.
4. Then consider `useReducer` or Zustand for the remaining shared state.

Also: `frontend/package.json` has no linter and no test runner, and `tsc` only runs during
`npm run build`. Add `eslint` + `tsc --noEmit` to CI.

### 4.4 189 documentation files describing a system that doesn't exist

`docs/` contains `WorkflowRegistryImplementation.md`, `ConfigurationValidation.md`,
`Pack7_README.md`…`Pack11_README.md`, `ARCHITECTURE_v1.md` alongside `Architecture.md`,
`README_v1.md` alongside `README.md`. Much of it documents the stub modules from 4.1 —
i.e. describes behavior no code implements. `CHANGELOG.md` is one line: "v1 repository
milestone completed."

**Fix:** replace with four files that are true — `README.md` (setup that actually works),
`ARCHITECTURE.md` (the real five modules), `AGENTS.md` (how `prompts/agents/*.md` are
authored and loaded), `CHANGELOG.md`. Archive the rest under `docs/archive/` or delete;
they are currently a liability, since anyone (human or AI) reading them will build on
assumptions the code doesn't hold.

### 4.5 README claims vs. reality

| README says | Reality |
|-------------|---------|
| "115 Autonomous AI Agents … 19 departments" | 115 `.md` files exist and register, but **none of their prompts reach the LLM** (§1.1a) |
| "Google Gemini API 1.5 Flash" | Default is `gemini-3.6-flash`, a nonexistent model (§3.2) |
| "Disk-persisted JSON memory logs" | Persisted to a phantom directory outside the repo (§1.1b) |
| `python main.py start-server --port 8000` | The `.bat` uses `uvicorn app.main:app --port 8095` |
| "MIT License" | `LICENSE` contains 4 bytes |

### 4.6 Dependency manifests are incomplete

`requirements.txt` lists `fastapi, uvicorn, pydantic`. Actually imported but unlisted:
`requests` (`integrations/llm.py:4`), `python-dotenv` (`core/config.py:5`),
`python-multipart` (required by `UploadFile` in `agents_api.py:55`), `pytest`.
`backend/requirements.txt` is a *different* list (`sqlalchemy, psycopg2-binary, alembic`)
for a database the app never opens — there's an `alembic.ini` and `app/db/`, but every
route reads and writes JSON files. A fresh `pip install -r requirements.txt` produces a
non-working install.

**Fix:** one manifest, generated from actual imports, pinned. Drop the SQLAlchemy/Postgres
stack (including the `db` service in `docker-compose.yml`) until something uses it.

---

## Tier 5 — Smaller items worth queuing

- **`.dict()` is deprecated** — `main.py:661`, `agents_api.py:40` use Pydantic v1 `.dict()` while `main.py:132` correctly uses `.model_dump()`. Standardize on v2.
- **`urllib` vs `requests`** — `app/services/local_llm.py` hand-rolls HTTP with `urllib.request` while `integrations/llm.py` uses `requests`. Pick one; `requests` is already a dependency.
- **Blocking I/O in sync routes** — `execute_project_step` (`main.py:208`) runs a 60s LLM call in a `def` handler, occupying a threadpool worker; group chat (`agents_api.py:83`) loops over agents *serially*, so N agents take N×30s. Make them `async def` with an async HTTP client, and `asyncio.gather` the group chat fan-out.
- **No streaming** — every LLM call blocks to completion. `local_llm.py:5` imports `Generator` but nothing streams. SSE or WebSocket streaming would transform perceived latency in chat.
- **No request timeouts on the frontend** — a hung backend leaves spinners forever. Add `AbortSignal.timeout(60_000)`.
- **`delete_agent` logic reads wrong** (`agents_registry.py:106`): `[a for a in agents if a.get("id") != agent_id or a.get("isPreset", False)]` keeps presets *by re-adding them* rather than rejecting the delete outright; the API then reports success-or-400 based on list length. Express the intent directly: refuse if preset, else filter.
- **Duplicate brand names** (`main.py:105`): `"Spilled Coffee: After Dark"` and `"Spilled Coffee After Dark"` are both listed, and the topic-vault matcher (`main.py:570`) does substring matching in both directions, so `"Life3Baje"` could match unexpectedly. Use a canonical slug per channel.
- **Voice intent parsing is duplicated three times** — `/api/voice/parse_intent` (`main.py:907`), `/api/jarvis/voice` (`main.py:994`), and again in the frontend (`App.tsx:599`). Three keyword tables that will drift. Keep the backend one; delete the others.
- **Bare `except: pass`** — `memory.py:82,127`, `main.py:55,253`, `agents_registry.py:79` swallow errors silently, including the phantom-directory writes from §1.1b. Log at minimum.
- **`.env.example` is 74 bytes** and doesn't list `GEMINI_API_KEY`, `OPENAI_API_KEY`, or the port variables.
- **`docker-compose_v1.yml`** is 28 bytes; `Dockerfile` copies the repo root but `requirements.txt` there lacks the real deps (§4.6), so the image won't run.

---

## Suggested sequencing

**Session 1 — make it actually work (~2 hours)**
1. `import json` in `core/base_agent.py` (§1.2)
2. Create `core/paths.py`; fix the three stale absolute paths and `.env` (§1.1)
3. Re-run `pytest` — expect 135 passed
4. Verify a real agent prompt loads: the `WARNING ... Using default` line should disappear
5. Fix the launcher's ports and directories; delete or merge `../MidnightBuzz` (§1.4)

**Session 2 — stop lying to the user (~3 hours)**
6. Mask keys in `GET /api/settings`; lock CORS to the dev origin; bind 127.0.0.1 (§2.1)
7. Tag every fallback with `"status": "fallback"`; remove `"success"` from the `except` block at `main.py:895` (§3.1)
8. Surface fallback state visibly in the UI
9. Fix the `gemini-3.6-flash` default (§3.2)
10. Make the voice stub honest or implement it (§1.5)

**Session 3 — reclaim the codebase (~2 hours)**
11. Delete the 255 stub files and the duplicate subsystem trees (§4.1, §4.2)
12. Collapse `docs/` to four true documents (§4.4)
13. Rewrite `README.md` against verified commands (§4.5)
14. Fix `requirements.txt` (§4.6); add CI running `pytest` + `tsc --noEmit`

**Ongoing**
15. Incrementally split `App.tsx` (§4.3), starting with the services layer
16. Async + streaming for LLM calls (§Tier 5)

---

## What's genuinely good

Worth saying, because the problems above are mostly *config rot*, not bad design:

- **`prompts/agents/*.md` with YAML frontmatter** is an excellent pattern — 115 agents defined as data, discovered dynamically (`core/agent.py:33`), validated on load, with dependency checks. Once §1.1a is fixed, this is the app's strongest asset.
- **Markdown-defined workflows** (`prompts/workflows/*.json`) with per-step approval gates and asset lineage (`runtime/workflow.py`) is a sound content-pipeline model.
- **Provider fallback chain** (`integrations/llm.py:85-114`) — try selected, then Gemini → OpenAI → LM Studio — is the right shape; it just needs to stop terminating in fabrication.
- **133 passing tests** across core, runtime, workflow, memory, and agents is more test coverage than most projects this age have.
- **`[INVOKE_AGENT: X] … [/INVOKE_AGENT]` delegation** (`main.py:704-734`) is a clean, debuggable approach to agent-to-agent handoff — visible in the transcript, easy to trace.
- **`Diagnostics.get_report()`** (`core/diagnostics.py`) is a genuinely useful health endpoint.

The architecture is sound. It's the wiring — three hardcoded paths and a missing import —
that's currently preventing it from running as designed.

---

### Note on review side effects

Reproducing §1.1b created
`B:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\` (backend/{knowledge,logs,projects,prompts}).
I verified it did not exist beforehand and removed it after confirming the finding. It will
reappear the next time the backend is imported, until §1.1 is fixed.
