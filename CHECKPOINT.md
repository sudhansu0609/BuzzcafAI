# MidnightBuzz Voice Cloning — Working Checkpoint

## Status: WORKING ✓ (saved 2026-07-29)

### What's Running
| Server | Port | Purpose |
|---|---|---|
| XTTS Microservice | 8096 | Persistent XTTS v2 model, loaded once |
| Backend API | 8095 | FastAPI — `python -X utf8 -m uvicorn app.main:app --port 8095` |
| Frontend | 3005 | Vite dev — `npm run dev` |

### Key Files
- `backend/app/services/voice_engine.py` — TTS router, calls XTTS server or Edge-TTS fallback
- `backend/app/services/xtts_server.py` — Persistent XTTS v2 HTTP microservice on port 8096
- `backend/app/services/voice_cloning_worker.py` — Subprocess worker (backup only)
- `backend/app/main.py` — FastAPI app with lifespan that auto-starts XTTS server
- `frontend/src/pages/ai/AgentCreatorStudio.tsx` — UI with voice recording + cloning

### How to Start (Every Session)
```powershell
# Terminal 1 — XTTS Microservice (must start first, ~25s warmup)
cd "b:\youtubeProjects\Buzzcaf Media\MidnightBuzz\backend"
$env:PYTHONIOENCODING="utf-8"; .\voice_env\Scripts\python.exe -X utf8 app/services/xtts_server.py

# Terminal 2 — Backend
cd "b:\youtubeProjects\Buzzcaf Media\MidnightBuzz\backend"
$env:PYTHONIOENCODING="utf-8"; python -X utf8 -m uvicorn app.main:app --port 8095

# Terminal 3 — Frontend
cd "b:\youtubeProjects\Buzzcaf Media\MidnightBuzz\frontend"
npm run dev
```

### Bugs Fixed
1. **XTTS subprocess timeout** — was spawning new process per request (~25s load = timeout). Fixed with persistent microservice.
2. **Edge-TTS pitch crash** — `+0%` invalid format. Fixed to `+0Hz`.
3. **transformers v5 conflict** — F5-TTS upgraded transformers, breaking XTTS `BeamSearchScorer`. Downgraded to 4.57.6.
4. **Windows CP1252 emoji crash** — `✅` emoji in `print()` crashed the XTTS HTTP call. Fixed to `[OK]`.
5. **Reverted from F5-TTS** — F5-TTS was tested but proved too sensitive to background noise/accent hallucination on this specific audio, reverted back to stable XTTS v2 pipeline.
