# ☕ Buzzcaf AI Studio

A local, single-user multi-agent studio for producing YouTube content across five
channel brands (**Originals**, **Raat3Baje**, **Beyond3Baje**,
**Life3Baje**, **Khayal3Baje**).

105 agent personas across 13 departments are defined as Markdown files with YAML
frontmatter and discovered at startup; workflows are JSON step definitions with
per-step human approval gates. A FastAPI backend runs them against Gemini,
OpenAI, or a local LM Studio / llama.cpp server — each persona declares a model
tier, so cheap work (tags, titles, checklists) can go to the local model while
the writing stays on the strong one.

> Every command and claim below was run against this checkout. See
> [ARCHITECTURE.md](ARCHITECTURE.md) for what the code actually does, and
> [AGENTS.md](AGENTS.md) for how to author an agent.

---

## Quick start

Requires Python 3.10+ (with WebView2, present on Windows 11) and, for
development, Node 18+.

**Use it:** double-click `Buzzcaf Studio.vbs`. It runs `pythonw backend/desktop_app.py`:
preflight, FastAPI on `127.0.0.1:8099` in-process, and a native window with no
console. Closing the window ends the process. Dexter can also launch it
("open the studio"). If 8099 is taken by another app the Studio steps to the
next free port and records it in `backend/config/studio.runtime.json`; a second
launch attaches to the running Studio instead of starting another.

**Develop it:**

```bash
pip install -r requirements.txt
cd frontend && npm install && npm run build      # writes backend/app/static
start_buzzcafai.bat --dev                        # one console: backend + our Vite (5173, or the next free port)
```

- API docs: <http://127.0.0.1:8099/docs>
- The built UI is served at `/` by the backend; `--dev` opens the Vite server instead.

Then open **Settings** in the UI and add a Gemini or OpenAI key, or point the
app at a local LM Studio server. Without a working provider the app still
responds, but every reply is labelled **⚠ SIMULATED** — see
[Simulated responses](#simulated-responses).

### CLI

`backend/apps/cli/main.py` exposes the same engine without the UI:

```bash
cd backend
python -m apps.cli.main list-agents         # all 105 registered personas
python -m apps.cli.main list-workflows
python -m apps.cli.main list-projects
python -m apps.cli.main diagnostics
```

### Tests

```bash
cd backend && python -m pytest tests -q     # 169 tests
cd frontend && npx tsc --noEmit && npm run build
```

Both run in CI on every push and pull request (`.github/workflows/ci.yml`).

---

## Analyze (v6)

The **Analyze** tab takes a YouTube video or channel link and answers two
questions: why does it perform, and how do we model our video on it. Data comes
from yt-dlp with no API key (views, likes, comments, captions, the "most
replayed" heatmap, and the channel's last 30 uploads as the baseline); the
reading is one model call with the selected channel's brand guide, so the
blueprint (titles, hook script, outline, thumbnail direction, tags, length,
CTA, what not to copy) is written for *that* channel. "Save as topic" puts the
first working title in the Topic Vault; "Start a project" creates a production
project on the channel's default workflow. When no model answers you get the
numbers and a "numbers only" badge, never an invented analysis. Dexter can ask
for the same thing: "analyse this video <link> for beyond3baje".

## The staff (v9)

Every persona is one click away, and you can see who did what.

- **Studio Assistant** — the persona picker is fed by `/api/agents`, grouped by
  department. The channel's strategist is the default; pick `FactChecker` or
  anyone else and the choice is remembered for that channel. When a strategist
  hands work on with `[INVOKE_AGENT: X]`, a card appears under the reply with
  the task and the specialist's answer (three delegations per reply, depth 1).
- **Departments** — one card per department with its manager and specialists,
  and an "Ask this department" box. The manager answers unless you pick a
  specialist.
- **Personas** — all 105, grouped by department, filterable by name or
  department.
- **Projects** — the workflow's steps as a timeline (done / current / waiting /
  pending, approval steps marked) and an asset panel that renders the script,
  research or SEO package in the window.
- **Dashboard** — the chosen workflow's steps are listed before you create the
  project, so you can see what it will do.

## Configuration

Paths are derived from the checkout location by `backend/core/paths.py`; nothing
needs editing to move or rename the project. Copy `.env.example` to `.env` to
override anything.

| Setting | Where | Notes |
|---|---|---|
| API keys | Settings UI → `backend/config/config.json`, or `.env` | The API never returns stored keys, only whether one is set |
| Provider order | Settings UI | Falls back Gemini → OpenAI → LM Studio → llama.cpp |
| Model tiers | Settings UI → `tiers` in `config.json` | `fast` defaults to llama.cpp on `http://127.0.0.1:8089/v1`; a tier that is down still falls through the normal order |
| Ports | `BUZZCAF_PORT` (default 8099) and `BUZZCAF_DEV_PORT` (default 5173) in `.env` | 8000 is avoided on purpose (other local apps use it). If a port is busy the launcher steps forward: the backend port is written to `backend/config/studio.runtime.json`; in `--dev` Vite is pinned to the chosen port (`--strictPort`) and the window opens only once `/health` through that Vite's proxy answers as the Studio |
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

- **Voice.** Removed in v5 (dictation, Jarvis, cloning). `git show pre-v5:...`
  has the old code; `backend/projects/voice_profiles` is left on disk.
- **Authentication.** None. The app binds to `127.0.0.1` and is single-user.
- **Database.** None. All state is JSON on disk under `backend/projects` and
  `backend/knowledge`.
- **Streaming chat.** Replies arrive whole; see `PLAN.md` 5.5.

## Channel brands

1. **Originals ✍️** — original stories, fiction & analysis (formerly Spilled Coffee Studio).
2. **Raat3Baje 👻** — folklore, 3 AM encounters, regional horror (formerly After Dark).
3. **Beyond3Baje 🔍** — fact-grounded documentaries, true crime, dark history.
4. **Life3Baje 🌿** — reflective personal essays and atmospheric video essays.
5. **Khayal3Baje 👁️** — fictional horror and speculative narrative.

Content is authored in Hinglish (conversational Hindi in Roman script) — the
channel guides under `backend/prompts/channels/` define each brand's voice.

## License

`LICENSE` is currently a placeholder. Treat this repository as all rights
reserved until it is filled in.
