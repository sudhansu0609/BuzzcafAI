import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.models.project import Project, StepExecution
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.agent import AgentFactory
from integrations.llm import LLMService
from integrations import effect_catalog, idle_offload

import requests

from core.errors import ApprovalRequired, AssetMissing, LLMUnavailable

logger = logging.getLogger("buzzcaf_ai.engine.workflow")

# Spoken-narration pace used to turn a target runtime (minutes) into a word
# budget for the writer. It suits the channels' conversational Hinglish
# narration and is the single knob for retuning length pacing.
WORDS_PER_MINUTE = 140

# Step output types whose prompt gets a target-length directive when the
# project has one set (Project.metadata["target_duration_minutes"]).
SCRIPT_OUTPUT_TYPES = {"outline", "script", "story", "script_final", "narration_optimized"}

# Steps that rewrite an existing script (edit / narration pass). Their output
# must be the whole script again, so it is checked against the input's length.
SCRIPT_REWRITE_TYPES = {"script_final", "narration_optimized"}

# Brands made by BuzzAnimate (animated screenplay), not BuzzEdit stills.
ANIMATED_BRANDS = {"khayal3baje", "originals"}

# Steps that write words the creator will say: they get his own writing style
# (app/services/writing_style.py) and are checked against it.
STYLE_OUTPUT_TYPES = (SCRIPT_OUTPUT_TYPES - {"outline"}) | {"voice_over"}

SCRIPT_TEXT_INSTRUCTION = """
### Output format (strict)
Output the COMPLETE script as plain Markdown -- every scene, every spoken line,
from the first word to the last. No JSON, no code fences, no wrapper object, no
summary instead of the script, and no commentary before or after it.
"""


def _unwrap_script(text: str) -> str:
    """Pull the script out of a JSON wrapper some personas answer with
    (`{"results": {"script_final": "..."}}`); plain Markdown passes through."""
    s = (text or "").strip()
    fenced = s.startswith("```")
    if fenced:
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    if not s.startswith("{"):
        return (text or "").strip() if not fenced else s
    try:
        data = json.loads(s, strict=False)  # models put raw newlines inside strings
    except ValueError:
        return s  # broken JSON: left for the length check to reject

    def find(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for key in ("script_final", "narration_optimized", "narration", "script", "story", "text", "content"):
                v = obj.get(key)
                if isinstance(v, str) and v.strip():
                    return v
            for v in obj.values():
                got = find(v)
                if got:
                    return got
        return None

    return (find(data) or s).strip()


def _spoken_words(text: str) -> int:
    """The words that are said: cue lines and speaker labels are not runtime."""
    from app.services.writing_style import narration_words
    return narration_words(text)


def classify_error(exc: Exception) -> str:
    """Categorise a step failure by exception type, not by message text.

    Anything unrecognised is BLOCKING on purpose: an unexpected exception is a
    bug in our code, and dressing it up as a retryable workflow state hides it.
    """
    if isinstance(exc, ApprovalRequired):
        return "HUMAN_INTERVENTION_REQUIRED"
    if isinstance(exc, (LLMUnavailable, requests.Timeout, requests.ConnectionError, TimeoutError, ConnectionError)):
        return "RETRYABLE"
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        # Rate limits and transient upstream faults are worth another attempt.
        if status == 429 or (status is not None and 500 <= status < 600):
            return "RETRYABLE"
        return "BLOCKING"
    if isinstance(exc, (AssetMissing, FileNotFoundError)):
        return "RECOVERABLE"
    return "BLOCKING"

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "workflows")
CHANNELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "channels")

# The research dossier the ResearchAgent is asked to fill in, key -> (file, heading).
# Until v9 these five files were written with the literal sentence "Information
# gathered from research." whatever the agent said, which read like research and
# was not. A section the model did not produce now simply has no file, and the
# step's history records it under `simulated_sections`.
RESEARCH_SECTIONS = {
    "timeline": ("timeline.md", "Timeline"),
    "facts": ("facts.md", "Factual Claims"),
    "sources": ("sources.md", "Sources"),
    "media": ("media.md", "Visual References"),
    "unanswered_questions": ("unanswered_questions.md", "Unanswered Questions"),
    "story_material": ("story_material.md", "Story Material"),
}

RESEARCH_JSON_INSTRUCTION = """
### Required format of the finished dossier (JSON only, written AFTER your research)
When your research is done, reply with a single JSON object and nothing else:

{
  "timeline": ["dated events, oldest first -- each with its source URL"],
  "facts": ["one verified claim per entry, labelled [Verified] / [Folklore] / [Alleged] / [Fiction], with its source URL"],
  "sources": ["title - url (only pages you actually searched or read)"],
  "media": ["images, footage or maps worth sourcing, with where they come from"],
  "unanswered_questions": ["what you could not establish"],
  "story_material": {
    "world": ["real texture for the setting: how the place, the job, the routine, the objects, the sounds and the smells actually are (from what you read)"],
    "folklore": ["the entity or belief with its exact local rules: what it does, what it wants, what wards it off, which region, which name"],
    "real_details": ["specific, unusual, checkable details a writer would never invent (a ritual, a register, a rule, a local word)"],
    "story_seeds": ["3-5 concrete story engines drawn from the material: a situation, a character with a reason to stay, and the hidden history underneath"],
    "twists": ["2-3 possible endings that re-read the earlier events, each tied to a real belief or detail above"]
  }
}

Leave a key out entirely rather than filling it with placeholder text. Do not
invent sources, records, dates, villages or witnesses. For a story episode the
"story_material" is what the writer needs most: fill it from what you read.
"""

# `_call_local` (the path BaseAgent.execute() actually uses for local models,
# see integrations/llm.py) never sends response_format/JSON-mode hints to
# LM Studio or llama.cpp -- require_json=True is a no-op there. JSON
# compliance for a locally-run visual_plan step comes only from instructions
# in the prompt text, same as RESEARCH_JSON_INSTRUCTION above.
VISUAL_PLAN_JSON_INSTRUCTION = """
### Required Output Format (JSON only)
Reply with a single JSON object and nothing else:

{
  "genre": "documentary",
  "beats": [
    {"anchor": "a short phrase copied verbatim from the script",
     "kind": "<one kind from the Effect catalog below>",
     "image_prompt": "...", "video_prompt": "...", "negative_prompt": "...",
     "style_hint": "...", "aspect_ratio": "16:9", "text": "...", "subtext": "...",
     "items": ["...", "..."], "number": 1, "caption": "...", "look": "...",
     "source": "...", "format": "web", "site": "...", "ticks": ["...", "..."], "active": 0,
     "place": "...", "data": {"value": 40, "suffix": "%"},
     "effect": "flicker", "intensity": 0.6, "duration": 0.5, "priority": 1.0}
  ]
}

`fx`/`atmos` beats trigger a visual effect BuzzEdit renders at the anchor: set
`effect` to one of the palette names given below, with optional `intensity`
(0-1) and `duration` (seconds). `fx` is a short punctuation hit (a reveal, a
scare, a tension beat); `atmos` is an ambient texture held longer. `grade` shifts
the colour for a moment (set `data` to `{"saturation":0.7,"vignette":0.3}` etc.).
Use effects sparingly and only where they earn the moment.

`anchor` MUST be copied character-for-character from the script you were given
(a short phrase, not a paraphrase) -- it is used to locate where the beat
belongs. Include only the fields relevant to `kind`; leave the rest out rather
than inventing values. Do not invent an anchor that does not appear in the
script.
""" + "\n" + effect_catalog.prompt_section() + "\n"


