# Buzzcaf AI - Local LLM Engine Integration Service (LM Studio & Open-WebUI/Ollama)
import urllib.request
import json
import logging
from typing import List, Dict, Any, Generator

logger = logging.getLogger("buzzcaf_ai.local_llm")

LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
OLLAMA_BASE_URL = "http://localhost:11434/v1"

class LocalLLMService:
    def detect_local_models(self) -> Dict[str, Any]:
        """Auto-detect running models from LM Studio and Ollama API endpoints."""
        models = []

        # 1. Probe LM Studio (http://localhost:1234/v1/models)
        try:
            req = urllib.request.Request(f"{LM_STUDIO_BASE_URL}/models", headers={"User-Agent": "BuzzcafAI"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    for m in data.get("data", []):
                        models.append({
                            "id": m.get("id"),
                            "name": m.get("id"),
                            "provider": "LM Studio",
                            "endpoint": LM_STUDIO_BASE_URL,
                            "status": "online"
                        })
        except Exception as e:
            logger.debug(f"LM Studio connection notice: {e}")

        # 2. Probe Ollama / Open-WebUI (http://localhost:11434/v1/models)
        try:
            req = urllib.request.Request(f"{OLLAMA_BASE_URL}/models", headers={"User-Agent": "BuzzcafAI"})
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    for m in data.get("data", []):
                        models.append({
                            "id": m.get("id"),
                            "name": m.get("id"),
                            "provider": "Ollama / Open-WebUI",
                            "endpoint": OLLAMA_BASE_URL,
                            "status": "online"
                        })
        except Exception as e:
            logger.debug(f"Ollama connection notice: {e}")

        # Provide fallback local model entries if servers are offline
        if not models:
            models = [
                {"id": "qwen2.5-coder-7b-instruct", "name": "Qwen 2.5 Coder 7B (LM Studio)", "provider": "LM Studio", "endpoint": LM_STUDIO_BASE_URL, "status": "offline_preview"},
                {"id": "llama3.2:latest", "name": "Llama 3.2 3B (Ollama)", "provider": "Ollama / Open-WebUI", "endpoint": OLLAMA_BASE_URL, "status": "offline_preview"},
                {"id": "deepseek-r1-distill-llama-8b", "name": "DeepSeek R1 Distill 8B", "provider": "LM Studio", "endpoint": LM_STUDIO_BASE_URL, "status": "offline_preview"}
            ]

        return {"models": models, "count": len(models)}

    def generate_agent_chat_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model_name: str = "qwen2.5-coder-7b-instruct",
        provider_endpoint: str = LM_STUDIO_BASE_URL,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Execute OpenAI-compatible chat completion on local LLM endpoint."""
        endpoint_url = f"{provider_endpoint.rstrip('/')}/chat/completions"
        
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        payload = {
            "model": model_name,
            "messages": full_messages,
            "temperature": temperature,
            "stream": False
        }

        try:
            req = urllib.request.Request(
                endpoint_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "BuzzcafAI"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode("utf-8"))
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return {"content": content, "status": "success", "model_used": model_name}
        except Exception as e:
            logger.warning(f"Local LLM execution fell back to local AI engine: {e}")

        # Fallback simulation response if local model server isn't actively running
        return {
            "content": f"[Simulated Response from {model_name}]: I have analyzed your project requirements. Let's refine the video strategy, hook structure, and audience engagement roadmap!",
            "status": "fallback",
            "model_used": model_name
        }

local_llm_service = LocalLLMService()
