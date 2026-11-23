# Agents

111 agent personas across 13 departments, each defined as one Markdown file in
`backend/prompts/agents/`. They are data, not code — adding an agent means
adding a file. This is the project's strongest asset; keep it that way.

> v9 merged ten duplicate personas (`Editor` into `EditorAgent`, `SEOSpecialist`
> into `SEOManagerAgent`, `PublishingScheduleManager`/`SchedulerAgent` into
> `ScheduleManager`, and the `*Analyzer` twins into their `*Analyst` originals)
> and folded the `"X Department"` namespaces into `"X"`, so the departments in
> the frontmatter now match the classes in `backend/app/departments/`
> one-for-one. 115 → 105, 19 → 13.

---

## File format

`backend/prompts/agents/<Name>.md`. The filename stem **must** match the
frontmatter `name`, because `BaseAgent._load_system_prompt()` looks the file up
by agent name.

```markdown
---
name: "ResearchAgent"
department: "Research"
role: "Gathers background information, verifies historical facts and timelines,
       and lists reference sources."
inputs: ["project_idea_summary"]
outputs: ["research_package"]
dependencies: []
permissions: ["read_knowledge", "write_project_assets"]
version: "1.0.0"
model_tier: "strong"
temperature: 0.7
---

# Agent Prompt: Research Department (ResearchAgent)

## Role
You are the Lead Researcher at Buzzcaf Media.

## Mission
...

## Responsibilities
1. ...
```

Everything below the frontmatter is the system prompt, sent verbatim to the
model. Everything in the frontmatter is metadata used by the registry.

| Field | Required | Meaning |
|---|---|---|
| `name` | **yes** | Registry key and prompt filename. Without it the file is skipped entirely |
| `department` | no | Grouping label, defaults to `"General"`. Should be one of the 13 department names |
| `role` | no | One-line description shown in the UI |
| `inputs` / `outputs` | no | Asset types consumed and produced |
| `dependencies` | no | Other agent names; validated after all agents load |
| `permissions` | no | Declarative labels — **not enforced by any code** |
| `version` | no | Defaults to `"1.0.0"` |
| `model_tier` | no | `fast`, `strong` or `premium`; anything else becomes `strong` (the default) |
| `temperature` | no | 0–2, defaults to `0.7`; reaches the provider payload |

List fields accept a real YAML list or a bracketed string; both are normalised.

### Model tiers (v9)

`model_tier` decides which provider is tried **first** for that persona.
Settings map each tier to a provider and an optional model override
(`tiers: {fast: {provider, model}, strong: {provider, model}}`, default
`fast → llamacpp` on `http://127.0.0.1:8089/v1`). If the tier's provider is
down, the normal fallback order (selected provider, then Gemini → OpenAI →
LM Studio → llama.cpp) still applies, so a tier can never strand a call.

LM Studio models are loaded by the Studio itself, with
`lm_studio_context_length` tokens of context (32k by default; grown to fit the prompt, up to `lm_studio_max_context_length` = 65536 since 2026-11-23 -- 131072 cost ~10 GB of RAM, inside the single-slot gate): a model that is
not in memory is loaded through `lms load -c` before the call, because LM
Studio's own just-in-time load (what happens after every idle unload) uses its
default (16k for Gemma), which a full script's visual plan does not fit. A prompt over the maximum is compressed in order (`runtime/context_budget.py`): the persistent-memory section, old tool results, older assistant replies, then input assets; the last user message is never touched. If it still does not fit, `ContextTooLarge` fails that provider (never simulated text). Local calls send `max_tokens` = `local_max_output_tokens` (8192). A
"prompt exceeds the context" refusal from a model loaded smaller than the
setting reloads it at the setting and retries once.

`fast` is currently declared by `TagGenerator`, `TitleGenerator`,
`DescriptionWriter`, `MetadataOptimizer`, `PublishingChecklist`,
`TaxonomyManager` and `CitationArchivist`. `premium` (2026-10-16) is declared
by the four personas whose quality decides a video -- `ResearchAgent`,
`WriterAgent`, `ShortsWriter` and `SEOManagerAgent` -- and defaults to Claude
`opus` through the local proxy (`DEFAULT_TIERS` in `integrations/llm.py`;
Settings -> Model Tiers changes it). With the proxy down or keyless the call
falls through to the selected provider like any tier. Everything else runs
`strong`.

### Model routing: per job, day and night (2026-10-26)

On top of the tiers, `integrations/llm.py` routes by **job**: the workflow
engine names each step's job from its output asset (`job_for_asset`:
research, script, rewrite, shorts, seo, planning), the strategist loop runs as
`strategist` and the chats as `assistant` (`llm_job(...)`). A job with a route
(`job_routes`, edited on the Model Routing window) overrides the persona's
tier: its provider first, then its fallback, then the usual order. Night routes
(`job_routes_night`) apply inside `night_hours` and always in the nightly run's
process (`BUZZCAF_ROUTE_PROFILE=night`): Gemma writes the scripts at night,
Claude by day. Every call is recorded in `knowledge/usage/llm_calls.jsonl`
(`integrations/llm_usage.py`), which the nightly forecast
(`app/services/run_forecast.py`) reads back for its times and Claude tokens.

