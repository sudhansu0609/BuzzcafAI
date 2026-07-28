# Buzzcaf AI - Custom Agents Registry Service
import os
import json
import uuid
from typing import List, Dict, Any, Optional

AGENTS_FILE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "projects",
    "custom_agents.json"
)

DEFAULT_AGENTS = [
    {
        "id": "agent-pm-01",
        "name": "Alex Vance",
        "role": "Lead Project Manager & Strategist",
        "avatarColor": "#7c3aed",
        "systemPrompt": "You are Alex, an elite YouTube Media Project Manager. Your goal is to guide content strategy, set channel milestones, and coordinate video production workflows with precision and high energy.",
        "modelProvider": "LM Studio (http://localhost:1234)",
        "modelName": "qwen2.5-coder-7b-instruct",
        "temperature": 0.7,
        "voiceId": "voice-alex-pm",
        "isPreset": True,
        "createdAt": "2026-07-28T00:00:00Z"
    },
    {
        "id": "agent-writer-02",
        "name": "Sarah Jenkins",
        "role": "Master Scriptwriter & Storyteller",
        "avatarColor": "#f43f5e",
        "systemPrompt": "You are Sarah, a veteran video scriptwriter specializing in viral hooks, 3-act story retention structures, and engaging audience storytelling. Write in natural Hinglish/English conversational tone.",
        "modelProvider": "Ollama (http://localhost:11434)",
        "modelName": "llama3.2:latest",
        "temperature": 0.8,
        "voiceId": "voice-sarah-writer",
        "isPreset": True,
        "createdAt": "2026-07-28T00:00:00Z"
    },
    {
        "id": "agent-seo-03",
        "name": "David Miller",
        "role": "CTR & SEO Specialist",
        "avatarColor": "#38bdf8",
        "systemPrompt": "You are David, a YouTube SEO & CTR Growth Strategist. You specialize in high-converting title hooks, keyword tag optimization, thumbnail concept testing, and algorithm ranking signals.",
        "modelProvider": "LM Studio (http://localhost:1234)",
        "modelName": "deepseek-r1-distill-llama-8b",
        "temperature": 0.5,
        "voiceId": "voice-david-seo",
        "isPreset": True,
        "createdAt": "2026-07-28T00:00:00Z"
    }
]

class AgentsRegistry:
    def __init__(self):
        self._ensure_storage()

    def _ensure_storage(self):
        os.makedirs(os.path.dirname(AGENTS_FILE_PATH), exist_ok=True)
        if not os.path.exists(AGENTS_FILE_PATH):
            with open(AGENTS_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_AGENTS, f, indent=2)

    def list_agents(self) -> List[Dict[str, Any]]:
        try:
            with open(AGENTS_FILE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_AGENTS

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agents = self.list_agents()
        for a in agents:
            if a.get("id") == agent_id:
                return a
        return None

    def save_agent(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        agents = self.list_agents()
        agent_id = agent_data.get("id")

        if agent_id:
            # Update existing
            for idx, a in enumerate(agents):
                if a.get("id") == agent_id:
                    agents[idx] = {**a, **agent_data}
                    self._write_all(agents)
                    return agents[idx]

        # Create new agent
        new_agent = {
            "id": f"custom-agent-{uuid.uuid4().hex[:8]}",
            "name": agent_data.get("name", "Custom Agent"),
            "role": agent_data.get("role", "AI Specialist"),
            "avatarColor": agent_data.get("avatarColor", "#a78bfa"),
            "systemPrompt": agent_data.get("systemPrompt", "You are a helpful AI assistant."),
            "modelProvider": agent_data.get("modelProvider", "LM Studio (http://localhost:1234)"),
            "modelName": agent_data.get("modelName", "default"),
            "temperature": float(agent_data.get("temperature", 0.7)),
            "voiceId": agent_data.get("voiceId", "default-voice"),
            "isPreset": False,
            "createdAt": agent_data.get("createdAt", "2026-07-28T00:00:00Z")
        }
        agents.append(new_agent)
        self._write_all(agents)
        return new_agent

    def delete_agent(self, agent_id: str) -> bool:
        agents = self.list_agents()
        filtered = [a for a in agents if a.get("id") != agent_id or a.get("isPreset", False)]
        if len(filtered) != len(agents):
            self._write_all(filtered)
            return True
        return False

    def _write_all(self, agents: List[Dict[str, Any]]):
        with open(AGENTS_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2)

agents_registry = AgentsRegistry()
