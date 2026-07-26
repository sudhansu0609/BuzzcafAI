import os
import logging
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from core.markdown import markdown_loader

logger = logging.getLogger("buzzcaf_ai.core.agent")

AGENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "agents")

class AgentDefinition(BaseModel):
    name: str
    department: str
    role: str
    inputs: List[str] = Field(default_factory=list)
    outputs: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    version: str = "1.0.0"
    prompt_filepath: Optional[str] = None

class AgentRegistry:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AgentRegistry, cls).__new__(cls)
            cls._instance.agents: Dict[str, AgentDefinition] = {}
            cls._instance.agent_cache: Dict[str, Any] = {} # lazy cache
            cls._instance.discover_agents()
        return cls._instance

    def discover_agents(self):
        """Discovers agents dynamically from prompts/agents/ directory."""
        self.agents.clear()
        if not os.path.exists(AGENTS_DIR):
            os.makedirs(AGENTS_DIR, exist_ok=True)
            return

        for f_name in os.listdir(AGENTS_DIR):
            if f_name.endswith(".md"):
                f_path = os.path.join(AGENTS_DIR, f_name)
                try:
                    # Leverage MarkdownLoader to parse frontmatter
                    doc = markdown_loader.load(f_path)
                    fm = doc.frontmatter
                    
                    if "name" in fm:
                        # Translate frontmatter types
                        def clean_list(val):
                            if isinstance(val, list):
                                return val
                            if isinstance(val, str):
                                # simple string list parse e.g. ["a", "b"]
                                cleaned = val.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
                                return [item.strip() for item in cleaned.split(",") if item.strip()]
                            return []

                        agent = AgentDefinition(
                            name=fm["name"],
                            department=fm.get("department", "General"),
                            role=fm.get("role", ""),
                            inputs=clean_list(fm.get("inputs")),
                            outputs=clean_list(fm.get("outputs")),
                            dependencies=clean_list(fm.get("dependencies")),
                            permissions=clean_list(fm.get("permissions")),
                            version=fm.get("version", "1.0.0"),
                            prompt_filepath=f_path
                        )
                        self.validate(agent)
                        self.agents[agent.name.lower()] = agent
                        logger.info(f"AgentRegistry: Discovered and registered agent '{agent.name}'")
                except Exception as e:
                    logger.error(f"AgentRegistry: Failed to load agent from {f_name}: {e}")

    def register(self, agent: AgentDefinition):
        self.validate(agent)
        self.agents[agent.name.lower()] = agent
        logger.info(f"AgentRegistry: Manually registered agent '{agent.name}'")

    def unregister(self, name: str):
        key = name.lower()
        if key in self.agents:
            del self.agents[key]
            if key in self.agent_cache:
                del self.agent_cache[key]
            logger.info(f"AgentRegistry: Unregistered agent '{name}'")

    def get(self, name: str) -> Optional[AgentDefinition]:
        """Lazy load or fetch from cache if already populated."""
        key = name.lower()
        if key in self.agent_cache:
            return self.agent_cache[key]
        if key in self.agents:
            agent = self.agents[key]
            self.agent_cache[key] = agent
            return agent
        return None

    def list(self) -> List[AgentDefinition]:
        return list(self.agents.values())

    def validate(self, agent: AgentDefinition):
        """Validate required fields, dependencies, and duplicates."""
        if not agent.name or not agent.department or not agent.role:
            raise ValueError(f"Agent validation error: Missing required fields (name, department, role).")
            
        # Verify dependency exists if we are not bootstrapping
        # (Ignore dependencies during bootstrapping or if they correspond to known roles)
        known_roles = ["ceo", "researchagent", "writeragent", "editoragent", "creativedirectoragent", "seomanageragent"]
        for dep in agent.dependencies:
            dep_key = dep.lower()
            if dep_key not in self.agents and dep_key not in known_roles:
                logger.warning(f"Agent '{agent.name}' has unresolved dependency: '{dep}'")

agent_registry = AgentRegistry()

from core.base_agent import BaseAgent
from integrations.llm import LLMService, clean_json_response
import json

class CEOAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("CEO", llm_service)

    def plan_next_step(self, project_details: str, current_step: str, history: str) -> Dict[str, Any]:
        prompt = f"""
Analyze the project details and history. Recommend the task details for the next step.

### Project Details
{project_details}

### Current Active Step
{current_step}

### Previous Execution History
{history}

Respond in the required JSON format containing:
- "task_objective"
- "target_agent"
- "context_files"
- "constraints"
"""
        raw_output = self.execute(prompt, require_json=True)
        try:
            cleaned = clean_json_response(raw_output)
            return json.loads(cleaned)
        except Exception as e:
            logger.error(f"CEOAgent failed to parse task plan JSON: {e}. Output was: {raw_output}")
            return {
                "task_objective": f"Execute standard {current_step} step.",
                "target_agent": f"{current_step}Agent",
                "context_files": [],
                "constraints": ["Follow brand standards."]
            }

class ResearchAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("ResearchAgent", llm_service)

    def execute(self, task: Any, require_json: bool = False) -> str:
        return super().execute(task, require_json)

class WriterAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("WriterAgent", llm_service)

    def execute(self, task: Any, require_json: bool = False) -> str:
        return super().execute(task, require_json)

class EditorAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("EditorAgent", llm_service)

    def execute(self, task: Any, require_json: bool = False) -> str:
        return super().execute(task, require_json)

class CreativeDirectorAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("CreativeDirectorAgent", llm_service)

    def execute(self, task: Any, require_json: bool = False) -> str:
        return super().execute(task, require_json)

class SEOManagerAgent(BaseAgent):
    def __init__(self, llm_service: Optional[LLMService] = None):
        super().__init__("SEOManagerAgent", llm_service)

    def execute(self, task: Any, require_json: bool = False) -> str:
        return super().execute(task, require_json)

class AgentFactory:
    @staticmethod
    def get_agent(agent_role: str, llm_service: Optional[LLMService] = None) -> BaseAgent:
        role_map = {
            "ceo": CEOAgent,
            "researchagent": ResearchAgent,
            "writeragent": WriterAgent,
            "editoragent": EditorAgent,
            "creativedirectoragent": CreativeDirectorAgent,
            "seomanageragent": SEOManagerAgent
        }
        normalized = agent_role.lower().strip()
        if normalized in role_map:
            return role_map[normalized](llm_service)

        # Look up registered agent definition for exact file name matching
        def_obj = agent_registry.get(normalized)
        target_name = def_obj.name if def_obj else agent_role

        class GenericAgent(BaseAgent):
            def __init__(self, name: str, service: Optional[LLMService] = None):
                super().__init__(name, service)

            def execute(self, task: Any, require_json: bool = False) -> str:
                return super().execute(task, require_json)

        return GenericAgent(target_name, llm_service)


