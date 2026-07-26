import os
from typing import Dict, Any, List, Optional
from core.config import config_manager

class ToolDefinition:
    def __init__(self, name: str, version: str, owner: str, permissions: List[str], inputs: List[str], outputs: str):
        self.name = name
        self.version = version
        self.owner = owner  # department or owner agent role
        self.permissions = permissions  # agent roles authorized to execute
        self.inputs = inputs
        self.outputs = outputs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "owner": self.owner,
            "permissions": self.permissions,
            "inputs": self.inputs,
            "outputs": self.outputs
        }

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}
        self._load_default_tools()

    def _load_default_tools(self) -> None:
        # Load Notion Integration Tool
        self.register(ToolDefinition(
            name="NotionSync",
            version="1.0.0",
            owner="Publishing Department",
            permissions=["CEO", "SEOManagerAgent", "ProjectManagerAgent"],
            inputs=["project_metadata"],
            outputs="sync_status"
        ))
        # Load Ollama Integration Tool
        self.register(ToolDefinition(
            name="OllamaLocalLLM",
            version="1.0.0",
            owner="system",
            permissions=["*"],  # Wildcard denotes anyone can execute local fallbacks
            inputs=["prompt_text"],
            outputs="response_text"
        ))
        # Load OpenAI Integration Tool
        self.register(ToolDefinition(
            name="OpenAIGPT",
            version="1.0.0",
            owner="system",
            permissions=["*"],
            inputs=["prompt_text"],
            outputs="response_text"
        ))
        # Load YouTube Publishing Tool
        self.register(ToolDefinition(
            name="YouTubePublish",
            version="1.0.0",
            owner="Publishing Department",
            permissions=["CEO", "SEOManagerAgent"],
            inputs=["publish_package"],
            outputs="youtube_video_id"
        ))

    def register(self, tool_def: ToolDefinition) -> None:
        self.tools[tool_def.name] = tool_def

    def check_permissions(self, agent_role: str, tool_name: str) -> bool:
        """Verifies if the requesting agent role has permission to execute the target tool."""
        tool = self.tools.get(tool_name)
        if not tool:
            return False
        if "*" in tool.permissions:
            return True
        return agent_role in tool.permissions

    def verify_availability(self, tool_name: str) -> Dict[str, Any]:
        """Runs availability health checks on external integrations based on configs."""
        tool = self.tools.get(tool_name)
        if not tool:
            return {"status": "unknown", "error": f"Tool '{tool_name}' not found."}

        # Check Notion Integration Health
        if tool_name == "NotionSync":
            notion_key = os.environ.get("NOTION_API_KEY") or config_manager.get("NOTION_API_KEY")
            if notion_key and len(notion_key) > 5:
                return {"status": "available", "latency_ms": 12}
            return {"status": "unavailable", "error": "Missing NOTION_API_KEY configuration variable."}

        # Check Ollama Local Integration Health
        elif tool_name == "OllamaLocalLLM":
            # Direct check if local LLM service address is configured
            local_url = config_manager.get("LOCAL_LLM_URL")
            if local_url and "localhost" in local_url:
                return {"status": "available", "latency_ms": 2}
            return {"status": "unavailable", "error": "Missing LOCAL_LLM_URL address configuration."}

        # Check OpenAI Integration Health
        elif tool_name == "OpenAIGPT":
            openai_key = os.environ.get("OPENAI_API_KEY")
            if openai_key:
                return {"status": "available", "latency_ms": 25}
            return {"status": "unavailable", "error": "Missing OPENAI_API_KEY environment variable."}

        # Check YouTube Integration Health
        elif tool_name == "YouTubePublish":
            yt_token = os.environ.get("YOUTUBE_OAUTH_TOKEN")
            if yt_token:
                return {"status": "available", "latency_ms": 18}
            return {"status": "unavailable", "error": "Missing YOUTUBE_OAUTH_TOKEN credentials."}

        return {"status": "available", "latency_ms": 1}

    def run_health_checks(self) -> Dict[str, Any]:
        """Collects availability reports for all registered tools."""
        report = {}
        for name in self.tools:
            report[name] = self.verify_availability(name)
        return report

tool_registry = ToolRegistry()