### Departments (v9)

`backend/app/departments/*.py` holds one class per department; together they
cover every registered persona exactly once (a test asserts the union equals the
registry). `GET /api/departments` lists them, and
`POST /api/departments/{name}/execute {task, role?}` runs the task on the
manager — or on a named specialist. A workflow step may put a department name in
`agent_role`; the engine resolves it to that department's manager.

## How loading works

1. `AgentRegistry.discover_agents()` (`backend/core/agent.py`) scans
   `backend/prompts/agents/*.md` at startup, parses frontmatter, validates each
   definition, and registers it under `name.lower()`. A file that fails to parse
   is logged and skipped — the rest still load.
2. Dependencies are checked in a second pass, once every agent is registered.
3. At execution time `BaseAgent._load_system_prompt()` reads
   `core.paths.AGENTS_DIR / "<AgentName>.md"` and uses the body as the system
   prompt. If the file is missing it logs a warning and falls back to a generic
   one-line prompt.

> That fallback is silent from the user's side: the agent still answers, just
> without its persona. If agents feel interchangeable, check the logs for
> `System prompt file for agent X not found` before looking anywhere else.

Strategist and lead roles (`CEO`, `COO`, `CreativeDirectorAgent`, or any name
containing "strategist") additionally get the full agent directory appended so
they can delegate. The counts in that roster come from the registry, so they
cannot go stale when a persona is added or merged.

## Adding an agent

1. Create `backend/prompts/agents/YourAgent.md` with the frontmatter above.
2. Restart the backend (discovery runs at startup).
3. Confirm it registered: `cd backend && python main.py list-agents`.
4. To use it in a pipeline, reference the name as `agent_role` in a workflow
   step under `backend/prompts/workflows/`.

## Execution and memory

`BaseAgent.execute()` accepts a `Context`, a dict, or a plain string. Before
calling the model it retrieves the six most recent memories for that agent and
appends them to the system prompt under **Persistent Agent Memory Context**.
After the call it saves a memory entry containing a 200-char task summary and a
300-char result snippet.

Memory lives in `backend/knowledge/agent_<name>_memory.json`, scoped per agent.
It grows on every execution — an agent with a long history carries a longer
prompt, so watch for drift in behavior over time.

## Delegation

An agent can hand work to another by emitting:

```
[INVOKE_AGENT: FactChecker]
Verify the 1923 timeline claims in the draft above.
[/INVOKE_AGENT]
```

`process_agent_invocations()` in `app/services/studio_chat.py` resolves those
blocks, runs the named agent on the caller's own `LLMService`, and splices the
result back into the transcript. Since v9 it also returns a record per block —
`{agent, task, output, simulated}` — which:

- comes back on the chat response as `invocations`, one card per delegation in
  the Studio Assistant;
- is visible while it runs (2026-10-22): the page sends a `turn_id` with the
  chat request and polls `GET /api/studio/chat_progress/{turn_id}`, which
  `app/services/chat_progress.py` fills with the strategist's own call, each
  delegation, lookup and tool as it starts and ends, with seconds; the live
  bubble shows the current step and the clock, and the finished reply keeps
  the list folded under its total time;
- publishes an `agent_invoked {agent, task_preview, simulated}` frame on
  `GET /api/studio/events`, so Dexter sees it;
- is stored in the specialist's own memory tagged `delegated`.

Limits: **three** delegations per reply (the rest are recorded `skipped: true`
and never run), and **depth 1** — tags inside a delegated output are stripped,
not executed. Workflow steps run the same pass on their output and append each
result under a `## Delegated: <Agent>` heading in the step's asset, recorded in
`StepExecution.delegations`. JSON assets are exempt, since a heading would break
the parse.

### Unattended strategists (the long-form scheduler)

The chat resolves a strategist's tags once and never shows it the results.
`app/services/strategist_runner.py` is the unattended version: a tool loop
(up to 8 turns, 6 calls per turn) where every tag in the reply is executed and
the results come back as the next user turn, until the strategist writes
`[FINAL_PLAN]{json}[/FINAL_PLAN]`. It accepts the chat's tags (all agents via
`INVOKE_AGENT`, web/book/news/archive search, vault, video/channel analysis,
project list/status, model list/status) plus `[IDEA_DUMP: Channel]` and
`[STUDIO_ACTION: name | {json}]` for every read action in the Dexter registry
and a short allowlist of safe writes. Settings, model switching, project
create/run/delete, renders and deletes are refused. The nightly long-form
planner (`app/services/longform_nightly.py`) uses it with the creator's
per-channel instructions; the plan's creative brief and those instructions are
stored on the project (`creative_brief`, `creator_instructions`) and the
workflow engine adds both to every step's prompt.

## The research step is a tool loop

