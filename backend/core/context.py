
from dataclasses import dataclass, field

@dataclass
class Context:
    project_id: str
    workflow: str
    memory: dict = field(default_factory=dict)
    knowledge: dict = field(default_factory=dict)
