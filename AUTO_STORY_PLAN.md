# Auto Story: videos made end to end by the tool, in the creator's voice

Status: planned and built overnight 2026-10-23 (the creator: "in the morning I
want all done"; "everything local, nothing paid"). Companion:
`REELS_DESK_PLAN.md` (the Instagram reels) -- this plan is the engine both use.
Update the Status column in §6 after every item.

## 1. What the creator asked for

1. **An audio story channel in his voice**: he shows his face only at the
   start; the rest is his cloned voice narrating a story the agents found and
   wrote, with sound effects, edited and **posted automatically**.
2. **Raat3Baje reels for Instagram**: short horror stories, rules horror,
   SCP-style anomaly files, entity files; script, pictures, video, audio all
   by the tool; narration generated in any voice and converted to his voice
   with the SkinWalker engine (seed-vc, already in BuzzEdit), good intonation.
3. **Life3Baje mood reels**: soothing hyper-realistic or painterly scenes with
   2-4 real ghazal lines and a bed, no voice (REELS_DESK_PLAN.md).
4. Agents and a Studio page for all of it, and a write-up.

## 2. The one idea that makes it cheap: the synthetic take

Every BuzzEdit production starts from a recording (transcribe -> plan visuals
-> stills and clips -> render). Instead of a recording-less render path, the
Studio **builds a take**: his face-intro clip (a saved clip of him, per
channel) followed by the narration audio over a dark still frame, in the
orientation the format needs. The existing pipeline then runs unchanged:
`face_layout = face_intro` keeps his face for the intro and pictures only
after it; auto-cut finds nothing to cut in a clean narration; the Short path
delivers the vertical file. Nothing in BuzzEdit's render changes.

```
topic/lines -> script (existing writers) -> spoken text
   -> narration.wav   (BuzzEdit /api/narration: TTS -> seed-vc to "sudhansu")
   -> take.mp4        (Studio synthetic_take: face intro + narration over a still)
   -> produce queue   (existing; review_mode none; vertical for reels)
   -> final file      -> publish (YouTube: existing uploader; Instagram: package)
```

## 3. Contracts (every brief builds against these; nothing else is shared)

### 3.1 BuzzEdit narration (brief N1) -- `backend/audio/narration.py`, `routes/narration.py`
- Engine: a local TTS in `engines/tts/.venv` (own Python 3.11; never the backend
  venv), run as a subprocess like seed-vc (`engines/tts/cli.py`: JSON progress
  on stderr, one JSON result on stdout, exit 2 = engine unavailable). The
  engine is whichever the R1 probe proved (`engines/tts/probe_tts.py`,
  `scratchpad/tts_probe/summary.json`); Kokoro is the fallback.
- `POST /api/narration/synthesize` `{text, language: "hi"|"en", voice: "sudhansu"|"<preset>"|"engine",
  style: {"exaggeration": 0.5, "pace": 1.0}, convert_to: "sudhansu"|null, out_dir?}`
  -> a job `{job_id, state: running|done|failed, message, result: {wav, seconds, duration_s, engine, converted}}`;
  `GET /api/narration/jobs/{id}`. Text may be Hinglish in Roman script: the
  engine step transliterates Hindi words to Devanagari (`indic-transliteration`
  or the engine's own handling), English words stay English; `(pause)`,
  `(pause 2s)`, `(beat)`, `(slow)` cues become silences / rate changes, never
  spoken. Long text is synthesised in sentence batches and joined with 60 ms
  crossfades.
- Voices: `GET /api/narration/voices` lists `data/voices/*.wav` (his is
  `sudhansu.wav`, written by the probe) and the engine's presets.
- GPU rule: synthesis refuses while a render runs, hands the GPU over first,
  offloads after (the seed-vc worker's pattern in `audio/voice_conversion.py`).

### 3.2 Studio synthetic take (brief S1) -- `backend/integrations/synthetic_take.py`
- `build_take(project, narration_wav, *, orientation: "landscape"|"vertical", face_intro_clip: Optional[str],
  still: Optional[str] = None, out_dir: Optional[str] = None) -> {"path", "duration_s", "face_intro_s", "orientation"}`
  with ffmpeg only: the intro clip scaled/padded to the frame (1920x1080 or
  1080x1920, 30 fps, AAC 48 kHz), then the narration over a still (a dark
  frame, or `still` when given) of exactly the narration's length; joined
  losslessly in order. Writes `<project>/recording/take_<stamp>.mp4` (the
  project's `recording_path`). No intro clip -> the take is the still only and
  `face_intro_s = 0`.
- `face_intro_clip_for(brand) -> Optional[str]`: config `channel_formats[brand]["face_intro_clip"]`
  (a path he sets on the page), validated to exist.

### 3.3 Studio orchestrator (brief S2) -- `backend/app/services/auto_story.py`, `app/api/auto_story_api.py`
- `run(project_id, *, voice="sudhansu", publish: bool, orientation, progress) -> record`:
  1. the project's spoken script (`writing_style.spoken_text` of its newest
     script asset; for a Short, `script/short_script.md`);
  2. BuzzEdit narration (3.1) with `convert_to=voice`; the wav is saved under
     `<project>/audio/narration.wav` and `metadata.narration = {...}`;
  3. the take (3.2) with the brand's face-intro clip;
  4. `produce_queue.enqueue(project_id, recording_path=take, settings_override={"face_layout": "face_intro",
     "face_intro_seconds": take.face_intro_s, "review_mode": "none"}, mode="record_first")` with
     `metadata.orientation = "vertical"` for reels (the queue's existing Short path);
  5. a watcher thread polls the item; on `ready` it publishes (3.4) and writes
     `metadata.auto_story = {state: "published"|"packaged"|"failed", final, posted: {...}}`.
  `GET /api/auto_story/{project_id}` returns that record; `POST /api/auto_story/{project_id}/run`
  starts it (a job like the Shorts desk's).
- `make(channel, format, length, *, voice, publish, style) -> project_id`: creates the project and
  the script with what exists -- Shorts formats through `shorts_desk.find` + `shorts_desk.build`
  (reels: what_if, anomaly_file, rules_horror, ghost_story, folklore_entity, horror_incident),
  long stories through `longform_nightly.build` -- then `run()`. The length is the format's length
  pick (reel) or `target_duration_minutes` (long).

### 3.4 Publishing (brief S2, same module)
- YouTube: `youtube_publish.upload(final, channel_id=channel_for_brand(brand), title, description, tags)`
  with the project's SEO package when it has one, else the Short package's title / caption /
  hashtags; `publish=False` or no signed-in channel -> skip, record why.
- Instagram: the Graph API needs a public video URL and a business token; nothing paid or hosted is
  used, so the tool writes an **Instagram package** instead: `<project>/publish/instagram/reel.mp4`
  (vertical), `caption.txt` (caption + hashtags), `cover.jpg`, and records
  `posted.instagram = "packaged"`. He posts from the phone; the package folder opens from the page.

### 3.5 Agents (brief A1) -- `backend/prompts/agents/`
- `NarrationDirector.md` (Writing): turns a script into narration text for the engine: Hinglish
  kept, hard words respelled for the engine, `(pause)`/`(beat)`/`(slow)` placed for intonation, one
  JSON `{text, notes}`; never changes the words' meaning.
- `MoodReelPlanner.md` (Production): 2-4 ghazal lines + mood -> N portrait shots in one world (no
  people, no camera words), each with `image_prompt`, `video_prompt`, `seconds`, and which line
  shows over it; JSON. Used by REELS_DESK_PLAN R3.
- `StoryProducer.md` (Production): the strategist-side persona that picks tonight's auto stories per
  channel (format rotation, what was posted, the vault's pilots) and writes the morning note.
- Each added to its department class in `app/departments/`.

### 3.6 Studio page (brief S3) -- `frontend/src/pages/StoryDesk.tsx`, tab `story_desk`
- Per channel: format (the channel's reel formats + "long story"), length, voice (his / engine
  presets), style (art style), face-intro clip path (saved to `channel_formats`), publish toggle
  (YouTube when signed in; Instagram package always), "Make one now" -> job with live progress
  (script, narration, take, production, publish), and a list of auto-story projects with state,
  final file, and "open package". Nightly: count per channel, time, on/off (`auto_story` settings),
  shown like the Shorts desk's nightly panel. Types in `lib/types.ts`, nav entry in `App.tsx`.

### 3.7 Nightly (brief S2) -- `nightly_run.run_tasks` task `auto_story`
- Settings `knowledge/auto_story/settings.json`: `{enabled, per_channel: {Raat3Baje: 1, Life3Baje: 1, Beyond3Baje: 0},
  formats: {Raat3Baje: ["rules_horror","ghost_story","anomaly_file","folklore_entity"], ...}, publish: false}`;
  rotates formats, runs `make()` per channel, waits for the queue, records to `settings.last` and
  the morning report (`nightly_report`: a "Made by itself" section).

## 4. Rules that hold
- Nothing paid: local TTS, local models, ffmpeg, the existing uploader. No cloud TTS, no hosted
  Instagram publishing.
- Copyright: generated or licensed beds only; public-domain poets for ghazal lines (the Shorts
  desk's rights check).
- Story channels stay pictures-only; no camera words in prompts; the fixed greeting opens a long
  video once (his face intro says it, or the narration does when there is no clip).
- GPU: one model at a time; synthesis and conversion go through BuzzEdit's GPU handover.
- A failure retries (TTS batch, take, enqueue) and never delivers a degraded result silently; the
  record says what happened.

## 5. Checkpoints tonight
1. R1 probe: an engine speaks Hinglish; seed-vc makes it his voice (listening files in the scratchpad).
2. N1 + S1 + S2 unit-tested; one Raat3Baje `rules_horror` reel made end to end (vertical file).
3. S3 page built; A1 personas registered.
4. One Life3Baje mood reel (REELS R3) if time allows; one long Raat3Baje audio story queued.
5. Write-up: this file's status, CHANGELOG, AGENTS.md, and the morning note.

## 6. Steps and status

| # | Brief | Delivers | Status |
|---|---|---|---|
| R1 | TTS probe (me) | engine choice, his reference voice, listening files | done 00:53: Chatterbox Multilingual (hi) clones his voice from data/voices/sudhansu.wav, ~33 s per 10 s of speech, load 100 s; Kokoro hm_omega 4 s per 16 s (+ seed-vc via SkinWalker's venv); files in scratchpad/tts_probe |
| N1 | BuzzEdit narration | `engines/tts/cli.py`, `audio/narration.py`, `routes/narration.py`, tests | done 01:45 (60 tests; real run: 13.6 s of his voice in 61 s; Devanagari now comes from NarrationDirector) |
| S1 | Synthetic take | `integrations/synthetic_take.py`, tests | done 00:55 (9 tests incl. a real ffmpeg vertical take) |
| S2 | Orchestrator + publish + nightly | `app/services/auto_story.py`, `app/api/auto_story_api.py`, nightly task, tests | done 01:20 (27 tests); gaps closed by me: anomaly_file on Raat3Baje, face_intro 0 s allowed, watchers resumed at startup |
| A1 | Personas | NarrationDirector, MoodReelPlanner, StoryProducer + departments | done 00:50 (96 tests) |
| S3 | Story Desk page | `pages/StoryDesk.tsx`, types, nav | done 01:10 (built; assumes voices + open_package routes, sent to S2) |
| E2E | One reel end to end | a vertical Raat3Baje reel in his voice, packaged | running 01:50 (rules_horror, 75 s) |
| W | Write-up | CHANGELOG, AGENTS.md, morning note | not started |


## 7. The Story Library: horror by real writers, adapted into his voice (added 01:40)

The creator (01:35): the strategist should find good horror stories by writers in
any language (Marathi: Narayan Dharap; English; others), convert them to modern
Hinglish, write the script in HIS style so it never reads as machine-written,
multi-part when long; he records, the pipeline produces; no copyright issues.

**Rights, enforced by the tool.** Indian law: an author's work is public domain
60 years after the year of death (died before 1966 as of 2026). Narayan Dharap
died in 2008 (protected until 2069), Ratnakar Matkari in 2020: their stories can
only be used as **inspiration** (idea, mechanic, fear), never translated or
closely retold. Public-domain horror is plentiful: M.R. James, Blackwood,
Bierce, Lovecraft, Le Fanu, E.F. Benson, W.W. Jacobs, Poe, Stoker, Tagore's
ghost stories, Hemendra Kumar Roy, Rajshekhar Basu, Devaki Nandan Khatri,
Manto, folklore everywhere. Every library entry carries `rights`:
`public_domain` (death year verified on Wikidata, free API) | `protected`
(inspired-by only) | `unknown` (treated as protected). Adaptation of a protected
text is refused unless "inspired" is chosen, and then nothing of the expression
is kept; the mode is recorded on the project.

| # | Brief | Delivers | Status |
|---|---|---|---|
| L1 | Story Library backend | `app/services/story_library.py` (Gutenberg / Wikisource / Internet Archive / web; full text; Wikidata death year -> rights; `knowledge/stories/library/<id>/`), `StoryScout` persona, `/api/stories/*` | done 02:05 (113 tests; M. R. James fetched, 45,404 words, public domain via Wikidata 1936) |
| L2 | Adaptation workflow | `StoryAdapter` + `HumanTouch` personas, `writing_style.ai_tells()` (human paragraph 15, machine 94), workflow `raat3baje_adaptation.json` (adaptation -> human touch x2 -> Shorts Scripts -> visual plan / SEO), `app/services/story_adapt.py`, `/api/stories/adapt*` | done 02:35 (113 tests): pieces from a collection (the James book splits into its 8 stories), part-by-part adaptation with the long-script path pinned off, two Human Touch passes |
| L3 | Story Library on the Story Desk | search (language, author, source), rights badges, add to library, pieces, parts x minutes, inspired-by, "Adapt into my style" -> project | done 02:25 (built) |
