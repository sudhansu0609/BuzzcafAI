
from abc import ABC

class BaseDepartment(ABC):
    """Groups related agents and workflows."""

    def __init__(self, name: str):
        self.name = name
        self.agents = {}