A step whose output is `research` no longer runs as one call. `runtime/
research_loop.py` loops the researcher the way the unattended strategist
runs: each reply may carry `[WEB_SEARCH]`, `[WEB_FETCH]`, `[BOOK_SEARCH]`,
`[NEWS_SEARCH]` and `[ARCHIVE_SEARCH]` tags (6 per reply, 5 replies), the
tags are run, the results come back as the next user turn, and the loop ends
when the reply is the JSON dossier. A dossier written without a single search
is sent back once ("memory is not research"); prose to the end is kept
verbatim with every section recorded as missing, as before; an empty reply
fails the step instead of completing it with nothing (an empty local-model
reply now raises in `integrations/llm.py` too). The dossier gained a `story_material` part --
world, folklore, real details, story seeds, twists -- written to
`research/story_material.md`, which is what the story writers build on.
Every lookup is in the step log. With no model answering the chat the step
falls back to the single call, labelled simulated as before.

Depth (2026-10-16): a search returns six results and a fetched page ~6,000
characters (the chat's own tags stay short), `[YOUTUBE_SEARCH: query]` shows
what has already been made about the topic, up to 7 replies
(`research_max_turns`), and a dossier written without reading one page --
or without sources or story material -- is sent back once more. The persona
says how to research each Raat3Baje format: first-hand accounts fetched with
their reported core for a real encounter, the beliefs as people hold them
(never instructions) for black magic and tantra.

## The SEO step is research too

A step whose output is `seo_package` runs `runtime/seo_research.py`: before it
starts, the SEO manager is shown a demand snapshot (YouTube autocomplete for
the title, what ranks for it with views per day, the channel's own recent
uploads), and its replies may carry `[YT_SUGGEST: seed]`,
`[YOUTUBE_SEARCH: query]`, `[OWN_CHANNEL]`, `[WEB_SEARCH]`, `[WEB_FETCH]` and
`[NEWS_SEARCH]` (8 per reply, 5 replies). A package written without a single
lookup is sent back once. The package keeps its evidence (`research`: search
demand, competition, the gap, a timely angle, audience questions, a virality
score with why and risks) next to the titles (each with why), thumbnail text,
description, tags, hashtags and a pinned comment; `parse_seo_package` reads
the publish files from it as before.

## Auto Story: the Story Desk, narration in his voice, the Story Library

Built overnight 2026-10-23 (`AUTO_STORY_PLAN.md`, `REELS_DESK_PLAN.md`). A
video can now be made with no recording: the script is narrated by a local
text-to-speech engine cloned to the creator's voice (BuzzEdit
`/api/narration`), `integrations/synthetic_take.py` builds a take from his
face-intro clip plus the narration over a still, and the ordinary pipeline
produces it. `app/services/auto_story.py` runs the chain (script, narration,
take, queue, watch, publish or package) for reels and long stories; the Story
Desk tab drives it; the nightly task `auto_story` runs it by itself.

Personas added: `NarrationDirector` (Writing: spoken words only, intonation
cues, Hindi in Devanagari for the engine), `MoodReelPlanner` (Production:
2-4 ghazal lines -> portrait shots in one world), `StoryProducer`
(Production: the nightly picks and the morning note), `StoryScout` (Research:
finds horror by real writers in any language, never invents a URL),
`StoryAdapter` (Writing: translates and transposes a public-domain story into
Hinglish in his style, part by part; a protected author is inspiration only)
and `HumanTouch` (Writing: rewrites only where `writing_style.ai_tells()`
flags machine-writing). Workflow `raat3baje_adaptation` runs adaptation ->
human touch -> Shorts Scripts -> visual plan / SEO. Rights are decided by
`story_library.rights_for` (Wikidata death year; public domain in India when
the author died before 1966) and enforced by `story_adapt.adapt`.

A reel format (REELS_DESK_PLAN.md VR5) skips the take and the production
queue: `StoryReelPlanner` (Production) turns the recorded narration into a
shot plan -- continuous stills and clips in script order, one consistent
lead character -- that `app/services/story_reel.py` renders through
BuzzEdit's vibe-reel narration mode and packages for Instagram.

## The Audience Desk: the comments as research

`app/services/audience_desk.py` (2026-10-22) reads the comments under the
creator's own videos and under the niche's biggest videos (yt-dlp: each
brand's YouTube searches, the competitor channels named on the Audience tab;
no API key) and hands them to `AudienceResearcher` in batches of 70. The
persona returns findings -- `story_request`, `question`, `own_encounter`,
`complaint`, `praise` -- each with the ids of the comments that say so and
verbatim quotes; a finding with no comment behind it is dropped, batches are
merged by a second call, and each finding is scored by mentions, likes and
how many videos it came up under. Findings are kept under
`knowledge/audience/<Brand>/` and become vault rows (`source_type:
viewer_requests`, `evidence`) on request or, for the top few with two or
more mentions, in the nightly run (`nightly_run.py --only audience`).