def _render_section(value: Any) -> str:
    """A section of the research JSON as Markdown, without inventing anything."""
    if isinstance(value, list):
        lines = []
        for item in value:
            text = json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
            if text.strip():
                lines.append(f"- {text.strip()}")
        return "\n".join(lines)
    if isinstance(value, dict):
        # A dossier part made of named lists (the story material): one
        # sub-heading per key, its items as bullets.
        if value and all(isinstance(v, (list, str)) for v in value.values()):
            parts = []
            for key, v in value.items():
                body = _render_section(v)
                if body:
                    parts.append(f"### {str(key).replace('_', ' ').title()}\n\n{body}")
            return "\n\n".join(parts)
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value or "").strip()


def _apply_step_delegations(agent_output: str, llm_service, caller: str):
    """Run any `[INVOKE_AGENT]` blocks the step's agent emitted (roadmap v9, B3).

    Same pass the Studio Assistant uses - same cap, same depth-1 rule - but the
    results are appended as `## Delegated: <Agent>` sections so they end up in
    the step's asset, and the step's own `requires_approval` still gates the
    whole thing. Callers skip this for JSON assets: a Markdown heading would
    make them unparseable.
    """
    from app.services.studio_chat import process_agent_invocations, strip_invocations, process_web_research_tags

    text = process_web_research_tags(str(agent_output))
    _, records = process_agent_invocations(text, llm_service=llm_service, caller=caller)
    if not records:
        return text, records

    parts = [strip_invocations(text)]
    for record in records:
        agent = record["agent"]
        task = record["task"]
        if record.get("skipped"):
            parts.append(f"## Delegated: {agent} (not run)\n\n> {task}\n\nOver the delegation limit for one step.")
        elif record.get("error"):
            parts.append(f"## Delegated: {agent} (failed)\n\n> {task}\n\n{record['error']}")
        else:
            label = " (simulated)" if record.get("simulated") else ""
            parts.append(f"## Delegated: {agent}{label}\n\n> {task}\n\n{record['output']}")
    return "\n\n".join(parts), records


def _parse_research(raw_output: str) -> Optional[Dict[str, Any]]:
    """The agent's JSON dossier, or None when it answered in prose."""
    from integrations.llm import clean_json_response

    try:
        parsed = json.loads(clean_json_response(str(raw_output)))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None

from core.workflow import workflow_registry


def _condition_holds(project: Project, condition: str) -> bool:
    """A step's `when`. Unknown conditions hold (the step runs)."""
    name = (condition or "").strip().lower()
    if name == "shorts_first":
        from app.services import session_format
        return session_format.is_shorts_first(project)
    if name == "not_animated":
        return (project.brand or "").strip().lower() not in ANIMATED_BRANDS
    return True


#: Why a `when` step was passed by, for the step log.
_SKIP_REASONS = {
    "not_animated": "this channel is animated by BuzzAnimate -- no BuzzEdit stills plan is needed.",
    "shorts_first": "this project is recorded as the long video only (no Shorts first) -- "
                    "turn on \"Shorts first\" for the project or the channel to write them.",
}


def _episode_format_direction(project: Project) -> str:
    """The project's episode format, unless the creator's instructions
    already carry it (the nightly run puts it there)."""
    try:
        from app.services.longform_nightly import format_direction
        direction = format_direction(project.brand, project.metadata.get("episode_format"))
    except Exception as exc:  # noqa: BLE001 - a missing format never fails a step
        logger.warning(f"Could not read the episode format: {exc}")
        return ""
    if not direction or direction in str(project.metadata.get("creator_instructions") or ""):
        return ""
    return direction


def _opening_directions(project: Project) -> str:
    """How the long video opens: after its Shorts, on the greeting (a
    session), and on the creator's face (face first)."""
    try:
        from app.services import session_format
        return session_format.long_script_direction(project) + session_format.face_intro_direction(project)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read the session / face layout: {exc}")
        return ""


def _refresh_recording_script(project: Project, history_step: Optional[StepExecution] = None) -> None:
    """script/recording_script.md (the session's Shorts, then the long video)
    after a long script or the Shorts changed. Never fails a step."""
    try:
        from app.services import session_format
        rel = session_format.refresh_recording_script(project)
        if rel and history_step is not None:
            history_step.logs.append(f"Recording script updated: {rel} (Shorts first, then the long video).")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not update the recording script: {exc}")


#: Steps the creator's own script makes unnecessary, and those a finished
#: recording makes unnecessary (the SEO step stays in both).
OWN_SCRIPT_SKIPPED = {"research", "script", "story", "outline", "vlog_plan", "script_final", "narration_optimized",
                      "voice_over", "character_plan"}  # his script is final; an animated one goes to BuzzAnimate as written
RECORDED_SKIPPED = OWN_SCRIPT_SKIPPED | {"shorts_set", "visual_plan", "sound_plan"}


def _recording_text_for_seo(project: Project) -> str:
    """What the SEO step reads when the project has no script: the kept
    transcript of the recording if there is one, else the title and brief."""
    try:
        from app.services import writing_style
        channel = writing_style.canonical_channel(project.brand)
        path = writing_style._dir(channel, "recordings", f"{writing_style._slug(project.id, 120)}.md")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Could not read the recording transcript for SEO: {exc}")
    brief = str(project.metadata.get("creative_brief") or "")
    return f"Title: {project.name}\n\n{brief}".strip()


def _duration_directive(project: Project, output_asset_type: str) -> str:
    """Target-length instruction for a script/outline step, or '' when unset.

    Reads the target the creator set on the project (in minutes) and turns it
    into a word budget so the writer produces a video of the right length; the
    creator resizes simply by changing the number and re-running the step.
    """
    minutes = project.metadata.get("target_duration_minutes")
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return ""
    if minutes <= 0:
        return ""
    if output_asset_type == "outline":
        return (
            f"\n\n### Target runtime\nPlan this outline for a video about {minutes:g} minutes long. "
            f"Give each segment an approximate minute budget, and make those budgets add up to about "
            f"{minutes:g} minutes.\n"
        )
    words = round(minutes * WORDS_PER_MINUTE)
    return (
        f"\n\n### Target runtime\nThis video's target length is {minutes:g} minutes -- about {words:,} "
        f"spoken words at ~{WORDS_PER_MINUTE} words per minute. Write the narration to run about "
        f"{minutes:g} minutes (within ~10%). If the material is thin, add depth, specific detail and "
        f"examples rather than filler; if it runs long, tighten it. Do not mention the word count, the "
        f"timing, or this instruction anywhere in the script itself.\n"
    )


