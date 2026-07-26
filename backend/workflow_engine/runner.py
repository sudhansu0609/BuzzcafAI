from runtime.workflow import WorkflowEngine

class WorkflowRunner:
    """Wraps WorkflowEngine for running workflow steps."""
    def __init__(self):
        self.engine = WorkflowEngine()

    def run_next_step(self, project_id: str):
        return self.engine.execute_next(project_id)
