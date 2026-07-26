import os
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime

@dataclass
class StepExecution:
    step_name: str
    agent_name: str
    status: str  # "pending", "running", "paused_for_approval", "completed", "failed"
    started_at: str
    completed_at: Optional[str] = None
    output_files: Dict[str, str] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    human_feedback: Optional[str] = None

@dataclass
class Project:
    id: str
    name: str
    brand: str
    workflow_name: str
    status: str = "active"  # "active", "completed", "archived"
    current_step: str = "Idea"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    steps_history: List[StepExecution] = field(default_factory=list)
    assets: Dict[str, str] = field(default_factory=dict)  # step_name -> file_path relative to project folder

    def get_project_dir(self) -> str:
        from core.config import config_manager
        projects_dir = config_manager.get("PROJECTS_PATH")
        return os.path.join(projects_dir, self.id)

    def save(self):
        project_dir = self.get_project_dir()
        os.makedirs(project_dir, exist_ok=True)
        file_path = os.path.join(project_dir, "project.json")
        self.updated_at = datetime.now().isoformat()
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=4)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        steps_history_data = data.pop("steps_history", [])
        steps_history = []
        for s in steps_history_data:
            steps_history.append(StepExecution(**s))
        return cls(steps_history=steps_history, **data)

    @classmethod
    def load(cls, project_id: str) -> "Project":
        from core.config import config_manager
        projects_dir = config_manager.get("PROJECTS_PATH")
        file_path = os.path.join(projects_dir, project_id, "project.json")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Project config file not found: {file_path}")
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