class WorkflowEngine:
    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm_service = llm_service or LLMService()
        self.load_workflows()

    def load_workflows(self):
        """Discovers workflows using the core WorkflowRegistry."""
        workflow_registry.discover_workflows()

    @property
    def workflows(self) -> Dict[str, WorkflowDefinition]:
        return workflow_registry.workflows

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        return workflow_registry.get(workflow_id)


    def _resolve_agent(self, agent_role: str):
        """The agent that runs a step: a persona by name, else a department's
        manager when the step names a department (roadmap v9, E3)."""
        from core.agent import agent_registry

        agent = self._resolve_agent_inner(agent_role)
        # A step's agent runs without its memory log: other channels' old scripts
        # in the prompt made it drift (the long-script path already works this way).
        try:
            agent.use_memory = False
        except Exception:
            pass
        return agent

    def _resolve_agent_inner(self, agent_role: str):
        from core.agent import agent_registry

        if agent_role.lower().strip() in agent_registry.agents:
            return AgentFactory.get_agent(agent_role, self.llm_service)
        try:
            from app.departments import get_department

            dept = get_department(agent_role)
        except Exception as exc:
            logger.warning(f"Could not look up department '{agent_role}': {exc}")
            dept = None
        if dept and dept.manager_role:
            logger.info(f"Step names department '{dept.name}'; routing to its manager '{dept.manager_role}'")
            return AgentFactory.get_agent(dept.manager_role, self.llm_service)
        return AgentFactory.get_agent(agent_role, self.llm_service)

    def _get_brand_guide(self, brand: str) -> str:
        """Load brand markdown guide if exists, else return a default text."""
        guide_name = brand.replace(" ", "").strip()
        guide_path = os.path.join(CHANNELS_DIR, f"{guide_name}.md")
        if os.path.exists(guide_path):
            try:
                with open(guide_path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                logger.error(f"Error reading brand guide for {brand}: {e}")
        return f"Maintain high-quality storytelling matching the '{brand}' channel tone."

    @idle_offload.tracked
    def execute_next(
        self,
        project_id: str,
        user_feedback: Optional[str] = None,
        allow_all: Optional[bool] = None,
    ) -> Project:
        """
        Executes the next step or re-runs the current step if feedback is provided.
        Returns the updated Project instance.

        Every model call of the step follows its job's route on the Model
        Routing window (research, script, shorts, SEO, ...: `llm.job_for_asset`).
        """
        from integrations.llm import job_for_asset, llm_job
        job, step = None, ""
        try:
            project = Project.load(project_id)
            wf = self.get_workflow(project.workflow_name)
            step_def = wf.get_step(project.current_step) if wf else None
            if step_def is None and wf and wf.steps:
                step_def = wf.steps[0]
            if step_def:
                job = job_for_asset(step_def.output_asset_type)
                step = f"{project.workflow_name}/{step_def.name}/{project_id}"
        except Exception:  # noqa: BLE001 - _execute_next reports a bad project itself
            pass
        with llm_job(job, step):
            return self._execute_next(project_id, user_feedback, allow_all)

    def _execute_next(
        self,
        project_id: str,
        user_feedback: Optional[str] = None,
        allow_all: Optional[bool] = None,
    ) -> Project:
        project = Project.load(project_id)
        wf = self.get_workflow(project.workflow_name)
        if not wf:
            raise ValueError(f"Workflow '{project.workflow_name}' not found for project {project_id}")

        # Check if allow_all is active (via parameter, project metadata, or global config)
        if allow_all is not None:
            is_allow_all = bool(allow_all)
            project.metadata["allow_all"] = is_allow_all
        else:
            cfg = getattr(self.llm_service, "config", {})
            is_allow_all = bool(
                project.metadata.get("allow_all")
                or project.metadata.get("auto_approve")
                or cfg.get("allow_all_steps")
                or cfg.get("auto_approve_workflow_steps")
            )

        # Check if the project is already completed
        if project.current_step == "Completed" or project.status == "completed":
            logger.info(f"Project {project_id} is already completed.")
            return project

        # The master pause (docs/STUDIO_DIRECTOR_PLAN.md Part 1): hold here,
        # between steps, before this one starts. Covers the long-form
        # nightly run, story adaptations and every Story Desk script, since
        # they all drive the engine one `execute_next` call per step.
        from app.services import master_control
        master_control.wait_if_paused(f"workflow step '{project.current_step}' of project {project_id}")

        # Find current step details
        step_def = wf.get_step(project.current_step)
        if not step_def:
            # If current_step is not in the list, default to first step
            if wf.steps:
                step_def = wf.steps[0]
                project.current_step = step_def.name
            else:
                project.status = "completed"
                project.save()
                return project

        # A step for some projects only (`when`): the others pass it by.
        if step_def.when and not _condition_holds(project, step_def.when):
            return self._skip_step(project, wf, step_def)

        # Handle resume from approval pause
        history_step = None
        for hist in reversed(project.steps_history):
            if hist.step_name == step_def.name:
                history_step = hist
                break

        # If it was paused for approval and user approves without feedback (or allow_all is active)
        if history_step and history_step.status == "paused_for_approval" and not user_feedback:
            # User approved or allow_all triggered! Mark it completed and advance
            history_step.status = "completed"
            history_step.completed_at = datetime.now().isoformat()
            if is_allow_all:
                history_step.logs.append("Step approved via 'Allow All' option.")
            
            # Advance step
            next_step = wf.get_next_step(project.current_step)
            if next_step:
                project.current_step = next_step.name
            else:
                project.current_step = "Completed"
                project.status = "completed"
            
            project.save()
            logger.info(f"Step '{step_def.name}' approved (allow_all={is_allow_all}). Advanced to '{project.current_step}'")
            return project

        # Run step execution (either new run, or re-run with user feedback)
        logger.info(f"Running step '{step_def.name}' for project '{project.name}'")
        
        # Determine status: if allow_all is active, bypass paused_for_approval
        execution_status = "completed"
        if step_def.requires_approval and not is_allow_all:
            execution_status = "paused_for_approval"

        # A re-run of a failed step (no new feedback) resumes a long script
        # from its saved sections instead of starting over.
        resume_long = bool(history_step and history_step.status == "failed" and not user_feedback)

        # Instantiate step execution details in history
        if not history_step or history_step.status == "completed":
            history_step = StepExecution(
                step_name=step_def.name,
                agent_name=step_def.agent_role,
                status="running",
                started_at=datetime.now().isoformat()
            )
            project.steps_history.append(history_step)
        else:
            history_step.status = "running"
            history_step.started_at = datetime.now().isoformat()
            if user_feedback:
                history_step.human_feedback = user_feedback
                history_step.logs.append(f"User requested changes: {user_feedback}")

        project.save()

        # A Human Touch step outside the adaptation runner (which writes its own,
        # numbered reports) gets the machine-writing report of the current script,
        # made here whenever it is missing or older than the script (2026-10-24).
        if "ai_tells" in step_def.input_assets and project.assets.get("script"):
            try:
                from app.services import story_adapt
                script_path = os.path.join(project.get_project_dir(), project.assets["script"])
                tells_rel = project.assets.get("ai_tells")
                tells_path = os.path.join(project.get_project_dir(), tells_rel) if tells_rel else ""
                if not tells_path or not os.path.exists(tells_path) or (
                        os.path.exists(script_path) and os.path.getmtime(tells_path) < os.path.getmtime(script_path)):
                    report = story_adapt.write_tells(project, "script")
                    history_step.logs.append(f"Machine-writing report: {report['score']}/100, "
                                             f"{len(report['tells'])} kind(s) of tell.")
                    project.save()
            except Exception as e:  # noqa: BLE001 - the step still runs without it
                logger.warning(f"Could not write the ai_tells report: {e}")

        # Gather inputs from dependencies
        context_data = ""
        input_texts: Dict[str, str] = {}
        for input_asset in step_def.input_assets:
            asset_path = project.assets.get(input_asset)
            if asset_path:
                full_path = os.path.join(project.get_project_dir(), asset_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            input_texts[input_asset] = f.read()
                            context_data += f"\n\n### Input Asset ({input_asset}):\n" + input_texts[input_asset]
                    except Exception as e:
                        logger.error(f"Error reading asset file {full_path}: {e}")

        # An already-recorded video has no script: the SEO step reads the
        # transcript (or the title and brief) instead, and never fails for it.
        if step_def.output_asset_type == "seo_package" and not any(
                input_texts.get(k, "").strip() for k in ("narration_optimized", "script_final", "script")):
            fallback = _recording_text_for_seo(project)
            if fallback:
                input_texts["script"] = fallback
                context_data += "\n\n### Input Asset (recording transcript):\n" + fallback

        brand_guide = self._get_brand_guide(project.brand)

        # Formulate agent instruction
        agent_instruction = f"""
You are executing the step '{step_def.name}' for the media project '{project.name}' (Brand: {project.brand}).

### Brand Guidelines
{brand_guide}

### Context & Input Assets
{context_data if context_data else "No input assets provided."}
"""

        # Direction set before the run (the nightly long-form planner): the
        # creator's own instructions for the channel, and the strategist's brief.
        if project.metadata.get("creator_instructions"):
            agent_instruction += (
                "\n\n### The Creator's Instructions for this channel (follow these)\n"
                f"{project.metadata['creator_instructions']}\n"
            )
        if project.metadata.get("creative_brief"):
            agent_instruction += (
                "\n\n### Creative Brief from the Channel Strategist\n"
                f"{project.metadata['creative_brief']}\n"
            )
        # The episode's format (Raat3Baje: rules / real encounter / story /
        # black magic / tantra), unless the creator's instructions carry it.
        episode_format = _episode_format_direction(project)
        if episode_format:
            agent_instruction += f"\n\n### This episode's format\n{episode_format}\n"
        # The art style (real / explainer / stick figure / cartoon), so the
        # writers, the storyboard and the thumbnail designer all picture the
        # same medium (2026-10-21).
        try:
            from integrations import art_style as art_mod
            from integrations.buzzedit_settings import art_style_of, settings_for_brand as _sfb_art
            art_direction = art_mod.step_direction(art_style_of(_sfb_art(project.brand, None, project)))
            if art_direction:
                agent_instruction += f"\n\n{art_direction}\n"
        except Exception as exc:
            logger.warning(f"Could not add the art style to the step prompt: {exc}")

        # How the creator himself writes, learned from his own writing and
        # recordings (app/services/writing_style.py): every script-writing step,
        # and the session's Shorts (he says those too).
        format_override = ""
        if step_def.output_asset_type == "shorts_set":
            from app.services import writing_style
            style = writing_style.style_section(project.brand, project)
            if style:
                agent_instruction += style
                history_step.logs.append("The creator's own writing style was added to the prompt.")
        if step_def.output_asset_type in STYLE_OUTPUT_TYPES:
            from app.services import writing_style
            standard = writing_style.standard_section(project.brand, project)
            if standard:
                agent_instruction += standard
                history_step.logs.append("The channel's story standard was added to the prompt.")
            # A sample he added since the style guide was written must be what
            # the writer follows: rebuild the guide first when it is older.
            refreshed = writing_style.ensure_current(project.brand, project)
            if refreshed:
                history_step.logs.append(refreshed)
            style = writing_style.style_section(project.brand, project)
            if style:
                agent_instruction += style
                history_step.logs.append("The creator's own writing style was added to the prompt.")
                format_override = writing_style.format_override(project.brand, project)
                rhythm = writing_style.rhythm_reminder(project.brand, project)
                if rhythm:
                    format_override += f"\n### Rhythm (the creator's own)\n{rhythm}\n"

        if history_step.human_feedback:
            agent_instruction += f"\n\n### IMPORTANT - User Requested Revisions:\nThe user has requested modifications. Please adjust your output based on this feedback:\n{history_step.human_feedback}\n"

        agent_instruction += f"""
### Task Description
{step_def.description}
{format_override}
### Expected Output
Please output the content matching the required output format (Markdown or JSON).
"""

        if step_def.output_asset_type == "research" or "research" in step_def.agent_role.lower():
            try:
                from app.services.web_research import web_research_service
                web_brief = web_research_service.brief(project.name)
                if web_brief and not web_brief.startswith("No live"):
                    agent_instruction += (
                        "\n\n### Seed search results for the project title (a first look only -- may be off-topic; "
                        f"your own searches decide what is true):\n{web_brief}\n")
                    history_step.logs.append("Injected verified live web research intelligence into prompt.")
            except Exception as exc:
                logger.warning(f"Web research brief generation failed: {exc}")

            try:
                from app.services.deep_research import build_source_brief
                sb = build_source_brief(project.name, ("news", "archives", "books"))
                if sb:
                    agent_instruction += f"\n\n### Public Archives, Books & News (source material)\n{sb}\n"
                    history_step.logs.append("Injected public archives/books/news source brief into prompt.")
            except Exception as exc:
                logger.warning(f"Deep research source brief generation failed: {exc}")

        if step_def.output_asset_type == "research":
            agent_instruction += RESEARCH_JSON_INSTRUCTION

        if step_def.output_asset_type == "visual_plan":
            agent_instruction += VISUAL_PLAN_JSON_INSTRUCTION
            # Tell the planner this video's genre and the effects that suit it,
            # so the fx/atmos beats it places are ones BuzzEdit renders well.
            try:
                from integrations.buzzedit_settings import settings_for_brand, fx_palette_for
                genre = settings_for_brand(project.brand).get("genre", "general")
                palette = ", ".join(fx_palette_for(project.brand))
                agent_instruction += (
                    f"\n\n### This video's genre and effect palette\n"
                    f"Genre: {genre}. For `fx`/`atmos` beats favour these effects: {palette}. "
                    f"Place them only where they earn the moment (a reveal, a tension beat, an "
                    f"archival cutaway), not on every line.\n"
                )
            except Exception as exc:
                logger.warning(f"Could not add genre effect palette to visual plan prompt: {exc}")
            # Story channels: pictures and clips only, in story order, with the
            # same characters throughout. This overrides the catalog above;
            # anything else is stripped before the render either way.
            try:
                from integrations.buzzedit_settings import art_style_of, is_story_style, settings_for_brand as _sfb
                from integrations import art_style as art_mod, story_visuals
                brand_settings = _sfb(project.brand, None, project)
                art = art_style_of(brand_settings)
                if is_story_style(brand_settings):
                    agent_instruction += (
                        "\n\nIMPORTANT -- this channel overrides the Effect catalog above:\n"
                        + story_visuals.planner_section(
                            float(brand_settings.get("video_broll_share") or 0.0),
                            story_visuals.load_cast_sheet(project), art_style=art)
                        + "\nKeep a character's look identical in every image_prompt and "
                        "video_prompt they appear in.\n")
                    history_step.logs.append("Story visual style: pictures and videos only.")
                elif art != "real":
                    agent_instruction += "\n\n" + art_mod.planner_section(art) + "\n"
                if art != "real":
                    history_step.logs.append(f"Art style: {art}.")
            except Exception as exc:
                logger.warning(f"Could not add story visual rules to visual plan prompt: {exc}")
            try:
                from integrations.music_catalog import planner_direction
                music_direction = planner_direction(project)
                if music_direction:
                    agent_instruction += f"\n\n{music_direction}\n"
            except Exception as exc:
                logger.warning(f"Could not add music direction to visual plan prompt: {exc}")

        if step_def.output_asset_type in SCRIPT_OUTPUT_TYPES - {"outline"}:
            agent_instruction += SCRIPT_TEXT_INSTRUCTION

        # Target length: fit the script/outline to the runtime the creator set.
        if step_def.output_asset_type in SCRIPT_OUTPUT_TYPES:
            directive = _duration_directive(project, step_def.output_asset_type)
            if directive:
                agent_instruction += directive
                history_step.logs.append(
                    f"Target runtime: {float(project.metadata['target_duration_minutes']):g} min injected into the {step_def.output_asset_type} prompt."
                )
            # A session's long video opens on the greeting; a face-first one is said to camera.
            opening = _opening_directions(project)
            if opening and step_def.output_asset_type != "outline":
                agent_instruction += opening
                history_step.logs.append("Opening direction added (recorded after its Shorts / face first).")

        # The session's Shorts, recorded before the long video.
        if step_def.output_asset_type == "shorts_set":
            from app.services import session_format
            agent_instruction += session_format.shorts_task(project)

        # Call worker Agent (a persona, or a department's manager)
        agent = self._resolve_agent(step_def.agent_role)

        # Check if output should be JSON (research dossiers, creative planning and SEO)
        is_json = step_def.output_asset_type in ["research", "visual_plan", "seo_package", "shorts_set"]

        try:
            long_output = self._long_script_step(
                project, step_def, agent, brand_guide, input_texts, history_step, resume_long,
            )
            if long_output is not None:
                agent_output = long_output
            elif step_def.output_asset_type == "research":
                agent_output = self._research_step(project, step_def, agent, agent_instruction, history_step)
            elif step_def.output_asset_type == "seo_package":
                agent_output = self._seo_step(project, step_def, agent, agent_instruction, history_step)
            elif step_def.output_asset_type == "screenplay":
                agent_output = self._screenplay_step(project, input_texts, history_step)
            else:
                agent_output = agent.execute(agent_instruction, require_json=is_json)
            if getattr(self.llm_service, "last_response_simulated", False):
                history_step.simulated = True
                history_step.logs.append(
                    "[WARNING] No LLM provider answered; output was generated using simulated fallback."
                )
                # A structured asset (visual plan, SEO package) made of canned
                # text is worse than none: production parsed one as JSON and
                # crashed, two videos later. Fail the step so it can be re-run
                # with a model answering; the research loop labels its own.
                if is_json and step_def.output_asset_type != "research":
                    raise RuntimeError(
                        f"No model answered for '{step_def.name}'; a simulated reply is not a usable "
                        f"{step_def.output_asset_type}. Check the model/provider and run the step again."
                    )

            if step_def.output_asset_type == "visual_plan":
                # The one JSON asset another program parses (produce_video).
                from integrations.llm import clean_json_response
                try:
                    json.loads(clean_json_response(str(agent_output)))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError(
                        f"'{step_def.name}' did not return valid JSON for its {step_def.output_asset_type} "
                        f"({exc}). Run the step again."
                    ) from exc

            if not is_json:
                agent_output, delegations = _apply_step_delegations(
                    agent_output, self.llm_service, step_def.agent_role
                )
                history_step.delegations = [
                    {
                        "agent": d["agent"],
                        "task_preview": d["task"][:200],
                        "simulated": bool(d.get("simulated")),
                        "skipped": bool(d.get("skipped")),
                    }
                    for d in delegations
                ]
                for d in history_step.delegations:
                    history_step.logs.append(
                        f"Delegated to {d['agent']}"
                        + (" (not run: over the limit)" if d["skipped"] else " (simulated)" if d["simulated"] else "")
                    )

            # Save output asset file
            ext = "json" if is_json else "md"
            file_name = f"{step_def.name.lower().replace(' ', '_')}.{ext}"
            file_path = os.path.join(project.get_project_dir(), file_name)
            
            if step_def.output_asset_type == "research":
                research_dir = os.path.join(project.get_project_dir(), "research")
                os.makedirs(research_dir, exist_ok=True)

                dossier = _parse_research(agent_output)
                written, missing = [], []
                if dossier is None and not str(agent_output or "").strip():
                    raise ValueError(
                        "The researcher returned nothing; the step was not completed. Re-run it "
                        "(check that the model is loaded and answering)."
                    )
                if dossier is None:
                    # Prose reply: keep it verbatim and write no section files at
                    # all, so an empty section is never mistaken for research.
                    missing = list(RESEARCH_SECTIONS)
                    body = str(agent_output)
                else:
                    parts = []
                    for key, (fn, title) in RESEARCH_SECTIONS.items():
                        rendered = _render_section(dossier.get(key))
                        if not rendered:
                            missing.append(key)
                            continue
                        with open(os.path.join(research_dir, fn), "w", encoding="utf-8") as f:
                            f.write(f"# {title}\n\n{rendered}\n")
                        written.append(fn)
                        parts.append(f"## {title}\n\n{rendered}\n")
                    body = "# Research package\n\n" + "\n".join(parts) if parts else str(agent_output)

                file_name = "research/research.md"
                with open(os.path.join(research_dir, "research.md"), "w", encoding="utf-8") as f:
                    f.write(body)

                history_step.simulated_sections = missing
                if missing:
                    history_step.logs.append(
                        f"Research sections the agent did not produce (no file written): {', '.join(missing)}"
                    )
                if written:
                    history_step.logs.append(f"Research sections written: {', '.join(written)}")
            elif step_def.output_asset_type in ["outline", "script", "story", "script_final", "narration_optimized"]:
                script_dir = os.path.join(project.get_project_dir(), "script")
                os.makedirs(script_dir, exist_ok=True)
                
                mapping = {
                    "outline": "outline.md",
                    "script": "draft.md",
                    "story": "draft.md",
                    "script_final": "final.md",
                    "narration_optimized": "narration.md"
                }
                fn = mapping.get(step_def.output_asset_type, "draft.md")
                file_name = f"script/{fn}"
                file_path = os.path.join(project.get_project_dir(), file_name)

                agent_output = _unwrap_script(agent_output)
                # A rewrite pass (edit / narration) must return the whole script.
                # A local model that runs out of context returns a stub instead;
                # fail the step rather than hand the teleprompter nine words.
                if step_def.output_asset_type in SCRIPT_REWRITE_TYPES:
                    source_path = project.assets.get("script_final") if step_def.output_asset_type == "narration_optimized" else None
                    source_path = source_path or project.assets.get("script")
                    source_words = 0
                    if source_path and os.path.exists(os.path.join(project.get_project_dir(), source_path)):
                        with open(os.path.join(project.get_project_dir(), source_path), "r", encoding="utf-8") as f:
                            source_words = _spoken_words(f.read())
                    out_words = _spoken_words(agent_output)
                    if source_words and out_words < source_words * 0.5:
                        raise ValueError(
                            f"The model returned only {out_words} words for a {source_words}-word script "
                            f"(truncated or summarised); nothing was saved. Re-run this step, ideally on a "
                            f"stronger or larger-context model."
                        )

                if step_def.output_asset_type in STYLE_OUTPUT_TYPES:
                    agent_output = self._match_creator_style(
                        project, step_def, agent, agent_output, history_step,
                        may_revise=long_output is None)
                    agent_output = self._fixed_greeting(project, agent_output, history_step)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(agent_output)
                # The session's recording script follows the newest long script.
                project.assets[step_def.output_asset_type] = file_name
                _refresh_recording_script(project, history_step)

                # Maintain the revision_log.md boilerplate
                rev_log_path = os.path.join(script_dir, "revision_log.md")
                if not os.path.exists(rev_log_path):
                    with open(rev_log_path, "w", encoding="utf-8") as f:
                        f.write("# Revision Log\n\n- Initial draft created.\n")

                # Length feedback loop: report the actual length against target
                # so the creator can see whether to resize and re-run this step.
                if step_def.output_asset_type != "outline":
                    words = _spoken_words(agent_output)
                    est_min = round(words / WORDS_PER_MINUTE, 1) if words else 0
                    target = project.metadata.get("target_duration_minutes")
                    if target:
                        history_step.logs.append(f"Script length: {words:,} spoken words ~{est_min} min (target {float(target):g}).")
                    else:
                        history_step.logs.append(f"Script length: {words:,} spoken words ~{est_min} min.")
            elif step_def.output_asset_type in ["scene_breakdown", "shot_list", "clip_plan", "image_plan", "assets_collected", "voice_over", "edit_plan", "review_report", "sound_plan", "thumbnail_plan", "vlog_plan", "character_plan", "screenplay"]:
                prod_dir = os.path.join(project.get_project_dir(), "production")
                os.makedirs(prod_dir, exist_ok=True)
                
                mapping = {
                    "scene_breakdown": "scenes.json",
                    "shot_list": "storyboard.md",
                    "clip_plan": "storyboard.md",
                    "image_plan": "storyboard.md",
                    "thumbnail_plan": "storyboard.md",
                    "vlog_plan": "storyboard.md",
                    "character_plan": "storyboard.md",
                    "assets_collected": "assets.csv",
                    "voice_over": "timeline.md",
                    "sound_plan": "timeline.md",
                    "edit_plan": "timeline.md",
                    "review_report": "qa.md",
                    "screenplay": "screenplay.md",
                }
                fn = mapping.get(step_def.output_asset_type, "storyboard.md")
                file_name = f"production/{fn}"
                file_path = os.path.join(project.get_project_dir(), file_name)

                # Words he will say: scored (and rewritten once) toward his style;
                # no greeting is forced into a voice-over asset.
                if step_def.output_asset_type in STYLE_OUTPUT_TYPES:
                    agent_output = self._match_creator_style(
                        project, step_def, agent, agent_output, history_step, may_revise=True)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(agent_output)

                # Initialize others if missing to satisfy the schema (scenes.json, storyboard.md, assets.csv, timeline.md)
                defaults = {
                    "scenes.json": "[]",
                    "storyboard.md": "# Storyboard\n",
                    "assets.csv": "ID,Type,Path,Tags\n",
                    "timeline.md": "# Timeline\n"
                }
                for def_fn, def_content in defaults.items():
                    def_path = os.path.join(prod_dir, def_fn)
                    if not os.path.exists(def_path):
                        with open(def_path, "w", encoding="utf-8") as f:
                            f.write(def_content)
            elif step_def.output_asset_type == "visual_plan":
                # The structured per-scene image/clip plan the BuzzEdit bridge
                # (app/api/produce_api.py) annotates onto the script. Without
                # this branch it fell into the bare `else` below and landed at
                # the project root instead of production/, unparsed.
                prod_dir = os.path.join(project.get_project_dir(), "production")
                os.makedirs(prod_dir, exist_ok=True)

                from integrations.llm import clean_json_response
                cleaned = clean_json_response(str(agent_output))

                file_name = "production/visual_plan.json"
                file_path = os.path.join(project.get_project_dir(), file_name)

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(cleaned)
            elif step_def.output_asset_type in ["seo_package", "publish_details", "analytics_report"]:
                pub_dir = os.path.join(project.get_project_dir(), "publish")
                os.makedirs(pub_dir, exist_ok=True)
                
                file_name = "publish/publish.json"
                file_path = os.path.join(project.get_project_dir(), file_name)
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(agent_output)
                
                # Satisfy output schema: title.txt, description.md, tags.txt, publish.json
                title_path = os.path.join(pub_dir, "title.txt")
                desc_path = os.path.join(pub_dir, "description.md")
                tags_path = os.path.join(pub_dir, "tags.txt")

                # The SEO manager's own title, description and tags. These files
                # used to get placeholders ("Title for <project>") every time.
                from integrations.youtube_publish import parse_seo_package, description_with_hashtags
                seo = parse_seo_package(str(agent_output))
                if seo and seo["titles"]:
                    with open(title_path, "w", encoding="utf-8") as f:
                        f.write(seo["titles"][0] + "\n")
                if seo and seo["description"]:
                    with open(desc_path, "w", encoding="utf-8") as f:
                        f.write(description_with_hashtags(seo["description"], seo["hashtags"]) + "\n")
                if seo and seo["tags"]:
                    with open(tags_path, "w", encoding="utf-8") as f:
                        f.write(", ".join(seo["tags"]) + "\n")

                if not os.path.exists(title_path):
                    with open(title_path, "w", encoding="utf-8") as f:
                        f.write(f"Title for {project.name}\n")
                if not os.path.exists(desc_path):
                    with open(desc_path, "w", encoding="utf-8") as f:
                        f.write(f"# Description\n\nOptimized description for {project.name}.\n")
                if not os.path.exists(tags_path):
                    with open(tags_path, "w", encoding="utf-8") as f:
                        f.write("buzzcaf, media, video, ai\n")
            elif step_def.output_asset_type == "shorts_set":
                # The session's Shorts: script/shorts.json (read by the
                # recording split) and shorts.md, then the recording script.
                from app.services import session_format
                shorts = session_format.parse_shorts(agent_output)
                if not shorts:
                    # Keep what the writer said, so a failure can be read instead of guessed at.
                    try:
                        raw_path = os.path.join(project.get_project_dir(), "script", "shorts_failed_reply.txt")
                        with open(raw_path, "w", encoding="utf-8") as f:
                            f.write(str(agent_output))
                    except OSError:
                        pass
                    raise ValueError(
                        "The Shorts writer returned no usable Shorts (strict JSON with a \"shorts\" list was "
                        "expected); nothing was saved. Re-run the step.")
                wanted = session_format.shorts_count(project)
                for s in shorts:
                    s["script"] = session_format.strip_greeting(s["script"])
                if len(shorts) != wanted:
                    history_step.logs.append(f"Asked for {wanted} Shorts, got {len(shorts)}.")
                shorts = shorts[:max(session_format.SHORTS_COUNTS)]
                file_name = session_format.save_shorts(project, shorts)
                project.assets["shorts_set"] = file_name
                history_step.logs.append(
                    "Shorts written: " + "; ".join(f"{s['title'] or 'untitled'} (~{s['estimated_seconds']} s)"
                                                   for s in shorts))
                _refresh_recording_script(project, history_step)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(agent_output)
            
            # Record asset mapping in project
            if step_def.output_asset_type:
                project.assets[step_def.output_asset_type] = file_name

            
            # Record execution in history
            started_time = datetime.fromisoformat(history_step.started_at)
            elapsed_ms = int((datetime.now() - started_time).total_seconds() * 1000)
            
            history_step.status = execution_status
            history_step.completed_at = datetime.now().isoformat()
            history_step.output_files[step_def.output_asset_type or "output"] = file_name
            history_step.logs.append(f"Successfully executed step '{step_def.name}' via agent '{step_def.agent_role}'.")
            history_step.logs.append(
                f"AUDIT TRAIL - workflow_id={wf.id} agent={step_def.agent_role} status={execution_status} "
                f"input_refs={step_def.input_assets} output_refs={file_name} elapsed_ms={elapsed_ms}"
            )

            
            # If step does NOT require approval or allow_all is active, advance immediately
            if not step_def.requires_approval or is_allow_all:
                next_step = wf.get_next_step(project.current_step)
                if next_step:
                    project.current_step = next_step.name
                else:
                    project.current_step = "Completed"
                    project.status = "completed"
                    
            logger.info(f"Step '{step_def.name}' completed with status: {execution_status}")
            
        except Exception as e:
            error_class = classify_error(e)
            error_msg = str(e)

            log_message = f"[{error_class}] Error executing agent step '{step_def.name}': {error_msg}"
            logger.error(log_message)
            
            history_step.status = "failed"
            history_step.logs.append(log_message)
            project.save()
            raise e

        project.save()
        return project

    def _match_creator_style(self, project, step_def, agent, script: str, history_step,
                             may_revise: bool) -> str:
        """Score a script against the creator's measured style; below
        `REVISE_BELOW`, ask the same agent once for a rewrite that keeps the
        content and changes the manner, and keep whichever scores higher. A
        long (sectioned) script is only scored here: each of its sections was
        already rewritten toward his style as it was written (the `StyleGate`
        in runtime/long_script.py), and 10k words in one call would be cut
        short. Never fails the step."""
        try:
            from app.services import writing_style

            if not writing_style.uses_my_style(project.brand, project):
                return script                       # "agent style": not scored or rewritten
            result = writing_style.check(script, project.brand)
            if result is None:
                return script
            best, best_result = script, result
            if may_revise and result["score"] < writing_style.REVISE_BELOW:
                history_step.logs.append(
                    f"Creator style match {result['score']}/100 -- rewriting once toward his style: "
                    + " | ".join(result["fixes"][:4]))
                revised = _unwrap_script(str(agent.execute(
                    writing_style.revise_task(project.brand, script, result, project)) or ""))
                again = writing_style.check(revised, project.brand) if revised else None
                if (again is not None and again["score"] > result["score"]
                        and _spoken_words(revised) >= 0.85 * _spoken_words(script)):
                    best, best_result = revised, again
                else:
                    history_step.logs.append(
                        "The style rewrite did not score higher (or came back short); kept the original.")
            history_step.logs.append(
                f"Creator style match: {best_result['score']}/100"
                + (f" -- still off: {' | '.join(best_result['fixes'][:3])}" if best_result["fixes"] else "."))
            matches = dict(project.metadata.get("style_match") or {})
            matches[step_def.output_asset_type] = {
                "score": best_result["score"], "fixes": best_result["fixes"],
                "checked_at": datetime.now().isoformat(timespec="seconds")}
            project.metadata["style_match"] = matches
            return best
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Creator style check failed: {exc}")
            return script

    def _skip_step(self, project: Project, wf: WorkflowDefinition, step_def: WorkflowStep) -> Project:
        """Record a `when` step as passed by and move on."""
        now = datetime.now().isoformat()
        reason = _SKIP_REASONS.get((step_def.when or "").lower(), f"its condition '{step_def.when}' does not hold.")
        project.steps_history = [h for h in project.steps_history if h.step_name != step_def.name]
        project.steps_history.append(StepExecution(
            step_name=step_def.name, agent_name=step_def.agent_role, status="completed",
            started_at=now, completed_at=now, logs=[f"Skipped: {reason}"]))
        next_step = wf.get_next_step(step_def.name)
        if next_step:
            project.current_step = next_step.name
        else:
            project.current_step = "Completed"
            project.status = "completed"
        project.save()
        logger.info(f"Step '{step_def.name}' skipped for project '{project.name}': {reason}")
        return project

    def skip_steps(self, project: Project, wf: WorkflowDefinition, output_types: set, reason: str) -> Project:
        """Record every not-yet-completed step whose output is one of
        `output_types` as passed by, and move `current_step` to the first
        step still to run (or "Completed")."""
        now = datetime.now().isoformat()
        done = {h.step_name for h in project.steps_history if h.status == "completed"}
        for step_def in wf.steps:
            if step_def.output_asset_type not in output_types or step_def.name in done:
                continue
            project.steps_history = [h for h in project.steps_history if h.step_name != step_def.name]
            project.steps_history.append(StepExecution(
                step_name=step_def.name, agent_name=step_def.agent_role, status="completed",
                started_at=now, completed_at=now, logs=[f"Skipped: {reason}"]))
            done.add(step_def.name)
        remaining = next((s for s in wf.steps if s.name not in done), None)
        if remaining:
            project.current_step = remaining.name
        else:
            project.current_step = "Completed"
            project.status = "completed"
        project.save()
        return project

    def use_own_script(self, project_id: str, text: str) -> Project:
        """The creator's own script: the Studio skips research and writing and
        continues from the steps after it. His words are never rewritten."""
        text = (text or "").strip()
        if not text:
            raise ValueError("The script is empty.")
        project = Project.load(project_id)
        wf = self.get_workflow(project.workflow_name)
        if not wf:
            raise ValueError(f"Workflow '{project.workflow_name}' not found for project {project_id}")
        script_dir = os.path.join(project.get_project_dir(), "script")
        os.makedirs(script_dir, exist_ok=True)
        file_name = "script/draft.md"
        with open(os.path.join(project.get_project_dir(), file_name), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        for asset in ("script", "script_final", "narration_optimized"):
            project.assets[asset] = file_name
        project.metadata["script_source"] = "creator"
        _refresh_recording_script(project)
        return self.skip_steps(project, wf, OWN_SCRIPT_SKIPPED, "the creator gave his own script")

    def _seo_step(self, project, step_def, agent, instruction: str, history_step) -> str:
        """The SEO step as research (runtime/seo_research.py): YouTube
        autocomplete, what ranks for the topic and how it performs, the web,
        then the package -- the evidence is kept in it. Falls back to one call
        when no model answers the chat."""
        from runtime import seo_research

        def log(msg: str) -> None:
            logger.info(msg)
            history_step.logs.append(msg)
            project.save()

        result = seo_research.run(agent, project, instruction, log)
        if result.get("calls"):
            history_step.logs.append(f"SEO research: {len(result['calls'])} lookup(s) in {result['turns']} turn(s).")
        return str(result.get("raw") or "")

    def _screenplay_step(self, project, input_texts: Dict[str, str], history_step) -> str:
        """The screenplay step (ANIMATED_CHANNELS_PLAN ST2): the model extracts the
        cast and labels the script; code copies his sentences into the screenplay
        and verifies no spoken word changed. Fails the step with the difference."""
        from app.services import animate_screenplay
        script = next((input_texts[k] for k in ("narration_optimized", "script_final", "script")
                       if input_texts.get(k, "").strip()), "")
        if not script.strip():
            raise ValueError("The screenplay step has no script to convert.")
        cast_out = os.path.join(project.get_project_dir(), "production", "cast.json")
        text = animate_screenplay.convert(script, project.brand, cast_out)
        history_step.logs.append("Screenplay: spoken text verified identical to the script; cast in production/cast.json.")
        return text

    def _research_step(self, project, step_def, agent, instruction: str, history_step) -> str:
        """The research step as a tool loop (runtime/research_loop.py): the
        researcher searches the live web, reads pages and searches again before
        it writes the dossier. Every lookup is in the step log."""
        from runtime import research_loop

        def log(msg: str) -> None:
            logger.info(msg)
            history_step.logs.append(msg)
            project.save()

        result = research_loop.run(agent, instruction, log)
        if result.get("calls"):
            history_step.logs.append(f"Research: {len(result['calls'])} live lookup(s) in {result['turns']} turn(s).")
        elif not result.get("simulated"):
            history_step.logs.append("Research: the dossier was written without any live lookup.")
        try:
            from memory.memory import memory_system
            memory_system.save(scope="agent", owner=step_def.agent_role, tags=["execution", "research"],
                               content={"task_summary": f"{step_def.name} for {project.name}",
                                        "result_snippet": str(result.get("raw") or "")[:2000]})
        except Exception as e:
            logger.warning(f"Could not save agent memory for the research step: {e}")
        return str(result.get("raw") or "")

    def _fixed_greeting(self, project, script: str, history_step) -> str:
        """A full video opens with the creator's greeting, word for word -- his
        name and the channel's, never a name borrowed from a sample. Shorts
        (under ~3 minutes of words) have no greeting. Never fails the step."""
        try:
            from app.services import writing_style

            if not writing_style.uses_my_style(project.brand, project) or _spoken_words(script) < 400:
                return script
            fixed, changed = writing_style.ensure_greeting(script, project.brand)
            if changed:
                history_step.logs.append(f"Greeting set to the creator's fixed line: {writing_style.greeting(project.brand)}")
            from app.services import session_format
            if session_format.is_shorts_first(project):
                # The session's recording is split at the greeting: it opens the long video.
                fixed, moved = session_format.greeting_first(fixed, project.brand)
                if moved:
                    history_step.logs.append("Session: the greeting was moved to the first line (the recording is split there).")
            return fixed
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not check the greeting: {exc}")
            return script

    def _style_gate(self, project, kind: str):
        """The creator's style applied section by section to a long script, or
        None in "agent style" or when there is nothing of his to compare with."""
        from app.services import writing_style
        from runtime.long_script import StyleGate

        if kind not in STYLE_OUTPUT_TYPES or not writing_style.uses_my_style(project.brand, project):
            return None
        if not writing_style.targets(writing_style.canonical_channel(project.brand)).get("words"):
            return None
        return StyleGate(
            check=lambda text: writing_style.check(text, project.brand),
            revise_task=lambda text, result: writing_style.revise_task(project.brand, text, result, project),
            below=writing_style.REVISE_BELOW,
            narration=writing_style.narration_format(project.brand, project),
            reminder=writing_style.rhythm_reminder(project.brand, project))

    def _long_script_step(self, project, step_def, agent, brand_guide: str, input_texts: Dict[str, str],
                          history_step, resume: bool) -> Optional[str]:
        """Write or rewrite a long script in sections (runtime/long_script.py) so
        a small local model can produce 30-90+ minutes without losing quality.
        Returns None when the step should run as a single ordinary call."""
        from runtime import long_script

        kind = step_def.output_asset_type
        config = getattr(self.llm_service, "config", {}) or {}
        try:
            minutes = float(project.metadata.get("target_duration_minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        target = round(minutes * WORDS_PER_MINUTE)

        source_key = None
        if kind in SCRIPT_REWRITE_TYPES:
            for key in (("script_final", "script") if kind == "narration_optimized" else ("script",)):
                if input_texts.get(key, "").strip():
                    source_key = key
                    break
            if not source_key or not long_script.should_chunk_rewrite(config, long_script.words(input_texts[source_key])):
                return None
            mode = "rewrite"
        elif kind in ("script", "story") and long_script.should_section(config, target):
            mode = "write"
        else:
            return None

        # A compact context: the channel, the direction, the inputs (minus the
        # script being rewritten) and the task -- no memory log, no JSON talk.
        parts = [
            f"You are working on the step '{step_def.name}' for the media project '{project.name}' "
            f"(Brand: {project.brand}).",
            f"### Brand Guidelines\n{brand_guide}",
        ]
        for key, text in input_texts.items():
            if key == source_key:
                continue
            limit = 4000 if mode == "rewrite" else 12000
            body = text if len(text) <= limit else text[:limit] + "\n[... trimmed ...]"
            parts.append(f"### Input Asset ({key})\n{body}")
        if project.metadata.get("creator_instructions"):
            parts.append(f"### The Creator's Instructions for this channel (follow these)\n{project.metadata['creator_instructions']}")
        if project.metadata.get("creative_brief"):
            parts.append(f"### Creative Brief from the Channel Strategist\n{project.metadata['creative_brief']}")
        episode_format = _episode_format_direction(project)
        if episode_format:
            parts.append(f"### This episode's format\n{episode_format}")
        opening = _opening_directions(project)
        if opening:
            parts.append(opening.strip())
        format_override = ""
        if kind in STYLE_OUTPUT_TYPES:
            from app.services import writing_style
            standard = writing_style.standard_section(project.brand, project)
            if standard:
                parts.append(standard.strip())
                history_step.logs.append("The channel's story standard was added to the prompt.")
            style = writing_style.style_section(project.brand, project)
            if style:
                parts.append(style.strip())
                format_override = writing_style.format_override(project.brand, project)
        if history_step.human_feedback:
            parts.append(f"### IMPORTANT - User Requested Revisions\n{history_step.human_feedback}")
        parts.append(f"### Task Description\n{step_def.description}\n{format_override}".rstrip())
        context = "\n\n".join(parts)
        gate = self._style_gate(project, kind)

        def log(msg: str) -> None:
            logger.info(msg)
            history_step.logs.append(msg)
            project.save()

        if mode == "rewrite":
            log(f"Long script: rewriting the {long_script.words(input_texts[source_key]):,}-word script in parts.")
            return long_script.rewrite_in_chunks(agent, config, context, input_texts[source_key], log, gate)

        work_dir = os.path.join(project.get_project_dir(), "script", "sections", kind)
        writer = long_script.LongScriptWriter(agent, config, work_dir, log, gate)
        if not resume:
            writer.reset()
        log(f"Long script: {minutes:g} min target (~{target:,} words) -- writing it section by section.")
        text = writer.write(context, minutes, target)
        try:
            from memory.memory import memory_system
            memory_system.save(scope="agent", owner=step_def.agent_role, tags=["execution", "long_script"],
                               content={"task_summary": f"{step_def.name} for {project.name} ({minutes:g} min, sectioned)",
                                        "result_snippet": text[:1500]})
        except Exception as e:
            logger.warning(f"Could not save agent memory for the long script: {e}")
        return text

    def restart(self, project_id: str, from_step: Optional[str] = None) -> Project:
        """Rewind the project so `from_step` (default: the first step) and every
        step after it run again. The title, brief, creator instructions, target
        runtime and the earlier steps' assets are kept; the rewound steps'
        history is dropped and their files are overwritten on the next run."""
        project = Project.load(project_id)
        wf = self.get_workflow(project.workflow_name)
        if not wf or not wf.steps:
            raise ValueError(f"Workflow '{project.workflow_name}' not found for project {project_id}")
        names = [s.name for s in wf.steps]
        start = from_step or names[0]
        if start not in names:
            raise ValueError(f"Step '{start}' is not in workflow '{wf.id}'. Steps: {', '.join(names)}")
        rewound = set(names[names.index(start):])

        project.steps_history = [h for h in project.steps_history if h.step_name not in rewound]
        project.current_step = start
        project.status = "active"
        project.save()
        logger.info(f"Project {project_id} rewound to '{start}' ({len(rewound)} step(s) will run again)")
        return project

    @idle_offload.tracked
    def execute_all(self, project_id: str, allow_all: bool = True) -> Project:
        """
        Executes all remaining workflow steps sequentially until completion or failure.
        When allow_all is True, approval-required steps will not pause the workflow.
        """
        project = Project.load(project_id)
        if allow_all:
            project.metadata["allow_all"] = True
            project.save()

        max_iterations = 30  # Guard against infinite loops
        iterations = 0

        while project.status != "completed" and project.current_step != "Completed" and iterations < max_iterations:
            iterations += 1
            prev_step = project.current_step
            project = self.execute_next(project_id, allow_all=allow_all)
            
            last = project.steps_history[-1] if project.steps_history else None
            if last and last.status == "failed":
                logger.error(f"execute_all stopped due to step failure in '{last.step_name}'")
                break
            if last and last.status == "paused_for_approval" and not allow_all:
                logger.info(f"execute_all paused for human approval at '{last.step_name}'")
                break
            if project.current_step == prev_step and last and last.status != "completed":
                logger.warning(f"execute_all detected no progress at step '{prev_step}', stopping.")
                break

        return project
