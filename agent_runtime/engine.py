from core.base_agent import BaseAgent
from core.context import Context
from core.result import Result

class AgentRuntime:
    def execute(self, agent: BaseAgent, context: Context) -> Result:
        return agent.execute(context)