## Recording sessions: the Shorts first, then the long video

For Raat3Baje, Life3Baje and Beyond3Baje a long video is recorded in one
sitting that opens with its 3-4 Shorts (`app/services/session_format.py`). The
channel default lives in config `channel_formats` (Scheduler Desk -> Long form,
"Every long video"); a project overrides it (`session_format`:
`shorts_first` / `long_only`, `session_shorts_count`: 3 or 4).

- **Writing.** The three workflows carry a "Shorts Scripts" step after the
  long script (`ShortsWriter`, output `shorts_set`, `"when": "shorts_first"`:
  a step with a `when` that does not hold is recorded as skipped). It writes
  `script/shorts.json` + `shorts.md` -- each Short one different moment of the
  episode, hook first, no greeting -- and `script/recording_script.md` puts
  the Shorts and the newest long script together in recording order (rewritten
  whenever either changes). The teleprompter offers it first.
- **Production.** A recording is split only when the session was planned:
  its Shorts were written, or the project was set to Shorts first (or given a
  split point) by hand -- a project from before sessions stays the long video
  only. After transcription `app/services/session_split.py` finds where the
  long video starts -- the creator's greeting, fuzzy-matched in the kept words
  with at least two of its "who" words (hello, doston, his name), else where
  the long script's first lines after the greeting are said, or
  `session_split_s` set by hand -- and each Short before it (by its script's
  opening, else the longest silence). In a session the greeting is moved to
  the long script's first line, since the split happens there. Each Short is cut out of
  the recording with ffmpeg (`<recording>_short<k>.mp4`, next to it), becomes
  its own `shorts_ready` project (`session_parent`, a vertical render) and is
  queued after the long video; the span before the greeting is cut off the
  long edit on BuzzEdit (`program/cut`, a manual cut a re-cut keeps). The
  record is `project.metadata["session_split"]`; a session whose greeting
  cannot be found stops with what to set.

## Face first or mixed

`face_layout` (channel default in `channel_formats`, project override in
`video_settings`): `mixed` -- the old way, his face between the pictures all
through by the Video / Images sliders -- or `face_intro`: only his face for
the first `face_intro_seconds` (30-180, default 90), then pictures and clips
only. Story and full-style channels alike are then timed by
`story_visuals.plan_timed_shots(face_intro_s=...)` (the cut lands on a pause
near the mark; a full-style script keeps its cards and prompts), BuzzEdit gets
`face_intro_s` (its own planner places nothing in the opening) and the
render's real coverage (`face_intro_render`), which the live sliders keep.
The writer is told the opening is said to camera.

## The art style

Every project has an `art_style` -- `real` (photoreal, default), `explainer`,
`stick_figure` or `cartoon` -- the medium its pictures, clips, thumbnail scene
and text cards are made in (`integrations/art_style.py`; BuzzEdit keeps the
same table in `presentation/art_style.py`). Picked per channel profile, per
project (`video_settings.art_style`) or per Topic Vault row. The workflow
engine adds "This video's art style" to every step's prompt, the visual plan
step gets the medium's planner rules, the CharacterPlanner's cast prompt gets
its cast direction, and the PromptEngineer, CharacterPlanner and
ThumbnailSpecialist personas say how to write for it. A drawn style keeps the
story-order and no-camera rules, swaps no real face in, and (explainer, stick
figure) keeps the short text cards on a story channel.

Two **mixes** (2026-10-27, `docs/MIXED_ART_STYLE_PLAN.md`) pick the medium per
shot instead: `mixed` (real ~50%, stick figure ~35%, maps & charts) and
`mixed_quirky` (illustrated ~45%, stick figure ~35%, real ~12%, more pop-up
numbers; for quirky documentaries). The planner writes `"art"` on every picture
beat, it travels as ` | art=...` and `story_visuals._picture` applies that
shot's look, motion and face rules and strips it; maps/charts/timelines are
kept on a story channel and timed like stills (`| seconds=N`, which BuzzEdit's
script parser honours). Shares live in `art_style.MIXES`: a new mix is a row.

## Raat3Baje episode formats

Five, in turn (`FORMAT_ROTATION` in `app/services/longform_nightly.py`):
rules horror -> a real encounter told as a story -> a fictional story -> a
black magic (kala jadu) story -> a tantra story. The nightly run takes the next
one (or the one pinned on the Long form panel, once); a project's own
`episode_format` (Projects page, "Format") reaches the researcher and the
writer through the engine. The channel guide has a section per format.

## Long scripts (30-90+ minutes)

A script step whose target runtime is above `long_script_threshold_minutes`
(config, default 12) does not ask the persona for the whole script in one reply.
`runtime/long_script.py` plans it first (a story bible -- characters, rules,
facts -- plus a section outline with word budgets), then writes one ~700-word
section per call, each carrying the bible, the outline, summaries of what is
written and the last lines verbatim. Short sections get a "continue" call and a
section that repeats earlier material is rewritten. Sections are checkpointed
under `script/sections/<asset>/`, so re-running a failed step resumes. Edit and
narration passes over a long script go in ~900-word parts, and a part the model
truncates keeps its original text. These calls use the persona's prompt without
its memory log. `long_script_mode`: `auto` (default), `always` or `off`.

