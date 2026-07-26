from executive.project import project_manager as core_project_manager

class ProjectManager:
    def __init__(self):
        self.manager = core_project_manager

    def create_project(self, name: str, brand: str, workflow_name: str):
        return self.manager.create_project(name, brand, workflow_name)
