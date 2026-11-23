# Studio Director and the master pause (2026-10-24)

The creator, 2026-10-24 night:
- "I want a master agent in the dashboard that can control each and every channel,
  Shorts, everything, and learns from my use ... the CEO or something that can
  orchestrate all this." Autonomy chosen: **(b) it makes content by itself but asks
  before publishing** (and before deleting or changing settings).
- "Make sure there is no memory crash; the models are offloaded properly before new
  models."
- "Make sure I can pause everything on master level and the models and memory are
  released, and then I can resume master and everything picks up from the last
  pause. This is important when I use different-purpose tools."

## Part 1: master pause / resume (build first)

One switch for the whole Studio + BuzzEdit + the model servers.

**Pause** (`POST /api/master/pause`, Dashboard button, Dexter, tray):
1. Nothing new starts: the production queue, Story Desk jobs, the long-form nightly
   run, story adaptations, the Shorts desk batch, the Audience Desk, the Instagram
   scheduler, the nightly Windows task's work, and outside runners that ask
   `GET /api/master/state` -- all hold.
2. Work in progress stops at the nearest safe point and keeps its checkpoint:
   an LLM workflow finishes its current call and holds before the next step; a
   BuzzEdit reel/production stops between shots/phases (finished shots and clips stay
   cached; a running ComfyUI clip is interrupted only if the pause is marked "now");
   narration finishes its current batch.
3. Memory is released: LM Studio `unload --all`, Ollama models unloaded, ComfyUI
   `/free` (models + memory), BuzzEdit's in-process models (Whisper, TTS, seed-vc)
   released, the Studio's own idle offload. The Dashboard shows RAM/VRAM before/after.
4. The pause is durable: a file records what was held and where (survives a restart
   of either app or the PC).

**Resume** (`POST /api/master/resume`): everything held continues from its checkpoint
(next workflow step, next shot, next queue item); models load again on first use.

### Built (2026-10-24)

- Studio: `app/services/master_control.py` (durable state at
  `backend/config/master_control.json`, gitignored) -- `pause(mode, reason, by,
  resume_at)`, `resume()`, `state()`, `is_paused()`, `wait_if_paused(where, say)`.
  API: `GET /api/master/state`, `POST /api/master/pause`, `POST
  /api/master/resume` (`app/api/master_api.py`).
- BuzzEdit mirrors it: `runtime/master_control.py` (state at
  `data/master_control.json`), `routes/master.py` on the same three paths;
  the Studio calls them through `BuzzEditClient.master_pause/resume/state`.
- Hold points (Studio): `produce_queue.checkpoint` (between its own
  import/transcribe/plan/finalize stages, not inside the render stage),
  `workflow.execute_next` (every step -- covers the long-form nightly run,
  story adaptations and every Story Desk script), `auto_story._step` (every
  phase of `run`/`_run_reel`/`make`/`make_mood_reel`, so before a vibe reel
  submits too), the Shorts daily scheduler and its per-channel/per-candidate
  loop, the Instagram scheduler tick, `audience_desk.run_all` (per brand),
  `longform_nightly.run` (per slot), `nightly_run.py` (before each task, and
  in `hibernate_decision`), `research_loop.run` and `seo_research._loop`
  (between turns), `long_script.write` (between sections, after the
  checkpoint file is read).
- Hold points (BuzzEdit): the vibe reel's per-shot loop
  (`presentation/vibe_reel.py`, async), narration's job runner
  (`audio/narration.py`, before synthesis starts -- the TTS CLI's own
  internal batches are not individually checkpointed), the scheduler's own
  `is_paused` flag (new jobs hold; the running one finishes).
- Release on pause: Studio reuses `idle_offload.offload_now` (LM Studio,
  Ollama, ComfyUI; it already defers rather than unloading mid-call) and
  calls BuzzEdit's pause, whose own release is
  `runtime.gpu_handover.offload_all` (LM Studio, Ollama, the in-process
  ASR/aligner, ComfyUI `/free`). `now` mode additionally calls ComfyUI
  `/interrupt` directly on BuzzEdit; a shot interrupted that way is retried
  (not failed) once the pause lifts.
- Never gives up while paused: `llm.wait_for_reel_render`'s 40-minute stall
  clock resets while the master pause is on; `idle_offload`'s idle watcher
  never stops the headless BuzzEdit while paused (only its models); a code
  reload (either app) treats anything in `master_control.held()` as busy.
  Pausing never quits BuzzEdit -- only the scheduler flag and the release.
  Who paused and when is recorded (`by`, `since`); `resume_at` is accepted
  and shown but nothing acts on it -- there is no auto-resume.
- UI: a header badge (`MasterBadge`) and a Dashboard card (`MasterPanel`,
  `frontend/src/components/MasterControl.tsx`) with mode/reason, held
  items, RAM/VRAM free; a Health row (`check_master_pause`).
- Known gaps: narration is held per job, not per internal TTS batch (the
  CLI owns those); a chained shot's own segments are not individually held,
  only the shot boundary; outside scratchpad runners are not touched by
  this change -- they should poll `GET /api/master/state` themselves.

### Durable jobs and restart survival (Fable review rows 5-8, enhancements 2/4; 2026-10-24)