The plan asks for a **layered story** (the bible carries `layers` -- surface,
beneath, truth -- plus `plants`, `escalation` and an earned `twist`), and one
extra call reviews it as a story editor and returns it strengthened in the
same shape (`long_script_plan_review`, default on; an unusable review keeps the
first plan). Every section after the first is told it begins inside the story,
and `once_opened()` cuts any greeting or opening line a section or rewrite part
still re-opens the video with (`writing_style.strip_repeated_intro`), so the
greeting is said once, in the opening, and never again.

Word budgets count **spoken** words only (`writing_style.narration_words`): cue
lines, speaker labels and `(pause)` marks are not runtime, so a 25-minute
target means 3,500 words that are actually said. In "my style" mode each
section and each rewritten part passes a `StyleGate`: it is scored against the
creator's style as it is written and rewritten once when it is below 75.

## Runtime-created agents

The Agents Workbench (`frontend/src/pages/ai/AgentCreatorStudio.tsx` →
`backend/app/api/agents_api.py`) is a **separate, simpler system**: agents are
JSON records with an inline `systemPrompt`, stored by
`app/services/agents_registry.py` and run against a local LM Studio / Ollama
model. They do not appear in `list-agents` and cannot be used in workflows.

Use the Markdown personas for production pipelines; use the Workbench for
throwaway experiments and group chat.

## The creator's own writing style

Channel guides say what a channel is about; `app/services/writing_style.py`
says how the creator himself writes and talks, per channel, so scripts sound
like him. It lives in `backend/knowledge/style/<Channel>/`:

| File | What |
|---|---|
| `samples/*.md` | his own writing, added on the **Writing Style** page (paste or upload) |
| `recordings/<project>.md` | what he actually said in a produced video, kept automatically after every production (speech-to-text) |
| `rewrites.json` | script line -> what he said instead, from the recording |
| `profile.md` | the style guide `StyleAnalyst` writes from all of it (Claude first); editable, replaced by Rebuild |
| `notes.md` | his own rules, always included, never overwritten; a `Never use: a, b` line is enforced |
| `fingerprint.json` | measured numbers: sentence length, short-sentence share, paragraph length, English share, Devanagari, '...', questions, viewer address, first-person share, stage-direction share, repeated phrases |

`style_section(brand)` -- "The Creator's Own Writing Style" -- is added to every
workflow step that writes words he will say (`script`, `story`, `script_final`,
`narration_optimized`, long scripts section by section), to the Shorts writer,
and to Studio Assistant writers. Every such step is then scored by
`check()`; below 75/100 the same agent rewrites it once toward his style and the
higher-scoring version is kept (long scripts section by section, as they are
written). The score is in the step log and `project.metadata["style_match"]`.
Writer personas carry a "Writing in the Creator's Own Style" section that tells
them how to use it: his fixed lines (greeting, story start, sign-off) word for
word, everything else as manner only.

**A guide is never older than his samples.** Adding a sample marks the profile
stale; `ensure_current()` rebuilds it before the next writing step (the nightly
run does too), and until it is rebuilt `style_section()` leaves the outdated
guide out and quotes his written samples instead.

**Format and point of view come from his written samples.** When they are
continuous narration (no cue lines or speaker labels: `narration_format()`),
the section carries a "Format" block, the step's task gets a format override,
and the long-script writer asks for narration paragraphs instead of the
`[VISUAL]`/`[SOUND]`/`NAME (V.O.)`/`(pause)` screenplay layout. `check()` marks
a screenplay down hard, and a third-person draft when he tells stories as
"main". A channel with recordings only keeps the cue format.

**The greeting is fixed, and said once** (`greeting()`): "Hello doston, mera
naam hai Sudhansu aur aap dekh rahe hain Raat 3 Baje." with the channel's own
name. It is in the section, and `ensure_greeting()` puts it into every full
script word for word: a greeting the writer reworded or borrowed from a sample
(another host or show) is replaced, a script without one gets it as its first
line, and every later greeting is removed together with the opening lines
around it (the "aaj ki kahani ... par aadharit hai" line, the subscribe
request, "toh chaliye ..."), since a sectioned script used to re-open the video
in every section. `check()` marks a draft down for greeting twice and for lines
copied word for word from his samples (`sample_copy_ratio`): the samples are
manner, never material. Shorts have none. A `Greeting: ...` line in
`notes.md` replaces the default.

**Saved styles.** A channel can keep several styles and writes in the selected
one. The first ("default") is the channel folder itself; the others live in
`<Channel>/styles/<id>/` with the same files (samples, recordings, profile,
notes, fingerprint). The selection and the styles' names are in the channel's
`state.json` (`style`, `styles`, `default_name`); `_dir()` resolves every read
and write to the selected style, so the section, the score, the rebuild and a
production's kept recording all follow it. The Writing Style page lists them
(select, new empty, save a copy, rename, delete — never the default);
`POST/PUT/DELETE /api/style/{channel}/styles...`.

