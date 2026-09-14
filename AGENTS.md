# Agents

105 agent personas across 13 departments, each defined as one Markdown file in
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

## Runtime-created agents

The Agents Workbench (`frontend/src/pages/ai/AgentCreatorStudio.tsx` →
`backend/app/api/agents_api.py`) is a **separate, simpler system**: agents are
JSON records with an inline `systemPrompt`, stored by
`app/services/agents_registry.py` and run against a local LM Studio / Ollama
model. They do not appear in `list-agents` and cannot be used in workflows.

Use the Markdown personas for production pipelines; use the Workbench for
throwaway experiments and group chat.

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
