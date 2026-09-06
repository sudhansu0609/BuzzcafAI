# ☕ Buzzcaf AI Studio

A local, single-user multi-agent studio for producing YouTube content across five
channel brands (**Beyond3Baje**, **Spilled Coffee After Dark**, **Life3Baje**,
**Khayal3Baje**, **Spilled Coffee Studio**).

115 agent personas are defined as Markdown files with YAML frontmatter and
discovered at startup; workflows are JSON step definitions with per-step human
approval gates. A FastAPI backend runs them against Gemini, OpenAI, or a local
LM Studio / Ollama server.

> Every command and claim below was run against this checkout. See
> [ARCHITECTURE.md](ARCHITECTURE.md) for what the code actually does, and
> [AGENTS.md](AGENTS.md) for how to author an agent.

---

## Quick start

Requires Python 3.10+ and Node 18+.

```bash
# 1. Backend
pip install -r requirements.txt
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

- Studio UI: <http://localhost:5173>
- API docs: <http://127.0.0.1:8000/docs>

On Windows, `start_buzzcafai.bat` starts both from this checkout on those ports.

Then open **Settings** in the UI and add a Gemini or OpenAI key, or point the
app at a local LM Studio server. Without a working provider the app still
responds, but every reply is labelled **⚠ SIMULATED** — see
[Simulated responses](#simulated-responses).

### CLI

`backend/main.py` exposes the same engine without the web UI:

```bash
cd backend
python main.py list-agents         # all 115 registered personas
python main.py list-workflows
python main.py list-projects
python main.py diagnostics
python main.py create-project --name "Title" --brand Beyond3Baje --workflow life3baje_video
python main.py start-server --port 8000 --host 127.0.0.1
```

### Tests

```bash
cd backend && python -m pytest tests -q     # 135 tests
cd frontend && npx tsc --noEmit && npm run build
```

Both run in CI on every push and pull request (`.github/workflows/ci.yml`).

---

## Configuration

Paths are derived from the checkout location by `backend/core/paths.py`; nothing
needs editing to move or rename the project. Copy `.env.example` to `.env` to
override anything.

| Setting | Where | Notes |
|---|---|---|
| API keys | Settings UI → `backend/config/config.json`, or `.env` | The API never returns stored keys, only whether one is set |
| Provider order | Settings UI | Falls back Gemini → OpenAI → LM Studio |
| Ports | `frontend/vite.config.ts` + `start_buzzcafai.bat` | Frontend 5173, backend 8000; the dev proxy forwards `/api` |
| Data directories | `.env` (`PROJECTS_PATH`, `KNOWLEDGE_PATH`, `PROMPTS_PATH`, `LOGS_PATH`) | Optional. Honoured only if the directory already exists |

---

## Security posture

**This is a local, single-user application. There is no authentication, and no
endpoint checks a token.** Run it bound to `127.0.0.1` only — the launcher does
this deliberately. Do not expose it to a LAN or the internet as-is.

What is in place:

- CORS is restricted to the local dev origins; add more via `ALLOWED_ORIGINS`.
- `GET /api/settings` masks API keys and returns `<key>_set` booleans instead.
  Saving with an empty field keeps the stored key rather than erasing it.
- Project ids are validated and resolved paths are confined to the projects
  directory, so a crafted id cannot read files elsewhere on disk.

---

## Simulated responses

When no LLM provider succeeds, the app returns canned text rather than failing.
This is always labelled, never silent:

- `LLMService.last_response_simulated` is set on the service.
- API responses carry `"status": "simulated"` and `"simulated": true`.
- The chat UI shows an amber **⚠ SIMULATED** banner on those messages.

If you see that banner, no model was reached — check Settings and that your
provider is running. A response without the banner came from a real model.

---

## Not implemented

Stated plainly so nobody builds on it:

- **Server-side voice cloning.** Uploading a reference clip stores the WAV
  (`status: "sample_stored"`); no embedding is extracted and no TTS engine is
  wired up. `synthesize_cloned_speech()` returns `status: "not_implemented"` and
  no `audioUrl`; the UI falls back to browser speech synthesis.
- **Authentication.** `POST /login` returns a placeholder token that nothing
  verifies.
- **Database.** `app/db/`, `app/models/`, and `alembic.ini` exist but no code
  path opens a database. All state is JSON on disk.
- **Most of the file tree.** Roughly two thirds of the Python files and nearly
  all frontend files under `src/pages/` are empty scaffolding that nothing
  imports. See [ARCHITECTURE.md](ARCHITECTURE.md) for the modules that are real.

## Channel brands

1. **Beyond3Baje 🔍** — fact-grounded documentaries, true crime, dark history.
2. **Spilled Coffee After Dark 🕯️** — folklore, 3 AM encounters, regional horror.
3. **Life3Baje 🌿** — reflective personal essays and atmospheric video essays.
4. **Khayal3Baje 👁️** — fictional horror and speculative narrative.
5. **Spilled Coffee Studio ☕** — flagship long-form storytelling.

Content is authored in Hinglish (conversational Hindi in Roman script) — the
channel guides under `backend/prompts/channels/` define each brand's voice.

## License

`LICENSE` is currently a placeholder. Treat this repository as all rights
reserved until it is filled in.
