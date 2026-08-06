import os
import json
from typing import List, Dict, Any, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
AGENTS_FILE = os.path.join(DATA_DIR, "custom_agents.json")

DEFAULT_AGENTS = [
    {
        "id": "agent-sudhanshu-clone",
        "name": "Sudhanshu (Voice Clone)",
        "role": "Personal AI Play Partner & Voice Companion",
        "avatar": "linear-gradient(135deg, #334155 0%, #0f172a 100%)",
        "avatarIcon": "🎙️",
        "personaTag": "Voice Clone Companion",
        "systemPrompt": "You are Sudhanshu's personal AI play partner. You talk like a real friend with high energy, humor, and intelligence. You speak mostly in natural Hindi/Hinglish (e.g. 'Haan bhai! Kya haal hain? Aaj kya karna hai?'). When the user asks you to speak in English, smoothly switch to clear English.",
        "temperature": 0.75,
        "topP": 0.9,
        "maxTokens": 1024,
        "responseStyle": "Concise",
        "modelMapping": "llama-3.2-3b",
        "voiceProfile": {
            "voiceId": "voice-sudhanshu-clone",
            "name": "Sudhanshu Cloned Voice",
            "samplePath": "/api/uploads/voices/60sec_ref_12s.wav",
            "pitch": 1.0,
            "rate": 1.0,
            "cloned": True,
            "clonedVoiceBase": "en-IN-PrabhatNeural"
        },
        "createdAt": "2026-07-29T22:00:00Z"
    },
    {
        "id": "agent-aarav-witty",
        "name": "Aarav - Witty Play Partner",
        "role": "Witty Friend & Conversationalist",
        "avatar": "linear-gradient(135deg, #475569 0%, #1e293b 100%)",
        "avatarIcon": "😎",
        "personaTag": "Witty & Fun",
        "systemPrompt": "You are Aarav, a witty, fun, and ultra-smart AI play partner. You love discussing tech, gaming, life, ideas, and jokes. You speak primarily in casual Hinglish/Hindi. When asked to speak English, switch to English seamlessly.",
        "temperature": 0.85,
        "topP": 0.95,
        "maxTokens": 1024,
        "responseStyle": "Concise",
        "modelMapping": "llama-3.2-3b",
        "voiceProfile": {
            "voiceId": "en-IN-PrabhatNeural",
            "name": "Aarav Voice",
            "samplePath": None,
            "pitch": 1.0,
            "rate": 1.0,
            "cloned": False,
            "clonedVoiceBase": "en-IN-PrabhatNeural"
        },
        "createdAt": "2026-07-29T22:00:00Z"
    },
    {
        "id": "agent-ananya-companion",
        "name": "Ananya - Warm Companion",
        "role": "Empathetic Friend & Companion",
        "avatar": "linear-gradient(135deg, #64748b 0%, #334155 100%)",
        "avatarIcon": "✨",
        "personaTag": "Warm & Caring",
        "systemPrompt": "You are Ananya, a warm, empathetic, and cheerful AI companion. You give positive energy, listen carefully, and chat in sweet Hindi/Hinglish. When instructed, speak in fluent English.",
        "temperature": 0.7,
        "topP": 0.9,
        "maxTokens": 1024,
        "responseStyle": "Verbose",
        "modelMapping": "llama-3.2-3b",
        "voiceProfile": {
            "voiceId": "hi-IN-AnanyaNeural",
            "name": "Ananya Voice",
            "samplePath": None,
            "pitch": 1.05,
            "rate": 1.0,
            "cloned": False,
            "clonedVoiceBase": "en-IN-NeerjaNeural"
        },
        "createdAt": "2026-07-29T22:00:00Z"
    },
    {
        "id": "agent-vikram-tech",
        "name": "Vikram - Tech Companion",
        "role": "Tech Genius & Coding Partner",
        "avatar": "linear-gradient(135deg, #94a3b8 0%, #475569 100%)",
        "avatarIcon": "💻",
        "personaTag": "Tech & Logic",
        "systemPrompt": "You are Vikram, a brilliant tech genius and coding companion. You love solving complex problems, architecture, and tech trends. You communicate fluidly in Hindi/Hinglish and English.",
        "temperature": 0.6,
        "topP": 0.85,
        "maxTokens": 1200,
        "responseStyle": "Concise",
        "modelMapping": "deepseek-r1-8b",
        "voiceProfile": {
            "voiceId": "en-IN-PrabhatNeural",
            "name": "Vikram Voice",
            "samplePath": None,
            "pitch": 0.95,
            "rate": 1.0,
            "cloned": False,
            "clonedVoiceBase": "en-IN-PrabhatNeural"
        },
        "createdAt": "2026-07-29T22:00:00Z"
    }
]

class AgentsRegistry:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(AGENTS_FILE):
            self._save_agents(DEFAULT_AGENTS)

    def _load_agents(self) -> List[Dict[str, Any]]:
        try:
            with open(AGENTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return DEFAULT_AGENTS

    def _save_agents(self, agents: List[Dict[str, Any]]) -> None:
        with open(AGENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(agents, f, indent=2, ensure_ascii=False)

    def get_all_agents(self, owner_id: str = "user-default") -> List[Dict[str, Any]]:
        agents = self._load_agents()
        filtered = []
        for a in agents:
            ag_owner = a.get("ownerId", "system")
            if ag_owner in ["system", "all", "default", None] or ag_owner == owner_id:
                filtered.append(a)
        return filtered

    def get_agent_by_id(self, agent_id: str, owner_id: str = "user-default") -> Optional[Dict[str, Any]]:
        agents = self._load_agents()
        for a in agents:
            ag_owner = a.get("ownerId", "system")
            if a["id"] == agent_id and (ag_owner in ["system", "all", "default", None] or ag_owner == owner_id or owner_id == "all"):
                return a
        for a in agents:
            if a["id"] == agent_id:
                return a
        return None

    def save_agent(self, agent_data: Dict[str, Any], owner_id: str = "user-default") -> Dict[str, Any]:
        agents = self._load_agents()
        target_name = agent_data.get("name", "").strip().lower()
        target_id = agent_data.get("id")

        if "ownerId" not in agent_data or not agent_data["ownerId"]:
            agent_data["ownerId"] = owner_id

        existing_idx = None
        for i, a in enumerate(agents):
            a_name = a.get("name", "").strip().lower()
            a_id = a.get("id")
            a_owner = a.get("ownerId", "system")
            if a_id == target_id or (target_name and a_name == target_name and a_owner == owner_id):
                existing_idx = i
                break
        
        if existing_idx is not None:
            agent_data["id"] = agents[existing_idx]["id"]
            agents[existing_idx] = agent_data
        else:
            agents.append(agent_data)
            
        self._save_agents(agents)
        return agent_data

    def delete_agent(self, agent_id: str, owner_id: str = "user-default") -> bool:
        agents = self._load_agents()
        new_agents = []
        deleted = False
        for a in agents:
            if a["id"] == agent_id:
                ag_owner = a.get("ownerId", "system")
                if ag_owner in ["system", "all"]:
                    continue
                if ag_owner == owner_id or owner_id in ["admin", "user-sudhanshu"]:
                    deleted = True
                    continue
            new_agents.append(a)
        
        if deleted:
            self._save_agents(new_agents)
            return True
        return False
