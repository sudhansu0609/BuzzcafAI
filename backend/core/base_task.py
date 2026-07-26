
from dataclasses import dataclass, field
from typing import Any

@dataclass
class BaseTask:
    id: str
    name: str
    payload: dict[str, Any] = field(default_factory=dict)
