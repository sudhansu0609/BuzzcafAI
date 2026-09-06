# Changelog

Notable changes to Buzzcaf AI Studio. Newest first.

## Unreleased

### Fixed — the app now runs as designed

- **Agent personas actually load.** `BaseAgent` looked for prompt files at a
  hardcoded path to a folder that no longer existed, so all 115 personas
  silently fell back to a generic one-line prompt — every agent behaved
  identically. Paths are now derived from the checkout location by the new
  `backend/core/paths.py`.
- **`NameError: name 'json' is not defined`** on every agent execution that had
  stored memories (`core/base_agent.py` used `json` without importing it).
- **Data no longer written outside the repo.** A missing configured path was
  silently `makedirs`-ed, so memory, logs, and project state landed in a phantom
  directory tree nobody knew about. Environment path overrides are now honoured
  only when the target already exists.
- **Settings persist.** `POST /api/settings` reported success while writing to
  the same dead path.
- **Launcher starts this checkout.** `start_spilledCoffeeAi.bat` pointed at a
  separate, diverged sibling folder on mismatched ports, so local edits appeared
  to have no effect. Replaced by `start_buzzcafai.bat` on ports 5173/8000
  matching `vite.config.ts`.
- **Test suite is green** — 135 passing, up from 133 passing / 2 failing.

### Security

- `GET /api/settings` no longer returns API keys in plaintext. Secrets are
  masked and accompanied by `<key>_set` booleans; saving with an empty field
  keeps the stored key instead of erasing it. Keys are no longer held in
  browser state.
- CORS narrowed from `allow_origins=["*"]` to the local dev origins, extensible
  via `ALLOWED_ORIGINS`. With a wildcard, any page open in the same browser
  could read the settings endpoint.
- The launcher binds `127.0.0.1` instead of `0.0.0.0`.
- Project ids are validated and resolved paths confined to the projects
  directory, closing a path-traversal hole in project and asset lookup.
- `GET /api/voice/config` masked the same way as `/api/settings`; it was
  returning the Picovoice and OpenAI Realtime keys in full. Those keys are no
  longer written to `localStorage`, and any copy left there by an earlier build
  is purged on load.

### Changed — no more silent fabrication

- Fallback responses are labelled at every layer: `LLMService` exposes
  `last_response_simulated`, API responses carry `"status": "simulated"`, and
  both chat UIs render an amber **⚠ SIMULATED** banner.
- Agent chat no longer returns `"status": "success"` from its `except` block
  with a canned greeting; failures report the actual error.
- Voice cloning is honest about being unimplemented: `synthesize_cloned_speech()`
  returns `status: "not_implemented"` with no `audioUrl` instead of a URL to a
  file that was never written and a route that never existed, and profile
  creation reports `sample_stored` rather than `ready`.
- Default Gemini model corrected from the nonexistent `gemini-3.6-flash` to
  `gemini-1.5-flash`, removing a wasted 404 round trip on every call.
- The 235-line simulated-response generator moved out of `integrations/llm.py`
  into `backend/dev/fixtures.py` and gated on `APP_ENV`. In a non-development
  environment an unreachable provider now raises `LLMUnavailable` instead of
  fabricating an answer.
- `/api/topics/discover`'s ~280-line inline vault moved to per-channel JSON in
  `backend/knowledge/seed_topics/`. Responses are tagged
  `"source": "curated_seed"` — the endpoint does not call the LLM, and no
  longer implies it did.
- Step failures are classified by exception type (`core/errors.py`) rather than
  by searching the message for words like "timeout". A `NameError` mentioning
  "connection" used to be reported as retryable; unexpected exceptions are now
  BLOCKING so they surface as the bugs they are.

### Performance and robustness

- Group chat fans out across agents concurrently instead of serially — five
  agents now take one round trip rather than five.
- The in-memory log buffer is capped at 500 lines per project (it was unbounded)
  and no longer copies unattributed lines into every concurrent run's log.
- Requests through the new `apiFetch` helper carry a 60s timeout, so a hung
  backend no longer leaves a spinner forever. `App.tsx`'s own `fetch` calls are
  not yet routed through it.

### Developer experience

- `frontend/src/services/http.ts` centralises the API base; the AI Studio pages
  no longer hardcode `http://localhost:8000`, which broke whenever the backend
  moved.
- Voice intent keywords consolidated into `app/services/voice_intent.py`; the
  unused duplicate endpoint `/api/voice/parse_intent` was removed. The frontend
  keeps a smaller offline copy on purpose, now labelled as such.
- `delete_agent` expresses its intent directly (refuse presets, else remove)
  instead of re-adding presets to a filtered list.
- Deprecated Pydantic v1 `.dict()` replaced with `model_dump()`; silent
  `except: pass` blocks in `memory.py` and `main.py` now log.
- Duplicate "Spilled Coffee: After Dark" / "Spilled Coffee After Dark" brand
  entries collapsed; channel matching compares canonical slugs rather than
  substrings in both directions.
- One dependency manifest at the repo root, containing what the code actually
  imports (`requests`, `python-dotenv`, `python-multipart`, `pytest`, `httpx`
  were all missing). The unused SQLAlchemy/Postgres/Alembic stack was dropped.
- CI added (`.github/workflows/ci.yml`): `pytest`, `tsc --noEmit`, and
  `vite build` on every push and pull request.
- `README.md`, `ARCHITECTURE.md`, `AGENTS.md`, and this file rewritten against
  verified behavior. `IMPROVEMENTS.md` tracks the remaining debt.
- Project renamed back to Buzzcaf AI Studio; MidnightBuzz naming removed.

## 2026-07-28

- Agents Creator Studio and Group Chat workbench with local LM Studio / Ollama
  support and continuous voice commands.

## 2026-07-26

- Initial repository: 115 Markdown-defined agents, JSON workflow definitions,
  FastAPI backend, React studio UI.
