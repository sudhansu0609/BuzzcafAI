
from abc import ABC, abstractmethod
import os
import json
import logging
from typing import Any, Dict, List, Optional
from integrations.llm import LLMService
from core.context import Context
from core.paths import AGENTS_DIR
from core.result import Result

logger = logging.getLogger("spilled_coffee_ai.core.base_agent")

class BaseAgent(ABC):
    """Base class for every AI agent."""

    name: str = "BaseAgent"


    def __init__(self, agent_name: str, llm_service: Optional[LLMService] = None):
        self.agent_name = agent_name
        self.llm_service = llm_service or LLMService()
        self.model_tier, self.temperature = self._load_model_settings()
        self.system_prompt = self._load_system_prompt()

    def _load_model_settings(self):
        """The tier and temperature this persona declares (roadmap v9, F1/F2).

        A persona with no frontmatter for them - or no file at all - runs on the
        strong tier at the studio default temperature.
        """
        try:
            from core.agent import agent_registry

            definition = agent_registry.get(self.agent_name)
        except Exception:
            definition = None
        if not definition:
            return "strong", 0.7
        return definition.model_tier, definition.temperature

    def _load_system_prompt(self, hinglish: bool = True) -> str:
        prompt_path = os.path.join(AGENTS_DIR, f"{self.agent_name}.md")
        base_prompt = ""
        if not os.path.exists(prompt_path):
            logger.warning(f"System prompt file for agent {self.agent_name} not found at {prompt_path}. Using default.")
            base_prompt = f"You are the {self.agent_name} of Buzzcaf AI Studio. Follow instructions accurately."
        else:
            try:
                with open(prompt_path, "r", encoding="utf-8") as f:
                    base_prompt = f.read()
            except Exception as e:
                logger.error(f"Error loading system prompt for {self.agent_name}: {e}")
                base_prompt = f"You are the {self.agent_name} of Buzzcaf AI Studio."

        # If this is a Channel Strategist or Lead Agent, append the full workforce
        # directory. Counts come from the registry: hard-coded ones went stale the
        # moment a persona was added or merged (roadmap v9, A4).
        if "strategist" in self.agent_name.lower() or self.agent_name in ["CEO", "COO", "CreativeDirectorAgent"]:
            try:
                from core.agent import agent_registry
                dept_map = {}
                for a_def in agent_registry.agents.values():
                    dept = a_def.department or "General"
                    dept_map.setdefault(dept, []).append(a_def.name)

                total = len(agent_registry.agents)
                dept_count = len(dept_map)
                roster_lines = [
                    f"\n\n## Studio Workforce & Inter-Agent Operations",
                    f"You are the Lead Channel Strategist in Buzzcaf AI Studio. You have full strategic leadership and knowledge over all {total} specialized AI agents across {dept_count} studio departments:",
                ]
                for dept, agents in sorted(dept_map.items()):
                    roster_lines.append(f"- **{dept}** ({len(agents)} agents): {', '.join(sorted(agents))}")

                roster_lines.append("\n### Inter-Agent Delegation Instructions:")
                roster_lines.append("1. You ARE AWARE of all these agents and can call any of them to execute specialized work for the creator.")
                roster_lines.append(f"2. When asked if you know all the other agents, CONFIRM that you manage all {total} agents across all {dept_count} departments and list their departments.")
                roster_lines.append("3. To invoke a specialized agent and make it run live for a sub-task, output: `[INVOKE_AGENT: AgentName] Specific task instructions... [/INVOKE_AGENT]`")

                base_prompt += "\n".join(roster_lines)
            except Exception as e:
                logger.error(f"Error building workforce roster for {self.agent_name}: {e}")

        # Hinglish directive for content generation (workflow steps produce
        # titles, hooks and scripts). The Studio Assistant chat passes
        # hinglish=False and answers in the creator's own language instead.
        if not hinglish:
            return base_prompt

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

    def execute_messages(
        self,
        messages: List[Dict[str, str]],
        system_extra: str = "",
        hinglish: bool = False,
        require_json: bool = False,
    ) -> str:
        """
        A real multi-turn chat: persona (+ roster for strategists) as the system
        prompt, `system_extra` appended once, and the turns passed as messages.
        Memory is the caller's business - the Studio Assistant injects only the
        relevant items - so nothing is auto-injected or auto-saved here.
        """
        system_prompt = self._load_system_prompt(hinglish=hinglish) + (system_extra or "")
        logger.info(f"Agent '{self.agent_name}' is answering a chat turn ({len(messages)} messages)...")
        return self.llm_service.generate_chat(
            system_prompt=system_prompt, messages=messages, require_json=require_json,
            tier=self.model_tier, temperature=self.temperature,
        )

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
                require_json=require_json,
                tier=self.model_tier,
                temperature=self.temperature,
            )
            try:
                from memory.memory import memory_system
                memory_system.save(
                    scope="agent",
                    owner=self.agent_name,
                    tags=["execution"],
                    content={"task_summary": user_prompt[:600], "result_snippet": str(raw_output)[:2000]}
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
            require_json=require_json,
            tier=self.model_tier,
            temperature=self.temperature,
        )
        try:
            from memory.memory import memory_system
            memory_system.save(
                scope="agent",
                owner=self.agent_name,
                tags=["execution"],
                content={"task_summary": user_prompt[:600], "result_snippet": str(raw_output)[:2000]}
            )
        except Exception as e:
            logger.error(f"Error saving agent memory: {e}")

        return raw_output



