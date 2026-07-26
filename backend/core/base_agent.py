
from abc import ABC, abstractmethod
import os
import logging
from typing import Optional, Any
from integrations.llm import LLMService
from core.context import Context
from core.result import Result

logger = logging.getLogger("spilled_coffee_ai.core.base_agent")

class BaseAgent(ABC):
    """Base class for every AI agent."""

    name: str = "BaseAgent"


    def __init__(self, agent_name: str, llm_service: Optional[LLMService] = None):
        self.agent_name = agent_name
        self.llm_service = llm_service or LLMService()
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        prompt_path = os.path.join(
            r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\prompts\agents",
            f"{self.agent_name}.md"
        )
        base_prompt = ""
        if not os.path.exists(prompt_path):
            logger.warning(f"System prompt file for agent {self.agent_name} not found at {prompt_path}. Using default.")
            base_prompt = f"You are the {self.agent_name} of Spilled Coffee AI Studio. Follow instructions accurately."
        else:
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    base_prompt = f.read()
            except Exception as e:
                logger.error(f"Error loading system prompt for {self.agent_name}: {e}")
                base_prompt = f"You are the {self.agent_name} of Spilled Coffee AI Studio."

        # If this is a Channel Strategist or Lead Agent, append the full 115-agent workforce directory
        if "strategist" in self.agent_name.lower() or self.agent_name in ["CEO", "COO", "CreativeDirectorAgent"]:
            try:
                from core.agent import agent_registry
                dept_map = {}
                for a_def in agent_registry.agents.values():
                    dept = a_def.department or "General"
                    dept_map.setdefault(dept, []).append(a_def.name)
                
                roster_lines = [
                    f"\n\n## Studio Workforce & Inter-Agent Operations",
                    f"You are the Lead Channel Strategist in Buzzcaf AI Studio. You have full strategic leadership and knowledge over all {len(agent_registry.agents)} specialized AI agents across 19 studio departments:",
                ]
                for dept, agents in sorted(dept_map.items()):
                    roster_lines.append(f"- **{dept}** ({len(agents)} agents): {', '.join(sorted(agents))}")
                
                roster_lines.append("\n### Inter-Agent Delegation Instructions:")
                roster_lines.append("1. You ARE AWARE of all these agents and can call any of them to execute specialized work for the creator.")
                roster_lines.append("2. When asked if you know all the other agents, CONFIRM that you manage all 115 agents across all 19 departments and list their departments.")
                roster_lines.append("3. To invoke a specialized agent and make it run live for a sub-task, output: `[INVOKE_AGENT: AgentName] Specific task instructions... [/INVOKE_AGENT]`")
                
                base_prompt += "\n".join(roster_lines)
            except Exception as e:
                logger.error(f"Error building workforce roster for {self.agent_name}: {e}")

        # Mandatory Hinglish Language Directive for All Agents & Topic/Script Generations
        hinglish_directive = (
            "\n\n### MANDATORY STUDIO LANGUAGE & SCRIPT DIRECTIVE (HINGLISH ENFORCEMENT):\n"
            "ALL generated topic titles, video hooks, outlines, full narration scripts, scene dialogues, "
            "B-roll suggestions, video ideas, and thumbnail text MUST be written in **Hinglish** (conversational, day-to-day Hindi "
            "expressed using English/Latin alphabet fonts).\n"
            "Guidelines:\n"
            "1. Use natural, engaging, everyday Hinglish as spoken in popular Hindi YouTube video essays & mystery documentaries.\n"
            "2. Example script style: 'Aaj ke episode mein hum baat karenge ek aisi unsolved mystery ki jo 1986 se sabko hairan kar rahi hai...'\n"
            "3. Example topic title: 'Bhangarh Fort Ka Wo Guard Jo Raat Ke 3 Baje Ghaayab Ho Gaya'\n"
            "4. NEVER output pure formal English scripts or Devanagari script. ALWAYS use Hinglish in Roman/English fonts!\n"
        )
        base_prompt += hinglish_directive

        return base_prompt

    def refresh_prompt(self):
        self.system_prompt = self._load_system_prompt()

    def execute(self, task: Any, require_json: bool = False) -> Any:
        try:
            from memory.memory import memory_system
            agent_memories = memory_system.retrieve(scope="agent", owner=self.agent_name, limit=6)
        except Exception:
            agent_memories = []

        memory_prompt_addon = ""
        if agent_memories:
            mem_items_text = []
            for m in agent_memories:
                content_str = json.dumps(m.content) if isinstance(m.content, (dict, list)) else str(m.content)
                mem_items_text.append(f"- [{m.updated[:19]}] {content_str}")
            memory_prompt_addon = "\n\n### Persistent Agent Memory Context (Retrieved Memory Logs):\n" + "\n".join(mem_items_text)

        if isinstance(task, Context):
            user_prompt = task.memory.get("user_prompt", "") or task.knowledge.get("user_prompt", "")
            self.refresh_prompt()
            effective_system_prompt = self.system_prompt + memory_prompt_addon
            logger.info(f"Agent '{self.agent_name}' is executing task with memory context...")
            raw_output = self.llm_service.generate_text(
                system_prompt=effective_system_prompt,
                user_prompt=user_prompt,
                require_json=require_json
            )
            try:
                from memory.memory import memory_system
                memory_system.save(
                    scope="agent",
                    owner=self.agent_name,
                    tags=["execution"],
                    content={"task_summary": user_prompt[:200], "result_snippet": str(raw_output)[:300]}
                )
            except Exception as e:
                logger.error(f"Error saving agent memory: {e}")
            return Result(success=True, output=raw_output, message="Successfully executed task.")

        if isinstance(task, dict):
            user_prompt = task.get("user_prompt", "")
            require_json = task.get("require_json", require_json)
        else:
            user_prompt = str(task)
            
        self.refresh_prompt()
        effective_system_prompt = self.system_prompt + memory_prompt_addon
        logger.info(f"Agent '{self.agent_name}' is executing task with memory context...")
        raw_output = self.llm_service.generate_text(
            system_prompt=effective_system_prompt,
            user_prompt=user_prompt,
            require_json=require_json
        )
        try:
            from memory.memory import memory_system
            memory_system.save(
                scope="agent",
                owner=self.agent_name,
                tags=["execution"],
                content={"task_summary": user_prompt[:200], "result_snippet": str(raw_output)[:300]}
            )
        except Exception as e:
            logger.error(f"Error saving agent memory: {e}")

        return raw_output



