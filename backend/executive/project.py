import os
import json
import logging
import datetime
import shutil
from typing import Dict, Any, List, Optional
from core.models.project import Project

logger = logging.getLogger("spilled_coffee_ai.core.project")

PROJECTS_DIR = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\projects"

REQUIRED_FOLDERS = [
    "research", "outline", "script", "storyboard", "visuals", 
    "clips", "voice", "editing", "seo", "publish", "analytics", "archive"
]

class ProjectManager:
    def __init__(self, projects_dir: Optional[str] = None):
        self.projects_dir = projects_dir or PROJECTS_DIR
        os.makedirs(self.projects_dir, exist_ok=True)

    def generate_project_id(self, brand: str, name: str) -> str:
        """Enforce standard: YYYY-MM-DD_Channel_ShortTitle"""
        date_str = datetime.date.today().isoformat()
        brand_clean = brand.replace(" ", "")
        
        # Format ShortTitle as PascalCase with alphanumeric only
        words = [w.capitalize() for w in name.split() if w]
        title_clean = "".join([c for c in "".join(words) if c.isalnum()])
        
        return f"{date_str}_{brand_clean}_{title_clean}"

    def create_project(self, name: str, brand: str, workflow_name: str) -> Project:
        project_id = self.generate_project_id(brand, name)
        project_path = os.path.join(self.projects_dir, project_id)
        
        # Enforce unique project ID check
        if os.path.exists(project_path):
            raise ValueError(f"Project ID conflict: A project directory already exists at {project_path}")
            
        os.makedirs(project_path, exist_ok=True)
        
        # Create full folder structure templates (ProjectTemplate.md)
        for folder in REQUIRED_FOLDERS:
            folder_path = os.path.join(project_path, folder)
            os.makedirs(folder_path, exist_ok=True)
            
        project = Project(
            id=project_id,
            name=name,
            brand=brand,
            workflow_name=workflow_name,
            current_step="Research",
            status="active"
        )
        
        # Save project metadata
        project.save()
        logger.info(f"ProjectManager: Successfully initialized folders and metadata for project {project_id}")
        return project

    def validate_project(self, project_id: str) -> bool:
        """Verify: Required folders, metadata config, workflow assignment."""
        project_path = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(project_path):
            logger.warning(f"Validation failed: Project directory missing: {project_path}")
            return False
            
        # Check required folder structures
        for folder in REQUIRED_FOLDERS:
            folder_path = os.path.join(project_path, folder)
            if not os.path.exists(folder_path):
                logger.warning(f"Validation failed: Required project folder missing: {folder_path}")
                return False
                
        # Check metadata
        meta_file = os.path.join(project_path, "project.json")
        if not os.path.exists(meta_file):
            logger.warning(f"Validation failed: Metadata project.json missing.")
            return False
            
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "id" not in data or "brand" not in data or "workflow_name" not in data:
                logger.warning("Validation failed: Metadata lacks required keys.")
                return False
        except Exception as e:
            logger.warning(f"Validation failed: Corrupted project.json: {e}")
            return False
            
        return True

    def archive_project(self, project_id: str):
        """Move project to archive state."""
        try:
            project = Project.load(project_id)
            project.status = "archived"
            project.current_step = "Archived"
            project.save()
            logger.info(f"ProjectManager: Project {project_id} successfully moved to archived status.")
        except Exception as e:
            logger.error(f"Error archiving project {project_id}: {e}")
            raise e
            
project_manager = ProjectManager()
