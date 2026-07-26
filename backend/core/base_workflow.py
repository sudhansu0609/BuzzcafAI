
class BaseWorkflow:
    def __init__(self, name: str):
        self.name = name
        self.tasks = []

    def add_task(self, task):
        self.tasks.append(task)
