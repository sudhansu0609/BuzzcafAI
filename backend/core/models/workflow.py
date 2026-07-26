from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class WorkflowStep:
    name: str
    agent_role: str  # e.g., "ResearchAgent", "WriterAgent"
    description: str
    requires_approval: bool = False
    input_assets: List[str] = field(default_factory=list)  # asset keys required
    output_asset_type: Optional[str] = None  # asset key generated, e.g., "research"

@dataclass
class WorkflowDefinition:
    id: str
    name: str
    description: str
    steps: List[WorkflowStep] = field(default_factory=list)

    def get_step(self, step_name: str) -> Optional[WorkflowStep]:
        for step in self.steps:
            if step.name.lower() == step_name.lower():
                return step
        return None

    def get_next_step(self, current_step_name: str) -> Optional[WorkflowStep]:
        for i, step in enumerate(self.steps):
            if step.name.lower() == current_step_name.lower():
                if i + 1 < len(self.steps):
                    return self.steps[i + 1]
                break
        return None