**My style / Agent style.** Each channel has a default (`state.json` `mode`,
toggled on the Writing Style page) and a project may override it (Projects
page, `project.metadata["writing_style"]`: `mine`, `agent`, or absent for the
channel's). In "agent" mode no section is added and nothing is scored or
rewritten: agents write from the channel guide alone. Shorts and the Studio
Assistant follow the channel's mode.

Accuracy comes from his written samples: recordings teach phrasing, openings
and habits, but their sentence breaks are the recogniser's, so sentence
numbers come from written samples only.

## The Tall Storyteller

A sixth channel brand (2026-10-23, handle `@TheTallStoryteller`): narrated,
no-face storytelling across every genre -- folk tales, mystery, thriller,
history, mythology, adventure, emotional/drama, romance, comedy, classic
world and Indian literature retold -- mostly detective and comedy, sometimes
crime, never horror (creator rule 2026-10-24) -- told in the creator's
own cloned voice (`sudhansu_story`, mood `warm`) the way Auto Story narrates
Raat3Baje/Beyond3Baje Shorts: `integrations/synthetic_take` with
`face_layout: face_intro` and no seconds of face unless the creator sets his
own face-intro clip on the Story Desk. Everything that makes a channel real
to the rest of the Studio follows the same pattern as the other five:
`prompts/channels/TheTallStoryteller.md` (voice, genres, the hook/setup/
rising-stakes/turn/payoff story shape, pacing, what to avoid, Shorts
guidance), `TheTallStorytellerStrategist` (Research department), the
`thetallstoryteller_story` workflow (story research -> script -> Shorts
Scripts, when the project is set to a recorded session -> visual plan ->
SEO), and a seed Topic Vault file with ideas across all ten genre formats.

It is a **story channel** like Raat3Baje/Khayal3Baje/Beyond3Baje
(`visual_style: story` -- pictures and videos only, same characters, no
camera, calm storyboard order) chosen for the same reason they use it:
narrated world-building, not because it is horror (it never is horror:
mostly detective and comedy, sometimes crime, never horror, per the creator's
rule of 2026-10-24). Unlike them it is never
recorded as a session (`channel_formats` default: `long_only`, no
Shorts-first split) and carries no face at all, so `face_layout` defaults to
`face_intro` with `face_intro_seconds: 0` -- Auto Story's own synthetic-take
pipeline already treats 0 as "no face" for every channel; a project can still
give the channel its own face-intro clip.

The Shorts Desk / Story Desk gained ten genre formats
(`folk_tale`, `mystery`, `thriller`, `history`, `mythology`, `adventure`,
`emotional`, `classic_retold`, `comedy`, `horror_tale`) plus `long_story`, a
one-minute (60 second) reel length like the other channels' Shorts, and
long stories of 15-25 minutes (20 by default, the system-wide default
already). Auto Story's channel voice default is no longer a single
horror-only special case: `CHANNEL_VOICE_DEFAULTS` is a per-channel table
(Raat3Baje/Beyond3Baje unchanged at `sudhansu_horror` / `horror_narrator`;
TheTallStoryteller at `sudhansu_story` / `warm`). The channel starts at 0 in
Auto Story's `per_channel` and absent from the nightly run's
`longform_nightly_channels` -- wired in, but silent until the creator turns
it on. YouTube publishing stays off until he signs the channel in on the
Bulk Editor tab and assigns it the `TheTallStoryteller` brand (`channels.json`
only ever holds channels that have actually completed OAuth, so none was
added there sight-unseen; `brands()` already offers the name because the
channel guide file exists).

## Master pause / resume

One switch (docs/STUDIO_DIRECTOR_PLAN.md Part 1, 2026-10-24) holds every
automated job -- the production queue, the long-form nightly run, story
adaptations, every Story Desk script, the Shorts/Audience/Instagram
schedulers, the nightly Windows task, and BuzzEdit's scheduler and vibe-reel
renderer -- at its nearest safe point and releases every local model (LM
Studio, Ollama, ComfyUI, BuzzEdit's in-process ASR/TTS). `POST
/api/master/pause {mode: "soft"|"now", reason?, by?}` / `POST
/api/master/resume` / `GET /api/master/state`; BuzzEdit mirrors the same
three paths and the Studio calls them. State is a small gitignored file in
each app (`backend/config/master_control.json`, BuzzEdit's
`data/master_control.json`) so a pause survives a restart of either app.

Any agent persona or workflow step that drives a loop across multiple model
calls should call `app.services.master_control.wait_if_paused(where, say)`
(BuzzEdit: `runtime.master_control.wait_if_paused` /
`wait_if_paused_async`) between calls, the way `runtime/research_loop.py`,
`runtime/seo_research.py` and `runtime/long_script.py` already do -- it
blocks while paused and returns the moment `resume()` runs, so the loop just
continues from its own checkpoint. An outside script that is not part of
either app's process (a scheduled task, a one-off runner) should poll `GET
/api/master/state` instead and hold its own work while `paused` is true.

Nothing auto-resumes a pause -- only an explicit `POST /api/master/resume`
-- and who paused and when is recorded (`by`, `since`) for the Dashboard and
the Health page's "Master paused since ..." row.

## Studio Director

The master agent on the Dashboard (docs/STUDIO_DIRECTOR_PLAN.md Part 3,
2026-10-24): `StudioDirector` (Executive Office) plus
`app/services/studio_director.py`. Autonomy (b) -- it makes content by
itself but asks before publishing, deleting or changing a setting.

- `snapshot()` is one compact JSON view of the whole Studio: every channel's
  recent Auto Story records, needs-review items and failures with reasons,
  the long-form/Auto Story schedules, the production queue, the Topic
  Vault's top ideas, Audience Desk findings, Instagram/YouTube connection
  status, the master pause state and RAM/VRAM, and the health checks' own
  problem rows. Its first key, `right_now()` (2026-10-26), is live: the
  queue with each item's own `doing`/`progress_pct`, the voice being made,
  `needs_you` items, the pause, commit memory and VRAM, open promises and the
  latest incidents. The chat is told it wins over older records (a video in
  the queue is not "failed") and to lead with it when asked what is going on;
  it used to sit past the 6,000-character cut and was never seen.
- `plan(horizon)` runs the Director through the unattended strategist tool
  loop (`app/services/strategist_runner.py`, the same `[STUDIO_ACTION: ...]`
  registry every other unattended strategist uses) over that snapshot and
  the learned rules; the reply's `[FINAL_PLAN]{"items": [...]}[/FINAL_PLAN]`
  is stored at `knowledge/director/plans/<date>.json`. `needs_approval` on
  every item is recomputed here from the MAKE allowlist, never trusted from
  the model.
- `act(plan)` runs each item whose action is one of eight MAKE actions --
  `auto_story_make`, `auto_story_make_mood_reel`, `longform_run_slot`,
  `story_adapt_start`, `story_adapt_resume`, `produce_queue_add`,
  `retry_step`, `retry_record` -- one at a time through the existing
  services (they already sequence the GPU); everything else becomes an
  approval request (`knowledge/director/approvals.jsonl`); approving one
  runs it. Every hold point calls `master_control.wait_if_paused`, so the
  Director itself holds while the master pause is on. A long script (20+
  minutes) needing the creator's own on-camera intro is never finished
  without him -- it is planned as a `needs_intro` item instead of a MAKE
  action, and shows up on the briefing as "needs your intro."
- `learn()` reads `knowledge/decisions/log.jsonl` (the same log
  `auto_story.reject()` and the Director's own approvals write to), posts
  made and Audience Desk findings, and distils per-channel rules into
  `knowledge/director/rules.md` -- newest evidence first, each rule with its
  evidence count. A hand-written `## Creator's rules` section and anything
  the creator said in chat (kept under `## From conversation`) are carried
  over verbatim; `learn()` only ever rewrites `## Learned from use`.
- `briefing(date)` is the morning markdown (what was made, what failed and
  why, what needs him today, today's plan, the learned rules), kept at
  `knowledge/director/briefings/<date>.md`. `ask(message)` is a chat turn --
  a question is answered from the snapshot; an instruction ending
  `[RULE: Channel] ... [/RULE]` is remembered under "From conversation."
- API: `app/api/director_api.py`, `/api/director/*` (snapshot, plan, act,
  approvals + approve/decline, ask, briefing, learn, rules, settings). A
  `director` task in `nightly_run.py` runs after the nightly batch:
  learn -> briefing -> tomorrow's plan, and only acts on MAKE items when
  `director_autoplan` (the "Auto-plan nightly" toggle) is on -- off by
  default until the creator turns it on. The Dashboard's Studio Director
  panel (`frontend/src/components/DirectorPanel.tsx`) shows the briefing,
  the plan, pending approvals, a chat box, the learned rules with an
  editable "Creator's rules" box, and that toggle.
- **Troubleshoot and fix (v2, 2026-10-25).** `app/services/director_fix.py`
  holds a hard allowlist of `fix_*` actions. SAFE ones run by themselves
  behind a guard (`fix_restart_claude_proxy`, `fix_restart_gemini_harness`,
  `fix_start_searxng`, `fix_start_buzzedit`, `fix_repair_app_env`,
  `fix_offload_models`, `fix_kick_queue`); APPROVAL ones wait for him
  (`fix_set_config` with an Undo rollback, `fix_set_director_provider`,
  `fix_restart_record`, `fix_master_resume`). `[FIX: name | {json}]` in a chat
  reply, a plan item, or `POST /api/director/diagnose {problem}` (evidence ->
  hypotheses -> fixes -> re-check -> incident) all go through the same
  `run_fix`. Guard: never while the master pause is on, a 900 s cooldown and 3
  runs a day per key (the third failure writes "Fix not holding"), 12 safe
  fixes a day, 2 per chat reply. Every run is in
  `knowledge/director/fixes.jsonl`.
- **Dev tickets.** The Director never edits code: a code bug becomes
  `[TICKET: title] ... [/TICKET]` -> `knowledge/director/tickets/<date>-<slug>.md`
  (evidence scrubbed of keys, suspected file, suggested fix; 5 new a day;
  the same open ticket gets a "Seen again" line). Listed in the briefing.
- **Memory** (`app/services/director_memory.py`). The last 40 chat turns are
  replayed (8 turns, 3,000 chars) and older ones folded into a summary;
  incidents (problem, cause, fix, worked) are searched before a diagnosis;
  promises (`[PROMISE]`, `[DONE: id]`) expire after 14 days and show on the
  briefing under "Needs you today".
- **Mission.** `knowledge/director/mission.md` (seeded from
  `prompts/director/mission_seed.md`; edit it on the Dashboard or
  `POST /api/director/mission`) is shown to every chat, plan and briefing;
  `[GOAL: section] ... [/GOAL]` adds to its "From conversation" part, and
  every plan item names the `goal` it serves.
- **Nightly self-check.** `run_nightly()` first runs `director_fix.self_check`
  (no model): a mapped health row that is not ok (Claude proxy, Gemini
  harness, SearXNG, queue; BuzzEdit only with work queued) gets its safe fix,
  is re-checked and recorded as an incident.

## Waiting for you

Anything that cannot go on without the creator is raised in one bright
pop-up (2026-10-26; he found waiting work looked like work in progress).
`app/services/needs_you.py` (`GET /api/needs_you`) collects, most urgent first:
Auto Story videos waiting to be approved for publishing, workflow steps
`paused_for_approval`, production review gates (`produce_gate`), pending
Studio Director approvals, long videos at `Voice Recording` / `Ready to
record` (offering "Use my cloned voice" -> `/api/auto_story/{id}/run`), and
one summary row for Shorts waiting to be recorded. A project in the
production queue or being narrated is not listed. Each item carries its own
buttons (method, path, body), so a new kind needs no frontend change.
`frontend/src/components/NeedsYou.tsx` polls it every 30 s, shows a glowing
header badge, and opens the pop-up by itself whenever an item he has not put
off is waiting ("Later" = 2 h, closing = 1 h; the Shorts row alone never
interrupts). A step on the Projects page pulses only while work is really
running on it: `Voice Recording` only while his cloned voice is being made.

## One video at a time

Creator rule 2026-10-26 ("the PC must not lag or hang"): one video is made
at a time, and the next starts only when that one finishes or is paused.
`app/services/video_slot.py` holds the slot: an Auto Story run (`run()`,
`make_mood_reel()`) waits in line in `turn()` -- its record says
`state: "waiting"` and who it waits for -- and holds the slot from its voice
until its production is queued; from then the queue item holds it, queued or
running. A paused item or a paused queue holds nothing. The queue worker does
not start an item while another project's voice is being made.

A start from the page while the slot is taken is refused with 409
`{"code": "video_running", "message", "active"}` (`/api/auto_story/make`,
`/run`, `/regenerate`, `/api/projects/{id}/produce_video`,
`/api/produce/queue`); `frontend/src/services/videoSlot.ts` wraps
`window.fetch`, so every page shows the same pop-up (`VideoBusyPopup.tsx`):
"Start mine after it" resends with `when_free=1` (the job waits in line),
"Pause it, start mine" pauses the running item first (not mid-render),
Cancel hands back the 409. Batches, Dexter, the Director and the nightly run
always wait their turn. A restart puts waiting videos back in line in order
(`resume_watchers`). `GET /api/video_slot` lists the slot and the line.

Models: a local model call waits until loading it leaves 1.5 GB VRAM and
5 GB RAM free (`integrations/llm.py` `wait_for_local_headroom`, up to 6 h;
an idle ComfyUI is asked to hand the card back once). ComfyUI starts with
`--cache-ram 6 --disable-pinned-memory` (BuzzEdit `electron/main.cjs`).
Scripts are cleaned for the voice (`auto_story.clean_for_voice`): no
`[...]` editor cues, no markdown marks, no model "text continues from" seams
or repeated paragraphs; a script too long to direct skips NarrationDirector.

## Writing a good persona

- Open with **Role** and **Mission** — the model reads the top most reliably.
- Give numbered **Responsibilities** rather than prose.
- State refusals explicitly ("Do not make up facts. Cite sources.").
- Name the output format you expect; steps that feed later steps should produce
  parseable Markdown or JSON.
- Content is authored in Hinglish — see `backend/prompts/channels/` for each
  brand's voice, and reference the channel guide rather than restating it.
- Keep it under a few hundred lines. It is prepended to every single call, and
  memory context is appended on top of it.
