# Fable review of the overnight content systems (2026-10-24, 02:00)

The creator asked the Fable model to "add improvements and enhancements if needed and
cross-check each failure point". This is its review (read-only), with what was done.

## Open failure points

| # | Area | Sev | Evidence | How it fails | Fix | State |
|---|---|---|---|---|---|---|
| 1 | GPU sequencing | high | llm.py REEL_RENDER_WAIT_S=45 min; auto_story REEL_SLOT_WAIT_S=2 h | a long story reel (2-5 h) outlives the ceilings; Gemma loads beside Wan | wait while the reel's progress changes, give up only on a stall | **done 02:05** (llm.wait_for_reel_render: 40-min stall rule); slot wait still has its 2 h ceiling |
| 2 | GPU sequencing | high | buzzedit_client.vibe_reel_busy False on any exception | a slow BuzzEdit answer (GPU busy) opens the gate | timeout = busy | **done 02:05** (timeout -> busy, 30 s read) |
| 3 | GPU sequencing | high | BuzzEdit gpu_handover.prepare_for_phase ejects LM Studio unconditionally | a Studio LLM call mid-script is killed when BuzzEdit starts a narration/clip phase | one machine-wide GPU lease | open (enhancement 1) |
| 4 | GPU sequencing | medium | llm._defer_gpu_providers only reorders | a production render on ComfyUI gets no LLM wait | gate on any BuzzEdit render, same progress rule | open |
| 5 | GPU sequencing | medium | idle_offload._buzzedit_hold: scheduler jobs + transcription only | a reel/narration outside a Studio job: Studio kills headless BuzzEdit after 5 idle min | add reels busy + narration busy to the hold | **done 2026-10-24** (`_buzzedit_hold` also checks `vibe_reel_busy()`/`narration_busy()`; BuzzEdit `GET /api/narration/busy` added; the Studio's own `code_reload.busy_reason` and the voice-preview routes hold the same way) |
| 6 | Restarts | high | BuzzEdit electron/main.cjs watchdog quits when the Studio pid is gone | any Studio exit (crash, closed, reaper) kills BuzzEdit mid-job | watchdog asks BuzzEdit's busy_reason; a new Studio adopts the running BuzzEdit | **done 2026-10-24** (enhancement 4: BuzzEdit `GET /api/reload/busy` {busy, reason}; the watchdog polls it every 30s instead of quitting, hard cap 6h; `POST/GET /api/supervisor/parent` lets a new Studio adopt a running headless BuzzEdit instead of spawning one -- `produce_api.launch_buzzedit_process` adopts first; applies on BuzzEdit's next Electron app start) |
| 7 | Durability | high | reels.py / narration.py jobs in memory; auto_story follower raises on first 404 | any BuzzEdit restart loses the job | persist jobs; follower tolerates misses; skip shots on disk | **done 2026-10-24** (enhancement 2: `runtime/job_store.py` -- reel/narration jobs on disk under `data/jobs/<kind>/`, `GET .../jobs/{id}` answers from disk after a restart, a startup sweep fails anything left "queued"/"running" as "BuzzEdit restarted"; `_follow_vibe_job` tolerates connection errors/404 for up to 10 min before raising; the per-shot cache on disk was verified to already skip generation on a resubmit, no fix needed there) |
| 8 | Durability | high | auto_story resume_watchers covers queued/producing/publishing only | a Studio restart mid-reel leaves a stuck record; re-run re-narrates | startup sweep; narration reuse by hash | **done 2026-10-24** (enhancement 2: `resume_watchers` now sweeps every non-terminal record -- a vibe job BuzzEdit still reports running gets a fresh follower thread, anything else is marked failed "Studio restarted -- press Retry" with a Story Desk Retry button wired to it; `_run_reel` reuses narration by a (voice, style, text) hash the same way `run()` does, and persists `vibe_job_id` to disk before the long follow starts) |
| 9 | Long-form | medium | longform_nightly.run reads settings once | minutes changed after start ignored | re-read per slot | **done 2026-10-24** (`settings()` re-read for minutes/instructions right before each slot's plan/build; the status row shows the slot's own minutes) |
| 10 | Instagram | high | auto_story._instagram_tick posts any packaged reel when an account is enabled | breaks "ask before publishing" | approved_at/rejected_at; post approved only | **done 2026-10-24** (enhancement 3: `review: {state, at, reason}` on every record; `/approve`, `/reject`, `/regenerate`; the Instagram scheduler and `post_instagram(force=False)` and the YouTube auto-publish path all wait for "approved"; rejections logged to `knowledge/decisions/log.jsonl`; Dashboard "Needs you" + Story Desk Approve/Reject) |
| 11 | Instagram | low | exact HH:MM slot match; whole file in RAM | slot skipped after a slow tick; no upload resume | due-since rule; streamed resumable upload | **done 2026-10-24** (`_instagram_due`: `post_time <= now`, earliest overdue slot not yet fired today; the upload streams from disk in chunks and resumes from rupload's confirmed offset on a dropped connection) |
| 12 | Narration | medium | NarrationDirector output kept if >= 50% of input length | the voice says a different text than the script | >= 85% in-order word overlap else raw text | **done 2026-10-24** (`_in_order_overlap` on normalised words, Devanagari and Roman alike; the raw script narrates otherwise, logged; the directed attempt is always saved to `script/narration_directed.txt` for review) |
| 13 | Story reels | medium | story_reel MIN_ENTITY_SHOTS raised after TTS | reel fails after narration was spent | repair instead of raise | **done 02:08** |
| 14 | Reel render | medium | reel_portrait (FlashVSR) never measured; 3 attempts x 15 min per shot | unattended reel_hq at the VRAM edge; no night budget | measure; pick quality/shots from the night's budget | open (enhancement 5) |
| 15 | Mood reels | low | validate_plan checks banned words only | wrong time of day / AI-tell objects slip through | per-theme forbid list; multimodal contact-sheet review | open (enhancement 7) |
| 16 | Tests | medium | no restart-recovery / gate-timeout / watchdog / approval tests | cross-process timing failures recur silently | those tests + a nightly smoke reel | open (enhancement 9) |
| 17 | Restarts | high | BuzzEdit backend 31964: log froze at 02:39:16 right after "Code reload: ... reloading at the first idle moment"; port 8100 kept LISTEN but refused connections until it was stopped at 04:10 (backend.log 107 MB) | a hung BuzzEdit fails every reel/narration ("BuzzEdit is not reachable") and nothing restarts it; the 60 s exit backstop never fired | find why the exit/reload path hung (stdout pipe to Electron? logging lock? exit backstop thread); the Studio keepalive should treat "port open, /api/health failing > 5 min, not busy" as hung and restart BuzzEdit; rotate backend.log | open (found 04:10, worked around by stopping the hung process) |
| 18 | Services | high | 2026-10-24 ~10:40: ComfyUI (started detached at 00:18) was gone; BuzzEdit logged "ComfyUI is not reachable" every 27 s and the reel waited ~10 min at scene 2 even though its shots were cached | a dead ComfyUI stalls every reel (up to the 60-min ComfyUI wait) with nothing restarting it | BuzzEdit starts/repairs ComfyUI itself when unreachable (its comfy_repair + the Electron launcher's command), and a cached shot must not need ComfyUI at all; find why it exited (no kill found in either app's log) | open (restarted by hand 10:49) |

Verified closed by the review: the reel gates (with the ceiling caveat), Studio reload waiting on
BuzzEdit reels, BuzzEdit reload holding on narrations/reels/ComfyUI, free_idle_comfyui before an
LLM load, the story-reel word budget + shot count + 80-shot cap, Shorts JSON salvage + repair,
catalogue rights dates, the mood-reel fixes (same ghazal, India anchor, wrapped cards, posted
field, no AI music).

## Enhancements (Fable's priority order)

1. **One GPU lease for the whole PC** (llm / comfy / tts; file-backed + HTTP in both apps;
   heartbeat expiry) -- replaces the ad-hoc waits.
2. **Durable jobs and stage checkpoints in both apps** (BuzzEdit reel/narration jobs on disk;
   startup sweep; narration reuse by hash; shots on disk skipped).
3. **Approval gate + morning review queue** (Approve / Reject (reason) / Regenerate; schedulers
   post approved only; rejections feed the Director's rules).
4. **Electron watchdog respects BuzzEdit work; the Studio adopts a running BuzzEdit.**
5. **Night budget planner** (measured seconds per clip/still per quality; order: long-form
   scripts, Raat3Baje reel, Beyond3Baje, mood reels; downgrade or carry over).
6. **Fresh intro + cloned remainder for long videos** (design below).
7. **Quality gates before packaging** (multimodal contact-sheet review, narration WER check,
   caption spelling, LUFS/black frames).
8. **Morning report with one-click actions.**
9. **Real-run smoke reel before each batch** (1 shot, 10 s, standard; any failure stops the
   batch and reports).

## Fresh intro + cloned remainder (design)

Project setting `intro_mode=fresh_recording` (channel default, project override),
`intro_minutes` 2-4. The script step writes a marked INTRO block (fixed greeting, hook, "aaj ki
kahani...") to be said to camera and the rest as narration; NarrationDirector narrates the
remainder only. The teleprompter shows the INTRO block; he records it when he likes (the
recording watcher picks `<project>_intro.mp4`, or he drops it on the Story Desk); the project
waits in "needs your intro" and the morning report lists it. On arrival: Whisper + the
session-split matcher find his last spoken script sentence; narration starts from the next line
(nothing repeated or skipped, his improvisations kept). Intro is auto-cut, eye-contact fixed,
same audio preset as the narration, narration loudness matched to his intro. The synthetic take
joins intro + narration-over-pictures (face_intro_seconds = intro length), the first picture fades
in under his last sentence, a 0.6 s room-tone pause hides the voice change. The intro path, the
seam and the narration hash are stored on the project so a restart resumes without
re-synthesis. YouTube upload waits for approval.

## What the master pause must cover

A durable state read at every loop head in both apps (queue, Story Desk stages, long-form
steps/sections, research/SEO turns, Shorts batch items, Audience Desk, adaptation parts, the
Instagram/Shorts schedulers, BuzzEdit shots/segments/narration batches/presentation phases,
ComfyUI interrupt only on "now"); a checkpoint of whatever is in flight; memory released in order
(LM Studio, Ollama, ComfyUI /free, BuzzEdit in-process models, Studio offload) with RAM/VRAM
before/after; waits and watchers hold indefinitely under pause (no ceilings), idle_offload never
kills BuzzEdit while paused, a code reload during pause keeps checkpoints; pausing never quits
BuzzEdit; who paused and when, optional resume-at, never auto-resume otherwise; paused + idle may
sleep (Sentinel), resume re-checks GPU/servers; tests for every loop head and for real unloads.
