import os
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from core.models.project import Project, StepExecution
from core.models.workflow import WorkflowDefinition, WorkflowStep
from core.agent import AgentFactory
from integrations.llm import LLMService

logger = logging.getLogger("buzzcaf_ai.engine.workflow")

WORKFLOWS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "workflows")
CHANNELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "channels")

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

        # Call worker Agent
        agent = AgentFactory.get_agent(step_def.agent_role, self.llm_service)
        
        # Check if output should be JSON (Creative Planning and SEO steps generate JSON output)
        is_json = step_def.output_asset_type in ["visual_plan", "seo_package"]
        
        try:
            agent_output = agent.execute(agent_instruction, require_json=is_json)
            
            # Save output asset file
            ext = "json" if is_json else "md"
            file_name = f"{step_def.name.lower().replace(' ', '_')}.{ext}"
            file_path = os.path.join(project.get_project_dir(), file_name)
            
            if step_def.output_asset_type == "research":
                research_dir = os.path.join(project.get_project_dir(), "research")
                os.makedirs(research_dir, exist_ok=True)
                
                # Main dossier content goes to summary
                with open(os.path.join(research_dir, "summary.md"), "w", encoding="utf-8") as f:
                    f.write(agent_output)
                
                # Write placeholder files to satisfy the output schema structure
                sections = {
                    "timeline.md": "Timeline",
                    "facts.md": "Factual Claims",
                    "sources.md": "Sources",
                    "media.md": "Visual References",
                    "unanswered_questions.md": "Unanswered Questions"
                }
                for fn, title in sections.items():
                    with open(os.path.join(research_dir, fn), "w", encoding="utf-8") as f:
                        f.write(f"# {title}\n\nInformation gathered from research.\n")
                
                file_name = "research/summary.md"
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
            # Enforce Error Handling: Categorize error
            error_class = "BLOCKING"
            error_msg = str(e)
            
            if "timeout" in error_msg.lower() or "connection" in error_msg.lower() or "429" in error_msg:
                error_class = "RETRYABLE"
            elif "not found" in error_msg.lower() or "missing" in error_msg.lower():
                error_class = "RECOVERABLE"
            elif "approval" in error_msg.lower() or "feedback" in error_msg.lower():
                error_class = "HUMAN_INTERVENTION_REQUIRED"
                
            log_message = f"[{error_class}] Error executing agent step '{step_def.name}': {error_msg}"
            logger.error(log_message)
            
            history_step.status = "failed"
            history_step.logs.append(log_message)
            project.save()
            raise e

        
        project.save()
        return project
