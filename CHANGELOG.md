# Changelog

Notable changes to Buzzcaf AI Studio. Newest first.

## Unreleased

### Model routing (day / night), the night's forecast, Gemma with its whole context (2026-10-26)

- **Model Routing window** (Dashboard -> Tonight's run, or Settings -> Model Tiers): per kind of work -- research, script, rewrites, Shorts, SEO, plans, strategist, chat -- Auto / Claude / Gemma / Ollama / Gemini, a Claude model and a fallback, separately for **Day** and **Night** (`job_routes`, `job_routes_night`, `night_hours` 22:00-09:00). The nightly run always uses Night: Gemma writes the scripts and Shorts at night, Claude by day. A Gemma step that falls back to Claude gets Sonnet, not the default Haiku.
- **Gemma had 16k, not 64k.** LM Studio loaded it with 4 parallel slots, which split the context: "Context size has been exceeded" on prompts the Studio had sized for 64k. Every load now passes `--parallel 1`, and a model someone else loaded with more slots is reloaded once. A 27k-token prompt now answers in 17 s.
- **Tonight's run** panel on the Dashboard (`app/services/run_forecast.py`, `/api/forecast/*`): each slot's steps with the model that will answer and minutes (upper quartile of recent runs, slowest run as the worst case, Gemma timed from its own runs once there are any), when each video is ready, which ones Windows' time limit would cut off, Claude tokens for the night; pre-flight checks (models answering, Gemma's slots, master pause, the tasks' time limit, a stuck production, disk) with one-click fixes; and the run live -- slow steps, failed slots and a run whose process died. The nightly run writes the forecast and the failed checks at the top of its own log.
- **Usage record**: every model call -> `knowledge/usage/llm_calls.jsonl` (provider, model, job, step, tokens, seconds); the Claude proxy logs `[usage]` lines and `claudeAPI/logs/usage.jsonl`.
- **Nightly time limit 4 h -> 12 h** (`nightly_time_limit_hours`): on 2026-10-26 Windows killed the run at 07:00 with 1 of 8 videos done. The run lock now checks that its holder is alive, so a killed run no longer blocks the next one, and a waiting run waits as long as the limit.
- The Gemini harness is no longer retried after a timeout (each chat turn waited 4.5 min before falling back); Gemma is the selected provider again.

### Environments that work, not only exist; archive rules (2026-10-26)

- **The 9-hour stuck production**: BuzzEdit's Whisper could not load `cublas64_12.dll` (the venv rebuilt after the SmartCleaner wipe has no nvidia wheels; only torch's own folder has CUDA 12 / cuDNN 9, and only once torch is imported), fell back to the CPU and hung at 0 %; every Studio retry "joined" the dead job. BuzzEdit now registers torch's CUDA folder itself, and a job stuck in one stage for 110 min is failed with the reason instead of joined.
- **Self-tests** (`installer\selftest.*`, `app.json` `self_test`): BuzzEdit, and installers for the Studio's three services (claudeAPI, geminiApi, searxng; their `installed.json` keeps SmartCleaner away). Run at the end of every repair (a repair that does not pass is not finished), by BuzzEdit's launcher, by the nightly run for every app the night needs (`app_envs.ensure_working`: test -> repair -> test), and shown on Health and Tonight's run with a Fix button. `Ensure-NodeModules` checks with `npm ls` instead of timestamps (a needless `npm ci` with the proxy running deleted its packages half-way).
- **Dexter and Sentinel** get the same `installer\` repair + self-test + marker next to their own wizards. Dexter was broken (no `dist`, no `node_modules`, two packages missing): its repair restored all of it in 66 s, and Dexter now runs that repair itself when its launch preflight fails. Sentinel's self-test is read-only (service, pipe, `--verify`, tray); its repair starts the tray and needs Administrator for the service. The nightly run self-tests Sentinel too.
- **Archive rules** (`app/services/project_archive.py`, Projects -> Clean up): in progress and untouched 7 days, a failed step never retried for 2 days, an older copy of the same title after 1 day, a ready script never recorded after 21 days; Keep pins a project. The nightly sweep now runs on the 03:00 Shorts task -- it only ran when the whole nightly ran in one go, which the two Windows tasks never do.

### Local Gemma context overflow fix (2026-10-25)

LM Studio context defaults to 64k and grows to fit the prompt (max 131072); over-long prompts are compressed by `runtime/context_budget.py`, else `ContextTooLarge`. Local calls send `max_tokens` (8192).

### Studio Director v2 (2026-10-25)

The Director can troubleshoot and fix (guarded `fix_*` allowlist, `/api/director/diagnose`, nightly self-check), writes dev tickets instead of editing code, remembers the conversation, incidents and promises, and plans against the creator's mission (`knowledge/director/mission.md`). Backend: `director_fix.py`, `director_memory.py`.

### Installers for the sibling apps; ComfyUI workflows documented (2026-10-24)

A SmartCleaner "dev" cleanup (15:18) removed every app's `.venv`, `node_modules`
and Rust `target` under `Buzzcaf_Media`, and the Recycle Bin was emptied after,
so BuzzEdit could not start. `scripts/app_installer/` is now an in-place setup
wizard (Setup.cs / Uninstall.cs / `setup_common.ps1` / `build_installer.ps1`,
see its README) that BuzzEdit, BuzzAnimate, MastGaane, VrDeep, SmartCleaner,
BuzzViolin and buzzBooks each ship in `installer/`: it rebuilds the app's
environment with an idempotent `setup_env.ps1`, makes the Desktop and Start
Menu (Buzzcaf Media) shortcuts, registers the app in Settings > Apps and writes
`installer/installed.json`. SmartCleaner never offers dev folders under that
marker or under any registered InstallLocation. All seven environments were
rebuilt; BuzzEdit's (Python 3.11 + torch 2.11+cu128, narration on torch
2.7.1+cu128, seed-vc) also gained `librosa` in `requirements.txt` and
`torchvision`, which the old hand-grown venv had and the file did not list.
The Studio's own SearXNG `.venv` and `frontend/node_modules` were rebuilt by
hand (the Studio itself runs on system Python and was unaffected).

`docs/COMFYUI_WORKFLOWS.md` maps the Studio's features onto BuzzEdit's
workflow files; `BuzzEdit/workflows/README.md` documents every graph, its
models, folders and custom node packs, and the face swap -- the one graph code
composes -- is kept as a file in `BuzzEdit/workflows/reference/`
(`backend/tools/export_reference_graphs.py`).

Each of those seven `installer/app.json` files now also carries a
`health_paths` list; a Health page row with anything missing repairs that
app automatically (`app/services/app_envs.py`, `POST
/api/health/app_envs/{app}/repair`), the nightly run and
`ensure_buzzedit_running` repair BuzzEdit first instead of timing out against
a broken environment.

### Eye contact: BuzzEdit eye gaze v2 in the Studio (2026-10-24)

BuzzEdit's Auto mode now measures the lens from head + eye gaze (7.85° on the
2026-10-11 Raat3Baje take, where it used to find 2.4°), and `aim_deg` /
`pitch_deg` add on top of that measurement while `angle_deg > 0` overrides its
sideways size. Before v2 those three were silently ignored in Auto, and the
nudges saved then (and the Studio's own -10° aim / 15° angle defaults) made up
for a measurement that under-read about 3x; sent now they would overshoot. So
`STUDIO_DEFAULTS` is just `{"mode": "auto"}`, and in Auto the Studio drops a
project's aim / angle / up-down unless its setup has `nudges_v2: true`, which
saving any of them sets (the other pre-v2 nudges are cleared then). Manual mode
sends everything as before. New per-project `lens_marks` (seconds where the
speaker looks into the lens) go to BuzzEdit with every run, measure and
preview. Each preview clip keeps `lens_source`, `camera_look_candidates`,
`side_check`, the per-eye shift and its contact sheet (`contact_sheet_url`,
served as JPEG by `/api/eye_contact/file`). The production step redoes a
correction once when the stored result predates v2 (no `lens_source`). The
panel shows the lens source, measured angle and per-eye px, the candidate
looks with "Mark", the marks with remove, the contact sheet under each preview,
a mirrored-video note, the nudges as "on top of the measurement (0 =
measured)", and steadiness as "Calm the reading sweep".

### Auto Story: videos made end to end in the creator's own voice (overnight 2026-10-23)

The creator asked for an audio story channel in his voice (his face only at
the start, then his cloned voice narrating a story the agents found and
wrote, with sound and pictures, posted automatically), Instagram reels for
Raat3Baje (short horror, rules horror, SCP-style anomaly files, entity files,
all by the tool) and soothing mood reels for Life3Baje (ghazal lines over
slow scenes). Built overnight; the plan and contracts are
`AUTO_STORY_PLAN.md` and `REELS_DESK_PLAN.md`.

- **Narration in his voice, local and free** (BuzzEdit `engines/tts/`, its own
  Python 3.11 venv): Chatterbox Multilingual speaks Hindi and clones his
  voice from one 40 s reference (`data/voices/sudhansu.wav`); Kokoro is the
  fast fallback, converted to him by the seed-vc worker already in BuzzEdit.
  `POST /api/narration/synthesize` (a job; cues `(pause)`, `(beat)`,
  `(slow)` become silences and pace; sentence batches joined with
  crossfades; the GPU handed over and offloaded around it). Measured: 13.6 s
  of speech in 61 s. The `NarrationDirector` persona turns a script into
  what the engine reads: spoken words only, intonation cues placed, Hindi
  in Devanagari (the engine's own transliteration misspells).
- **The synthetic take** (`integrations/synthetic_take.py`): his face-intro
  clip (a path he sets per channel) followed by the narration over a dark
  still, 9:16 or 16:9, so the existing pipeline (transcribe, plan visuals,
  stills and Wan clips, render, Shorts delivery) runs unchanged with
  `face_layout = face_intro`; 0 s now means "no face at all".
- **The orchestrator** (`app/services/auto_story.py`, `/api/auto_story/*`):
  `make(channel, format, length, voice, publish, style)` writes the script
  with the Shorts desk (reels) or the long-form builder (long stories),
  narrates, builds the take, queues the production with the review gate off,
  watches it, publishes to YouTube when a channel is signed in and the
  switch is on, and always writes an **Instagram package** (vertical file,
  caption with hashtags, cover frame) since Instagram's API needs hosting
  and a paid business set-up; he posts from the phone. Watchers resume after
  a Studio restart; a running job now blocks the self-restart (it used to
  kill the job mid-narration). Nightly task `auto_story` with per-channel
  counts and the `StoryProducer` persona rotating formats.
- **Formats**: Raat3Baje reels from every Shorts format plus the new
  `anomaly_file`; Beyond3Baje `what_if` and `anomaly_file`; Life3Baje
  `mood_reel` (`app/services/mood_reel.py`: real public-domain ghazal lines
  from the Shorts desk, the `MoodReelPlanner` persona's portrait shots in
  one world, the lines read softly in his voice and shown as quote cards,
  an ACE-Step bed from the planner's mood, 15/30/45 s). A new **painterly**
  art style (soft oil / gouache) in both apps for the illustration version.
- **The Story Desk** (tab `story_desk`, `pages/StoryDesk.tsx`): channel,
  format, length, voice, style, face-intro clip, publish switch, "Make one
  now" with live steps, the nightly panel, and the records with their
  packages.
- **The Story Library** (§7 of the plan; the creator at 01:35): horror by
  real writers in any language, found on Gutenberg, Wikisource, the
  Internet Archive and the web (`app/services/story_library.py`,
  `StoryScout`), the full text fetched, the author's death year checked on
  Wikidata: public domain in India when the author died before 1966,
  otherwise protected and usable as **inspiration only** (Narayan Dharap,
  d. 2008, is protected until 2069). Adaptation (`app/services/story_adapt.py`,
  workflow `raat3baje_adaptation`): `StoryAdapter` translates and transposes
  a public-domain story into modern Hinglish in his style, part by part
  with the long-script planner pinned off (a collection is split into its
  stories first: the fetched M. R. James book gives eight), then
  `HumanTouch` rewrites only where `writing_style.ai_tells()` flags
  machine-writing (balanced triads, "not X but Y", stock transitions,
  uniform sentence length, morals; a human paragraph scores 15, a machine
  one 94), twice at most, then Shorts Scripts and the recording script as
  for any episode. The Story Library panel on the Story Desk searches, shows
  the rights badge, adds to the library, picks a piece, parts x minutes,
  and "Adapt into my style".

### Beyond3Baje: What If stories and the Anomaly Files (2026-10-23)

The creator's new direction for Beyond3Baje: **"What If this happened to
you?"** second-person Hinglish psychological horror, and a sister series of
**SCP-style Anomaly Files** about original anomalies in India. A new persona,
`WhatIfWriter`, holds both blueprints (the six-beat 75-second Short, the
5-25 minute expansion with `[SFX]`/`[VISUAL]` cues and a worked example from
the creator's own reference script, and the anomaly-file report form), the
language matrix (70/30 Hinglish, no literary Hindi, no formal English), the
rationality trap, the uncanny-not-gore rule and the gut-punch ending. The
length is always a setting, never a guess: a length pick on the Shorts desk
("75 seconds", "2 minutes", "3 minutes", carried on each candidate to the
writer) or the project's target runtime, with the beats scaled to it.

Where it is wired: two Shorts desk formats for Beyond3Baje (`what_if`,
`anomaly_file`, each naming its writer; `build()` routes to a format's
writer); two long-form episode formats (`what_if`, `anomaly_file`) plus
`investigation` for the channel's existing pillars, so the Projects page
Format dropdown and the nightly rotation know them; a "What If stories"
and "The Anomaly Files" section in the channel guide; pillars 7 and 8 in the
strategist persona with delegation to the writer. 105 ideas from the
creator's Notion export are in the Topic Vault (`format: what_if`, category
by list, rank, potential/virality scores, the pilot picks marked `pilot`).
Two projects were filed ready to record at a 5-minute target: the first
detailed script written by the Studio (pilot 1, the CCTV that shows
tomorrow night) and the creator's own five-minute reference (the room that
vanishes when looked at).

### The three pending measurements ran (2026-10-22, BuzzEdit)

- **Batched Whisper**: 1.8x faster on 10 min of a real take (65 s vs 117 s)
  but only 82 % of the words agreed (bar 96 %), 68 words fewer. Kept
  sequential. The batched path in `asr/faster_whisper_engine.py` was also
  broken (faster-whisper 1.2 needs clip timestamps without VAD, in seconds,
  30 s each); it now hands the pipeline fixed 30 s windows.
- **SageAttention graphs**: same picture (frame diff 0.007) but slower on the
  RTX 5060 Ti: clip 313 s vs 232 s plain, stills 18 s vs 17 s. The check
  adopted them on the picture match alone; it now also requires them to be
  faster, and the plain graphs (`zimage_wan22_i2v_lite16`, `zimage1_esrgan`)
  are the selection again.
- **Editor bench, Raat3Baje ep2, single call**: Gemma 12B caught 25 % with
  87 s wrongly removed; Qwen 27B caught 47 % with 43 s; Opus 5.5 (earlier)
  72-75 % with 9-11 s. The cut decision stays on Claude until a fine-tuned
  local model beats it (`AUTO_CUT_FINETUNE_PLAN.md`).
- Tool fix: `bench_generation.run` no longer aborts the whole check when
  ComfyUI's HTTP goes quiet during a SageAttention kernel compile.

### Health that reports the silent failures (2026-10-22)

The Health tab is now one row per watchdog and service with its real state
and the last error in plain words (`app/services/health_checks.py`,
`GET /api/health/checks`, refreshed every minute): the self-restart watcher
(its last check error -- the str/Path slip that kept the Studio on old code
for 2.5 h would have been a red row), the idle offload (same), the named
background threads, BuzzEdit and ComfyUI through BuzzEdit's health, LM
Studio with the loaded context against the setting (a 16k Gemma is a
warning), Ollama, the Claude proxy, the GPU (memory held while nothing
runs is a warning), the production queue, the nightly tasks (Windows task
or in-Studio schedule), the last nightly run, SearXNG, the disks, YouTube
sign-in and the error lines of the last hour. `code_reload.status()` and
`idle_offload.status()` expose what the watchers saw; the idle check's
"unsure means busy" now logs at WARNING and is shown.

Found by the first run: a self-restart that lands between an edit under
`frontend/src` and its build used to show a modal "UI bundle is out of
date" box that blocked `launch_desktop` itself -- backend answering, no
window, no reload watcher, until someone clicked OK. The desktop now
rebuilds a stale bundle by itself (`BUZZCAF_AUTOBUILD`, default on) and
only logs when it cannot; the Health tab has a "UI bundle" row.

### Archived projects and the morning report (2026-10-22)

Projects have an **Archived** tab: an archive button on every card and in
the details panel (files kept, one click brings it back), and the nightly
run archives by itself every active project untouched for
`archive_after_days` (14) that is not in the production queue and not the
parent of a live session Short (`app/services/project_archive.py`,
`POST /api/projects/{id}/archive`, `/api/projects/archive/sweep`). The
first sweep put 30 three-week-old "Ready to record" projects away.

The nightly run also writes a morning report
(`app/services/nightly_report.py`, `knowledge/nightly/reports/<date>.md`,
`GET /api/nightly/report`): problems first, then the Shorts and long videos
it wrote with their scores and where they stopped, the viewer requests it
saved, what it archived, what is waiting for the creator, and whether the
PC hibernated. The Dashboard shows it as "Last night" with the headline,
the problems and the whole report on click, and says when no run has been
recorded for days.

### The Audience Desk: what viewers ask for, from the comments (2026-10-22)

A new tab, **Audience**, reads the comments under the creator's own videos
and under the biggest videos of the niche (YouTube search for each brand's
queries, plus competitor channels he names: Khooni Monday, Scary Pumpkin,
Maroon Files for Raat3Baje) and lists what the viewers are asking for --
story requests, open questions, their own encounters, complaints, what they
loved -- each with how many said it, how many liked those comments, how many
videos it came up under, the verbatim quotes and links to the videos. No
YouTube API key: yt-dlp lists uploads, searches and pulls the top comments
(`app/services/audience_desk.py`, `/api/audience/*`). The reading is done
by `AudienceResearcher` (rewritten from a template into a real persona) on
the local model, in batches, with a merge pass; a finding without a comment
behind it is dropped.

"Save to vault" makes a Topic Vault row (`source_type: viewer_requests`,
category Viewer request / question / encounter, `evidence` with the quotes
and videos, the links in `sources_used`) and the vault card shows "N viewers
asked · K videos". The nightly run (`nightly_run.py`, new `audience` task,
`--only audience`) reads every brand and puts the top few requests with two
or more mentions in the vault by itself; the Audience tab holds the switch,
the searches and the competitor list per brand.

Also fixed on the way: `topic_store.add_topic` gave an existing row a fresh
id on every re-add (a saved finding, a strategist's SAVE_TOPIC of a known
topic), which orphaned links to it; it now keeps the id and the first save
date.

### The Assistant shows what the strategist is doing (2026-10-22)

A Studio Assistant turn used to be one silent request: "X is thinking…"
for as long as the strategist wrote, delegated to three specialists and
looked things up on a local model, then everything at once. The creator
asked for updates and status as it happens. Each turn now carries a
`turn_id` the page makes up, and `app/services/chat_progress.py` records
what the turn is doing under it: the strategist writing (with how many
delegations it asked for), each `[INVOKE_AGENT]` specialist as it starts and
finishes (words back, or the error), each web search, page read, book/news/
archive lookup, vault save, video analysis, project creation and model
switch, each with its seconds. `GET /api/studio/chat_progress/{turn_id}`
serves the snapshot and every change is published on the event feed as
`chat_progress`; `agent_invoked` is now published as each delegation ends
instead of after the whole reply, and carries the `turn_id`.

The chat page polls the snapshot every 1.5 s while its request is open and
replaces the thinking line with a live bubble: the current step as the
headline, "1/3 delegations", the running clock, and the step list with
ticks, spinners and times. The finished reply keeps the list folded under a
"2 min 10 s · 3 delegations" line, a failed turn shows how far it got and a
**Retry** button sends the same message again. The request timeout went
from 5 to 30 minutes, since the bubble now shows the turn is alive.

Found on the way: the self-restart and the idle offload had been silently
blocked since 19:19 -- `idle_offload._nightly_running` joined
`KNOWLEDGE_DIR` (a str) with `/`, every check raised, and "unsure means
busy" kept the Studio on old code with its models loaded. Fixed
(`Path(KNOWLEDGE_DIR)`); the Studio was restarted once by hand onto it.

### Art style: real, explainer, stick figure or cartoon (2026-10-21)

Every video now has an **art style**, the medium its pictures, clips,
thumbnail scene and text cards are made in: `real` (cinematic photoreal, the
default), `explainer` (flat vector), `stick_figure` (black marker on white
paper) or `cartoon` (2D cel). It is picked per channel (Settings -> Channel
Profiles), per project (Projects -> Visuals -> Art style) or per saved topic
in the Topic Vault (carried into the project by Start project and by the
nightly run), and resolved like every other video setting
(`integrations/buzzedit_settings.py`, `integrations/art_style.py`).

The style reaches everyone who makes a picture: every workflow step's prompt
names it, the visual planner gets the medium's rules, the CharacterPlanner
writes each look in it, the ThumbnailSpecialist's scene is drawn in it, and
every `[broll:]`/`[video:]` prompt carries its look and its clip motion.
Explainer and stick figure bring the short text cards (popup, stat,
definition, chapter title, quote) back on a story channel, since numbers are
the point of those media; cartoon is pictures only. In a drawn style nobody
gets a real face swapped in. BuzzEdit's side is `presentation/art_style.py`:
the look stamped on every prompt instead of the genre's photographic words,
the thumbnail scene in the medium, the cards in the medium's fonts, and no
recreation grain on a drawing.

The vault also gained the creator's 20 ranked Beyond3Baje survival stories
(rank and potential/virality scores on each row).

### Eye contact: Auto mode, measured from the take, with a preview (2026-10-20)

The correction was invisible on the 2026-10-20 take (1.5 px per iris): the
"auto" side setting aimed at a modelled lens position, and the landmark model
under-reads the real angle by several times. The new **Auto** mode (default)
needs no geometry at all: the frames where the creator really looks into the
lens (an intro, a sign-off; 12% of that take) say where each iris sits then,
sideways and up/down, and every reading frame is moved exactly there
(`BuzzEdit eyecontact/plan.py` `measure_lens`; per-eye targets, the sweep
damped as before, the vertical capped where the warp folds). A take with no
such look falls back to the symmetric guess and says so. Manual (side, angle,
aim, up/down) stays under Advanced.

- BuzzEdit: `mode` on the eye-contact setup; `POST .../analyse` tracks and
  plans a take without rendering (cached landmarks every preview and the full
  run reuse) and returns the measured numbers; previews of a short clip use
  the whole take's measurement.
- Studio: `POST /api/projects/{id}/eye_contact/analyse` and `/preview`
  (three 6-second before/after pairs at 15%, 50% and 85% of the take, measured
  first in Auto), `GET /api/eye_contact/file` streams them from BuzzEdit's
  preview cache. The project panel: Auto / Manual, Measure, Preview with
  side-by-side players played in step and a flip view, the measured numbers
  in words, and the last run's numbers.
- A speaker who looks into the lens by lifting the head (the prompter below
  the lens, eyes neutral in the head: ep3 reads bowed 6.7 deg the whole way)
  is measured from those head-up frames too, and the eyes are raised by the
  bow (`head_raise_deg`); when the irises sit the same for reading and for
  the lens, the head decides which frames are reading. "Open large": a
  full-screen popup per moment, before/after side by side or flipping in one
  place, played in step, click on the eyes to zoom 3x.
- Measured on ep3: the eyes are 33 px wide, the irises move 0.7 px sideways
  and are raised 5.6 deg (about 1.3 px). That is the whole reach of an eye
  warp at this framing; the rest of the off-camera look is the head bow,
  which only the rig can fix (prompter text at lens height).
- **Re-render video** (`POST /api/projects/{id}/produce_video/rerender`, a
  button next to "Fix eye contact now" once a fix is applied): BuzzEdit renders
  the saved edit again from the corrected recording, through the queue's
  render stage, every picture and clip reused, and the final copy lands next
  to the recording like a fresh production.

### The finished video lands next to the recording (2026-10-20)

- When a production finishes, the rendered file is copied to its final place
  and Explorer opens on it. Settings -> Local Models -> "Save the final
  video": next to the recording it was made from (default; named after the
  recording with `_final`), one folder for every video, or left where
  BuzzEdit wrote it; the Explorer pop can be turned off. BuzzEdit's own render
  stays for re-renders and publishing. The project page shows the final path
  with "Open folder" (`POST /api/projects/{id}/produce_video/reveal`); the
  status and the `video_ready` event carry `final_output_path`.
- BuzzEdit got a shortcut installer of its own
  (`BuzzEdit/scripts/install_shortcuts.ps1`): Desktop and Start Menu
  shortcuts to `START_APP.vbs`, with an icon (`build/icon.ico`, also the tray
  icon). One click opens one window; a BuzzEdit backend the Studio already
  keeps alive is adopted, never doubled.

### One launcher in the root (2026-10-20)

`Buzzcaf Studio.exe` is the only way to start the Studio from the root: it
runs `pythonw backend/desktop_app.py` hidden, so one window and nothing else.
`installer\Buzzcaf Studio Setup.exe` installs in place (default folder = this
checkout, so BuzzEdit stays a sibling) and creates the Desktop and Start Menu
shortcuts to it. The developer launchers moved out of the way into `scripts/`
(`start_buzzcafai.bat --dev` for a console with Vite, `start_buzzcafai.sh` for
macOS/Linux, `Buzzcaf Studio.vbs` as the icon-less twin of the exe); their
paths resolve the root one level up.

### Production never dies with a busy BuzzEdit (2026-10-20)

The 2026-10-20 Raat3Baje run failed three times at "transcribe" with
"BuzzEdit no longer has the transcription job": each time, 30 minutes into
the transcription, BuzzEdit's event loop was blocked for ~70 s by the cut
verification's ffmpeg join, one health probe timed out, the keep-alive took
that for "not running", the watchdog in `launch_buzzedit_process` stopped a
headless BuzzEdit older than 180 s, and the fresh one had no job. 77 minutes,
the same 42-minute recording transcribed three times, nothing produced.

- **A busy BuzzEdit is never killed.** `_headless_buzzedit_starting` stops a
  BuzzEdit only when nothing of the Studio's is running on it, and it has not
  answered for 30 minutes (`BUZZEDIT_HUNG_AFTER_S`; the client remembers its
  last answer, `buzzedit_client.seconds_since_answer`). The keep-alive leaves a
  BuzzEdit whose process is alive alone, and only starts one when there is
  none. The idle offload holds a BuzzEdit that answers late, is transcribing,
  or has a Studio production on it.
- **Timeouts are not disappearance.** `wait_for_transcription` no longer
  counts read timeouts towards the unreachable grace (now 10 minutes, for
  refused connections only); a slow BuzzEdit is followed until the job moves,
  bounded by the stall ceiling.
- **The queue retries by itself.** A failed item goes back to the front of
  the line from its last checkpoint, up to `AUTO_RETRY_ATTEMPTS` (4) runs,
  60 s apart, before it stays failed. BuzzEdit steps get 5 attempts with
  longer backoff.
- **BuzzEdit checkpoints the transcription** (`asr/transcribe_checkpoint.py`):
  Whisper's words and the planned cut are saved next to the project as each
  phase finishes, keyed on the recording and settings, so a retry after a
  crash reuses them instead of transcribing again; the file goes once the
  project is saved. A second POST for a project already transcribing joins
  the running job instead of starting Whisper twice. The verification's
  ffmpeg join, the timeline rebuild, the coverage check and the project save
  run off the event loop, and the health probe no longer spawns ffprobe or
  calls ComfyUI on the loop, so status polls and health answer while
  BuzzEdit works.
- **ComfyUI is watched, not only its exit.** BuzzEdit's Electron already
  restarted a ComfyUI that crashed (three tries in ten minutes); now it also
  probes `/system_stats` every 30 s, stops and restarts a ComfyUI it owns
  that has not answered for 10 minutes, starts its own in place of an
  adopted one that went mute that long, and tries again after the give-up
  window instead of staying down until BuzzEdit is restarted
  (`electron/main.cjs`, `startComfyWatchdog`).
- **A Studio restart mid-run resumes the run.** An item found "running" when
  the queue loads goes back in line from its checkpoint (within the retry
  budget) instead of coming back failed; the startup kick runs it.
- **Failed planning windows get a second pass** after 30 s before the plan
  is written; only a window that fails twice is left out, so "every window
  failed" (which parks the run at a plan review) needs two failures in a row.
- **Errors that need the creator are final at once.** An exception with
  `retryable = False` (a Shorts-first session whose greeting was not found)
  is not retried four times.
- **The PC stays awake during a production** (`integrations/keep_awake.py`,
  `SetThreadExecutionState` held by the queue worker). Sentinel's own [power]
  rule is not bound by it.
- **Per-project production log.** Every status line, warning and error of a
  run is appended to `production/produce_log.jsonl` in the project folder
  with a timestamp, so a failure overnight can be read back in order.

### Teleprompter: hold-to-scroll and rebindable controls (2026-10-18)

- **Hold a button, the text moves; let go, it stops.** Left mouse scrolls up,
  right mouse scrolls down by default (Page Up / Page Down and the left /
  right arrows too), at "Hold speed" x the reading pace (0.5-5, default 1.5).
  A held button overrides auto-scroll while held and auto-scroll carries on
  when it is released; the reading line shows a "hold" badge.
- **Controls panel** (toolbar -> Controls): every action -- the two hold
  scrolls, play/pause, pace, text size, reverse, top -- can be bound to any
  mouse button, any key (`KeyboardEvent.code`) or any gamepad button, so a
  USB foot pedal, presenter remote or controller can drive it. "+ Add" waits
  for the next press; one input does one thing. Bindings and hold speed are
  saved with the other prompter prefs (`buzzcaf.teleprompter.v2`). Right-click
  and the mouse side buttons no longer open a menu or navigate inside the
  prompter.
- **Pen and touch too.** A Wacom pen's tip (`pen:0`) and side switch
  (`pen:2`, "right click" in the default Wacom mapping) are their own inputs,
  separate from the mouse, and bound by default to scroll down / scroll up;
  the side switch works while hovering, no need to touch the tablet. Touch is
  `touch:0`. ExpressKeys set to a keystroke in Wacom Center bind as keys.

### Two darker presets and a Theme Builder (2026-10-18)

- **Studio Dusk Deep** sits between Studio Dusk and Studio Dark (same soft
  lavender and rose accents); **Slate Deep** is Slate Midnight a step darker.
  Both are presets in `frontend/src/lib/theme.ts` + `studio.css`.
- **Theme Builder** (Settings -> Appearance, or the copy icon on any theme
  card): colour pickers for background, sidebar, cards, borders, text and the
  two accents (secondary and muted text optional), "Darker" / "Lighter" buttons
  that move all surfaces together, a live preview of the whole Studio, a
  contrast read-out, and Copy / Import JSON. `deriveTokens()` turns the seven
  colours into the full CSS variable set and writes it inline on `<html>`
  (`data-theme="custom"`). Saved themes live in `localStorage`
  (`buzzcaf_studio_custom_themes`), join the theme grid and the header
  switcher, and the pre-React script in `index.html` paints a saved custom
  theme from cached tokens so there is no flash on load.

### Shorts batch and Visual Plan: JSON from small local models (2026-10-18)

- **Why the 17 and 18 Oct Shorts batches built nothing.** On 16 Oct the
  selected provider and both model tiers were pointed at Ollama's
  `gemma4:e4b-it-qat`. That model answers a "reply with one JSON object" task
  with prose, a script or a Markdown plan, so `ShortsScout` picked nothing,
  `ViralityJudge` scored nothing ("nothing scored >= 60" on every channel) and
  `PromptEngineer` failed the Visual Plan step of the "Meri Dadi" video twice
  with "did not return valid JSON".
- **Routing restored.** `selected_provider` and the `strong` tier are back on
  LM Studio `google/gemma-4-12b`; the `fast` tier keeps the small Ollama model.
  The Ollama-only config is kept as `config/config.json.bak-ollama-e4b-2026-10-18`.
- **JSON mode on local servers** (`integrations/llm.py`): a call that requires
  JSON now sends `response_format: json_object` to LM Studio, Ollama and
  llama.cpp, and is made once more without it when the server answers 4xx.
- **The judge's reply is read in any shape** (`shorts_desk._score_list`): the
  `scores` list, one bare `{id, score}` object, a list, or candidates keyed by
  id.
- Preflight expects 110 personas, the number there are.

### Idle release of models, RAM and VRAM (2026-10-17)

- **Five idle minutes free everything the Studio holds**
  (`integrations/idle_offload.py`). The watcher now checks every 10 s, so the
  unload lands at 5:00-5:10 instead of up to 5:30.
- **The headless BuzzEdit the Studio started is stopped**, and with it its
  backend's RAM, Whisper and the ComfyUI it brought; the next use starts it
  again. Before, one started by opening a page (Music, the audio rack) stayed
  up until the Studio closed. It stays up, with only its models cleared, while
  `buzzedit_keep_alive` is on or BuzzEdit's queue has a job (asked again one
  idle window later). Nothing is unloaded while a nightly run holds its lock:
  it runs in its own process on the same servers and offloads when it ends.
- **Loads that bypassed the tracker are counted**: an explicit model load
  (`ensure_local_model_loaded`), the Agents Workbench chat, and every BuzzEdit
  use (`ensure_buzzedit_running`). BuzzEdit work also unloads LM Studio, which
  BuzzEdit's own passes use.
- **A skipped end-of-task offload is finished later**: when `offload_now`
  found other work or a BuzzEdit job running, its full unload was dropped and
  only what the Studio had marked was ever unloaded; the watcher now does it
  once that work ends.

### Recording sessions, face first, Raat3Baje formats, research-first SEO (2026-10-16)

- **Shorts first, then the long video.** Raat3Baje, Life3Baje and Beyond3Baje
  long videos are recorded in one session that opens with 3-4 Shorts. A new
  "Shorts Scripts" step (`ShortsWriter`, `shorts_set`, `when: shorts_first`)
  writes them; `script/recording_script.md` is the teleprompter's "Recording
  session". Production splits the take at the greeting
  (`app/services/session_split.py`): each Short becomes its own vertical
  project queued after the long video, and the Shorts are cut off the long
  edit on BuzzEdit. Channel default on the Long-form panel, project override
  on the Projects page; old projects are never split.
- **Face first or mixed.** `face_layout`: the old mixed layout, or only the
  creator's face for the first 30-180 s and then pictures and clips only.
  Toggle per channel and per project; BuzzEdit gained `face_intro_s`.
- **Raat3Baje formats.** Five in turn: rules, a real encounter told as a
  story, a fictional story, black magic (kala jadu), tantra -- each with its
  channel-guide section; pin the next one on the Long-form panel or set a
  project's own.
- **Research and SEO.** The research loop reads deeper (6 results, ~6,000
  characters a page, YouTube search, a second round for a thin dossier); the
  SEO step researches demand (YouTube autocomplete, ranking videos with
  views/day, the channel's own uploads) before it writes, and keeps the
  evidence and a virality score in the package.
- **Premium tier.** ResearchAgent, WriterAgent, ShortsWriter and
  SEOManagerAgent run on `premium` = Claude opus through the local proxy
  (Settings -> Model Tiers).

### v5 — Studio as a desktop app controlled by Dexter

- Tracking moved to `PLAN.md` + `PROGRESS.md`; `ECOSYSTEM.md` records ports,
  launch order and the Dexter→Studio control contract. `IMPROVEMENTS.md` is
  superseded.
- Tests run against a throwaway copy of `knowledge/` and `projects/`
  (`tests/conftest.py`); previously `test_memory_system` deleted every real
  session memory file on each run.
- `GET /api/projects` lists from `core.paths.PROJECTS_DIR` instead of a
  second path computed in `app/main.py`.
- **Desktop app.** `backend/desktop_app.py` (pywebview) + `Buzzcaf Studio.vbs`
  open the Studio in a native window with no console; `npm run build` writes
  straight into `backend/app/static`; `start_buzzcafai.bat --dev` is the
  one-console developer variant.
- **Voice removed** (dictation, Jarvis, cloning routes and UI).
- **Chat rebuilt.** `services/studio_chat.py` sends a real messages list:
  persona and roster once, channel guide, up to six *relevant* memories, the
  last eight turns. Hinglish applies only to content-producing workflow steps.
  Failures are HTTP 502, shown as toasts.
- **Chat is the landing tab.** `App.tsx` is a 193-line shell over
  `src/pages/*`; fabricated fallback projects/topics/video ideas and the four
  mock tabs are gone; every request goes through `services/api.ts`.
- **Control API for Dexter.** `GET /api/studio/state`, `POST /api/studio/chat`,
  `GET /api/studio/events` (SSE), `POST /api/projects/{id}/approve`; `/health`
  identifies the app.
- **BuzzBrain store.** `POST /api/buzzbrain/snapshot` and `GET /api/buzzbrain/*`;
  a video is "mine" only when its channel id is in `owner_channel_ids`.
- **Purge.** 26 dead trees, 128 stub files, the auth stub and `app/db` removed;
  `docs/` archived to `docs/legacy/`.

### v6 — Video intelligence

- **Analyze tab.** Paste a video or channel link: metrics against the channel's
  own median, most-replayed moments with the transcript at each peak, why it
  works, and a blueprint for our version on the selected channel. Backed by
  `services/video_intel.py` (yt-dlp, no API key) and `POST /api/video-intel/analyze`;
  results cached under `knowledge/video_intel/`; labelled numbers-only when no
  model answers.

### Earlier unreleased repair pass (tagged `pre-v5`)

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
