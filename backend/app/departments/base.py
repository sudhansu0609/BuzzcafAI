import logging
from typing import Dict, List, Any, Optional
from core.agent import AgentFactory, agent_registry, BaseAgent
from integrations.llm import LLMService

logger = logging.getLogger("spilled_coffee_ai.departments.base")

class Department:
    """Base class for department execution engines."""

    def __init__(
        self,
        name: str,
        manager_role: str,
        specialist_roles: List[str],
        llm_service: Optional[LLMService] = None
    ):
        self.name = name
        self.manager_role = manager_role
        self.specialist_roles = specialist_roles
        self.llm_service = llm_service or LLMService()
        self.manager_agent: Optional[BaseAgent] = None
        self.specialists: Dict[str, BaseAgent] = {}
        self._initialize_agents()

    def _initialize_agents(self):
        """Instantiates department manager and specialist agents."""
        if self.manager_role:
            self.manager_agent = AgentFactory.get_agent(self.manager_role, self.llm_service)
            logger.info(f"Department [{self.name}]: Initialized Manager '{self.manager_role}'")
        for role in self.specialist_roles:
            self.specialists[role.lower()] = AgentFactory.get_agent(role, self.llm_service)
            logger.info(f"Department [{self.name}]: Initialized Specialist '{role}'")

    def get_agent(self, role_name: str) -> Optional[BaseAgent]:
        """Fetches an agent by role name."""
        key = role_name.lower().strip()
        if self.manager_role and key == self.manager_role.lower().strip():
            return self.manager_agent
        if key in self.specialists:
            return self.specialists[key]
        # Fallback dynamic retrieval
        return AgentFactory.get_agent(role_name, self.llm_service)

    def execute_task(self, role_name: str, task: Any, require_json: bool = False) -> Any:
        """Executes a task on the targeted agent."""
        agent = self.get_agent(role_name)
        if not agent:
            raise ValueError(f"Agent '{role_name}' not found in department '{self.name}'.")
        return agent.execute(task, require_json=require_json)

    def list_agents(self) -> List[str]:
        """Lists all agent role names in this department."""
        agents = []
        if self.manager_role:
            agents.append(self.manager_role)
        agents.extend(self.specialist_roles)
        return agents
