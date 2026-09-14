import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.models.project import Project, StepExecution
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.agent import AgentFactory
from integrations.llm import LLMService

import requests

from core.errors import ApprovalRequired, AssetMissing, LLMUnavailable

logger = logging.getLogger("buzzcaf_ai.engine.workflow")


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
}

RESEARCH_JSON_INSTRUCTION = """
### Required Output Format (JSON only)
Reply with a single JSON object and nothing else:

{
  "timeline": ["dated events, oldest first"],
  "facts": ["verified factual claims, one per entry"],
  "sources": ["title - url or archive reference"],
  "media": ["images, footage or maps worth sourcing, with where they come from"],
  "unanswered_questions": ["what you could not establish"]
}

Leave a key out entirely rather than filling it with placeholder text. Do not
invent sources.
"""


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
    from app.services.studio_chat import process_agent_invocations, strip_invocations

    text = str(agent_output)
    _, records = process_agent_invocations(text, llm_service=llm_service, caller=caller)
    if not records:
        return agent_output, records

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

    def execute_next(self, project_id: str, user_feedback: Optional[str] = None) -> Project:
        """
        Executes the next step or re-runs the current step if feedback is provided.
        Returns the updated Project instance.
        """
        project = Project.load(project_id)
        wf = self.get_workflow(project.workflow_name)
        if not wf:
            raise ValueError(f"Workflow '{project.workflow_name}' not found for project {project_id}")

        # Check if the project is already completed
        if project.current_step == "Completed" or project.status == "completed":
            logger.info(f"Project {project_id} is already completed.")
            return project

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

        # Handle resume from approval pause
        history_step = None
        for hist in reversed(project.steps_history):
            if hist.step_name == step_def.name:
                history_step = hist
                break

        # If it was paused for approval and user approves without feedback
        if history_step and history_step.status == "paused_for_approval" and not user_feedback:
            # User approved! Mark it completed and advance
            history_step.status = "completed"
            history_step.completed_at = datetime.now().isoformat()
            
            # Advance step
            next_step = wf.get_next_step(project.current_step)
            if next_step:
                project.current_step = next_step.name
            else:
                project.current_step = "Completed"
                project.status = "completed"
            
            project.save()
            logger.info(f"Step '{step_def.name}' approved by human. Advanced to '{project.current_step}'")
            return project

        # Run step execution (either new run, or re-run with user feedback)
        logger.info(f"Running step '{step_def.name}' for project '{project.name}'")
        
        # Determine status
        execution_status = "completed"
        if step_def.requires_approval:
            execution_status = "paused_for_approval"

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

        # Gather inputs from dependencies
        context_data = ""
        for input_asset in step_def.input_assets:
            asset_path = project.assets.get(input_asset)
            if asset_path:
                full_path = os.path.join(project.get_project_dir(), asset_path)
                if os.path.exists(full_path):
                    try:
                        with open(full_path, "r", encoding="utf-8") as f:
                            context_data += f"\n\n### Input Asset ({input_asset}):\n" + f.read()
                    except Exception as e:
                        logger.error(f"Error reading asset file {full_path}: {e}")

        brand_guide = self._get_brand_guide(project.brand)

        # Formulate agent instruction
        agent_instruction = f"""
You are executing the step '{step_def.name}' for the media project '{project.name}' (Brand: {project.brand}).

### Brand Guidelines
{brand_guide}

### Context & Input Assets
{context_data if context_data else "No input assets provided."}
"""

        if history_step.human_feedback:
            agent_instruction += f"\n\n### IMPORTANT - User Requested Revisions:\nThe user has requested modifications. Please adjust your output based on this feedback:\n{history_step.human_feedback}\n"

        agent_instruction += f"""
### Task Description
{step_def.description}

### Expected Output
Please output the content matching the required output format (Markdown or JSON).
"""

        if step_def.output_asset_type == "research":
            agent_instruction += RESEARCH_JSON_INSTRUCTION

        # Call worker Agent (a persona, or a department's manager)
        agent = self._resolve_agent(step_def.agent_role)

        # Check if output should be JSON (research dossiers, creative planning and SEO)
        is_json = step_def.output_asset_type in ["research", "visual_plan", "seo_package"]

        try:
            agent_output = agent.execute(agent_instruction, require_json=is_json)

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
                
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(agent_output)
                
                # Maintain the revision_log.md boilerplate
                rev_log_path = os.path.join(script_dir, "revision_log.md")
                if not os.path.exists(rev_log_path):
                    with open(rev_log_path, "w", encoding="utf-8") as f:
                        f.write("# Revision Log\n\n- Initial draft created.\n")
            elif step_def.output_asset_type in ["scene_breakdown", "shot_list", "clip_plan", "image_plan", "assets_collected", "voice_over", "edit_plan", "review_report", "sound_plan", "thumbnail_plan", "vlog_plan", "character_plan"]:
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
                    "review_report": "qa.md"
                }
                fn = mapping.get(step_def.output_asset_type, "storyboard.md")
                file_name = f"production/{fn}"
                file_path = os.path.join(project.get_project_dir(), file_name)
                
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
                
                if not os.path.exists(title_path):
                    with open(title_path, "w", encoding="utf-8") as f:
                        f.write(f"Title for {project.name}\n")
                if not os.path.exists(desc_path):
                    with open(desc_path, "w", encoding="utf-8") as f:
                        f.write(f"# Description\n\nOptimized description for {project.name}.\n")
                if not os.path.exists(tags_path):
                    with open(tags_path, "w", encoding="utf-8") as f:
                        f.write("buzzcaf, media, video, ai\n")
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

            
            # If step does NOT require approval, advance immediately
            if not step_def.requires_approval:
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
