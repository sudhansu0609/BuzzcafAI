# Buzzcaf Studio — Progress Log

Running record of what has actually landed, newest first. Plan: `PLAN.md`.
A row is **done** only with the evidence that proves it. Nothing is marked done on intent.

## Status at a glance

| Item | Status | Evidence |
|---|---|---|
| 0.1 commit + `pre-v5` tag | ✅ done | 4 commits `a8bf90c..a32e0a3`, `git tag -l` → `pre-v5` (2026-09-06) |
| 0.3 PLAN.md / PROGRESS.md | ✅ done | this file |
| 0.4 ECOSYSTEM.md identical in both repos | ✅ done | `diff ECOSYSTEM.md ../dexter/ECOSYSTEM.md` empty |
| 0.5 test sandbox conftest | ✅ done | `pytest tests -q` → 136 passed; `md5sum backend/knowledge/*_memory.json` identical before/after; `main.py` now lists projects via `core.paths.PROJECTS_DIR` |
| 2.1 build into static mount | ✅ done | `vite.config.ts` `build.outDir: ../backend/app/static`; `npm run build` → `backend/app/static/index.html` refreshed (2026-09-06) |
| 2.2 desktop shell (**I2**) | ✅ done | `pythonw backend/desktop_app.py`: no new `conhost` (20 → 20), `/health` → `app:"buzzcaf"` after **4.0 s**, log `Window opening after 3.7s`, `<title>Buzzcaf Studio</title>` served at `/`, projects listed; attaches to an already-running backend instead of double-starting; `Buzzcaf Studio.vbs` + `start_buzzcafai.bat --dev`; `preflight.py` 7 ok |
| 2.3 voice removed | ✅ done | `voice_intent.py`, `voice_engine.py`, `/api/jarvis/voice`, `/api/voice/config`, clone routes, dictation tab, jarvis handlers, mic buttons gone; `grep -rni jarvis\|voice_intent\|webkitSpeech\|voice_engine backend/app frontend/src` empty; `pytest` 136 passed |
| 2.4 chat correctness | ✅ done | `services/studio_chat.py` builds persona (+roster once) + brand guide + ≤6 *relevant* memories + last 8 turns as messages; `LLMService.generate_chat`; `BaseAgent.execute_messages` (no Hinglish for chat, kept for workflow steps); `memory.retrieve(query=)`; full replies stored; 502 on failure; `tests/test_studio_chat.py` 9 tests, suite 145 passed |
| 2.5 chat is the front door (**I11**) | ✅ done | `App.tsx` rewritten as a shell over `src/pages/*` + `state/studio.tsx`; landing tab `studio_chat`; all requests via `apiFetch`/`services/api.ts`; `Toast`/`ConfirmDialog` replace 10 `alert()`/`confirm()`; no fabricated projects/topics; mock tabs removed; real `/health` badge; `tsc` + `vite build` green |
| 3.1 control API | ✅ done | `api/studio_api.py`: `GET /api/studio/state`, `POST /api/studio/chat`, `GET /api/studio/events` (SSE); `POST /api/projects/{id}/approve` (409 when nothing waits); events `project_created`/`step_started`/`step_completed`/`approval_needed`/`step_failed` published from create/execute; `/health` carries `app`+`version`; `tests/test_studio_api.py` 8 tests, suite 153 passed |
| 5.1 BuzzBrain store | ⬜ open | |
| 5.4 frontend split + stub purge | ⚠️ frontend half done | 96 one-line stub files under `src/` deleted, `router.tsx` gone, `App.tsx` 3595 → ~200 lines; backend stub purge and `docs/legacy` still open |
| 5.5 streaming (optional) | ⬜ open | |

## 2026-09-06

- Plan v5 adopted. The repair pass recorded in `IMPROVEMENTS.md` (paths,
  `json` import, masked settings, labelled fallbacks) was committed as four
  commits and tagged `pre-v5` so every v5 change is reversible.
