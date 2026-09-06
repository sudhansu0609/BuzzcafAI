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

## Not doing

- Voice (any form) until text chat, memory and control are solid.
- Deleting the `MidnightBuzz` sibling folder (owner's call; references are removed instead).
- Authentication: single-user, loopback only. Dexter's per-run token model can be copied later if the bind ever changes.
