import os
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.models.project import Project
from runtime.workflow import WorkflowEngine
from integrations.llm import load_config, save_config
from knowledge.assets import AssetService

app = FastAPI(title="Spilled Coffee AI Studio Dashboard")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECTS_DIR = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\projects"
engine = WorkflowEngine()
asset_service = AssetService()

import logging
from collections import defaultdict

class InMemoryLogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.logs = defaultdict(list)

    def emit(self, record):
        try:
            msg = self.format(record)
            project_id = getattr(record, "project_id", "N/A")
            if project_id == "N/A" and active_executions:
                for pid in active_executions:
                    self.logs[pid].append(msg)
            elif project_id != "N/A":
                self.logs[project_id].append(msg)
        except Exception:
            pass

log_handler = InMemoryLogHandler()
log_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] - %(message)s'))
logging.getLogger().addHandler(log_handler)

active_executions = set()


# Pydantic Schemas
class ProjectCreateSchema(BaseModel):
    name: str
    brand: str
    workflow_name: str

class SettingsSchema(BaseModel):
    gemini_api_key: str
    gemini_model: str
    openai_api_key: Optional[str] = ""
    openai_model: Optional[str] = "gpt-4o-mini"
    lm_studio_url: str
    lm_studio_model: str
    prefer_gemini: bool
    selected_provider: Optional[str] = "gemini"


class ExecuteStepSchema(BaseModel):
    feedback: Optional[str] = None

class AssetRegisterSchema(BaseModel):
    title: str
    type: str
    tags: List[str]
    file_path: str
    source: Optional[str] = "internal"
    license: Optional[str] = "Royalty Free"
    status: Optional[str] = "active"
    project_id: Optional[str] = None

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/projects")
def projects():
    return list_projects()

@app.get("/api/brands")
def get_brands():
    return ["Beyond3Baje", "Khayal3Baje", "Spilled Coffee Studio", "Spilled Coffee: After Dark", "Spilled Coffee After Dark", "Life3Baje"]

@app.get("/api/assets")
def get_assets(type: Optional[str] = None, tag: Optional[str] = None, query: Optional[str] = None):
    return asset_service.query_assets(asset_type=type, tag=tag, query_string=query)

@app.post("/api/assets")
def register_asset(payload: AssetRegisterSchema):
    return asset_service.register_asset(
        title=payload.title,
        asset_type=payload.type,
        tags=payload.tags,
        file_path=payload.file_path,
        source=payload.source,
        license_info=payload.license,
        status=payload.status,
        project_id=payload.project_id
    )


@app.get("/api/settings")
def get_settings():
    return load_config()

@app.post("/api/settings")
def update_settings(settings: SettingsSchema):
    save_config(settings.model_dump())
    engine.llm_service.reload_config()
    return {"status": "success", "message": "Settings updated successfully."}

@app.get("/api/workflows")
def get_workflows():
    engine.load_workflows()
    return [
        {
            "id": wf.id,
            "name": wf.name,
            "description": wf.description,
            "steps": [
                {
                    "name": s.name,
                    "agent_role": s.agent_role,
                    "description": s.description,
                    "requires_approval": s.requires_approval
                } for s in wf.steps
            ]
        } for wf in engine.workflows.values()
    ]

@app.get("/api/projects")
def list_projects():
    if not os.path.exists(PROJECTS_DIR):
        os.makedirs(PROJECTS_DIR, exist_ok=True)
        return []
    
    projects = []
    for pid in os.listdir(PROJECTS_DIR):
        p_dir = os.path.join(PROJECTS_DIR, pid)
        if os.path.isdir(p_dir):
            try:
                p = Project.load(pid)
                projects.append(p.to_dict())
            except Exception as e:
                # Log and skip corrupted projects
                continue
    # Sort by created_at descending
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return projects

from executive.project import project_manager

@app.post("/api/projects")
def create_project(payload: ProjectCreateSchema):
    # Load workflow to check first step
    wf = engine.get_workflow(payload.workflow_name)
    if not wf:
        raise HTTPException(status_code=400, detail=f"Workflow '{payload.workflow_name}' not found.")
        
    try:
        project = project_manager.create_project(
            name=payload.name,
            brand=payload.brand,
            workflow_name=payload.workflow_name
        )
        return project.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))



@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    try:
        project = Project.load(project_id)
        return project.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

@app.post("/api/projects/{project_id}/execute")
def execute_project_step(project_id: str, payload: ExecuteStepSchema = None):
    feedback = payload.feedback if payload else None
    active_executions.add(project_id)
    log_handler.logs[project_id] = [f"Starting execution of workflow step at {datetime.now().isoformat()}..."]
    try:
        project = engine.execute_next(project_id, user_feedback=feedback)
        # Add final agent logs if any
        if project.steps_history:
            last_step = project.steps_history[-1]
            for step_log in last_step.logs:
                if step_log not in log_handler.logs[project_id]:
                    log_handler.logs[project_id].append(step_log)
        return project.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")
    except Exception as e:
        log_handler.logs[project_id].append(f"[ERROR] Execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Execution error: {str(e)}")
    finally:
        active_executions.discard(project_id)

@app.get("/api/projects/{project_id}/logs")
def get_project_execution_logs(project_id: str):
    return log_handler.logs.get(project_id, ["No active logs found for this project."])

@app.get("/api/projects/{project_id}/asset/{asset_name}")
def get_project_asset(project_id: str, asset_name: str):
    try:
        project = Project.load(project_id)
        asset_file = project.assets.get(asset_name)
        if not asset_file:
            raise HTTPException(status_code=404, detail="Asset not generated yet")
            
        file_path = os.path.join(project.get_project_dir(), asset_file)
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="Asset file missing on disk")
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check if json
        if asset_file.endswith(".json"):
            try:
                return json.loads(content)
            except:
                pass
        return {"content": content}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Project not found")

from core.diagnostics import Diagnostics

@app.get("/api/diagnostics")
def get_diagnostics():
    return Diagnostics.get_report()


# Serve UI static files

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    print(f"WARNING: UI static folder not found at: {static_dir}")