Built on top of Part 1 without touching its hold points: BuzzEdit's vibe-reel
and narration jobs now live at `data/jobs/<kind>/<job_id>.json`
(`runtime/job_store.py`), so `GET /api/reels/jobs/{id}` and
`GET /api/narration/jobs/{id}` answer from disk after a restart, and a
startup sweep marks anything still "queued"/"running" on disk `failed`
("BuzzEdit restarted") rather than leaving it to be polled forever; the
per-shot cache on disk already skipped regeneration on a resubmit (verified,
no fix needed). BuzzEdit's `GET /api/reload/busy` mirrors `code_reload.
busy_reason` for the Electron watchdog, which now polls it every 30s instead
of quitting the instant its Studio pid is gone (hard cap 6h), and
`POST/GET /api/supervisor/parent` lets a *new* Studio adopt a running
headless BuzzEdit (`produce_api.launch_buzzedit_process`) instead of
spawning a second one -- the watchdog change applies on BuzzEdit's next
Electron app start. On the Studio side: `idle_offload._buzzedit_hold` and
`code_reload.busy_reason` also hold for a BuzzEdit reel/narration busy;
`auto_story._follow_vibe_job` tolerates a BuzzEdit restart's own downtime
(connection errors/404) for up to 10 minutes instead of raising on the first
miss; `resume_watchers` sweeps every non-terminal auto-story record, not
only queued/producing/publishing -- a vibe job BuzzEdit still reports
running gets a fresh follower thread, anything else is marked failed
"Studio restarted -- press Retry" (Story Desk Retry button wired to
`POST /{id}/run`); `_run_reel` reuses narration by a (voice, style, text)
hash the same way `run()` does, and persists `vibe_job_id` to disk before
the long follow starts.

## Part 2: memory safety (continuous)

- Before any model loads: the other LLMs are unloaded (exists) and an idle ComfyUI is
  asked to free its cached models (added 2026-10-24, `llm.free_idle_comfyui`).
- A local LLM call waits while BuzzEdit renders a reel (added 2026-10-23); a reel waits
  for the previous one (added); the Studio never restarts onto new code while BuzzEdit
  renders (added 2026-10-24).
- Watchdog: when free RAM < 4 GB or VRAM is over-committed while idle, free ComfyUI /
  unload idle models, and log it to the Health page.

## Part 3: Studio Director (the master agent)

A persona + service + Dashboard panel: sees every channel and job, plans the day/week,
acts through the Studio's own actions (make reels/scripts/Shorts, queue productions,
retry failures, set nightly counts), asks before publishing/deleting/settings, learns
from what the creator approves, rejects, edits and posts, and writes a morning briefing.
Built after Part 1 (it uses the pause/resume API and the GPU rules).

## Status

| # | Item | State |
|---|---|---|
| P1 | Master pause/resume (Studio + BuzzEdit + model servers), durable, Dashboard button | built 2026-10-24 |
| P1b | Durable jobs + restart survival (Fable review rows 5-8, enhancements 2/4) | built 2026-10-24 |
| P2 | Memory watchdog + free-before-load (free-before-load done) | partly done |
| D1 | Studio Director: persona, state snapshot, planner, action loop with approval gate | built 2026-10-24 |
| D2 | Learning from use: decision log -> per-channel rules | built 2026-10-24 |
| D3 | Dashboard panel + morning briefing | built 2026-10-24 |
| Part 4 | Director v2: troubleshoot + safe fixes, dev tickets, memory, the creator's mission (backend; status in docs/DIRECTOR_V2_STATUS.md) | built 2026-10-25 |

### Built (2026-10-24, Part 3)

- Persona `backend/prompts/agents/StudioDirector.md` (Executive Office,
  `model_tier: strong`), added to `ExecutiveDepartment`'s specialist roles.
- `app/services/studio_director.py`: `snapshot()`, `plan(horizon)` (the
  unattended strategist tool loop over the snapshot and the learned rules,
  stored at `knowledge/director/plans/<date>.json`), `act(plan)` (the eight
  MAKE actions run one at a time; anything else becomes an approval request
  at `knowledge/director/approvals.jsonl`; approving runs it; holds on the
  master pause throughout), `learn()` (the decision log, the Director's own
  approvals, Auto Story records and Audience Desk findings -> per-channel
  rules at `knowledge/director/rules.md`, preserving a hand-written
  `## Creator's rules` section and `## From conversation` notes verbatim),
  `briefing(date)` (the morning markdown at
  `knowledge/director/briefings/<date>.md`), `ask(message)` (a chat turn;
  `[RULE: Channel] ... [/RULE]` in a reply is kept under "From
  conversation").
- API `app/api/director_api.py`, `/api/director/*`. A `director` task in
  `nightly_run.py` after the nightly batch: learn -> briefing -> tomorrow's
  plan, acting on MAKE items only when the `director_autoplan` setting
  ("Auto-plan nightly" on the Dashboard) is on -- off by default.
- Dashboard panel `frontend/src/components/DirectorPanel.tsx`: the
  briefing, today's plan, pending approvals (Approve/Decline), a chat box,
  the learned rules with an editable "Creator's rules" box, and the
  "Auto-plan nightly" toggle.
- Tests: `backend/tests/test_studio_director.py`.
- Known gaps: `act()`'s approval executor only has real handlers for
  `auto_story_approve/reject`, `publish_youtube` and `post_instagram` --
  a generic settings change, a nightly scheduler on/off and deleting a
  project have no safe existing primitive to call yet and are refused with
  a clear error on approval rather than guessed at (STUDIO_DIRECTOR_PLAN.md
  D1 follow-up). The "needs your intro" item is Director-side bookkeeping
  only; the fresh-intro production path itself (FABLE_REVIEW_2026-10-24.md
  enhancement 6) is not built.
