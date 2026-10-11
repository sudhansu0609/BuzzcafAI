# Agents

106 agent personas across 13 departments, each defined as one Markdown file in
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
| `model_tier` | no | `fast` or `strong`; anything else becomes `strong` (the default) |
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
`lm_studio_context_length` tokens of context (32k by default): a model that is
not in memory is loaded through `lms load -c` before the call, because LM
Studio's own just-in-time load (what happens after every idle unload) uses its
default (16k for Gemma), which a full script's visual plan does not fit. A
"prompt exceeds the context" refusal from a model loaded smaller than the
setting reloads it at the setting and retries once.

`fast` is currently declared by `TagGenerator`, `TitleGenerator`,
`DescriptionWriter`, `MetadataOptimizer`, `PublishingChecklist`,
`TaxonomyManager` and `CitationArchivist`. Everything else runs `strong`.

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
