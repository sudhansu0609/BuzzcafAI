
class BaseProject:
    def __init__(self, project_id: str, title: str):
        self.project_id = project_id
        self.title = title
        self.metadata = {}
