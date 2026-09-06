import os
import json
import logging
import requests
from datetime import datetime
from typing import Dict, Any, Optional


from core.errors import LLMUnavailable
from core.paths import CONFIG_PATH

logger = logging.getLogger("buzzcaf_ai.llm")

# Environments where falling back to canned text is acceptable. Anywhere else,
# an unreachable provider raises instead of fabricating an answer.
_SIMULATION_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


def _simulation_enabled() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() in _SIMULATION_ENVIRONMENTS

def load_config() -> Dict[str, Any]:
    default_config = {
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash",
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": "meta-llama-3-8b-instruct",
        "prefer_gemini": True,
        "selected_provider": "gemini"
    }
    
    config = dict(default_config)
    
    # 1. Load from file if exists
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                for k, v in file_config.items():
                    config[k] = v
        except Exception as e:
            logger.error(f"Error loading LLM config: {e}")

    # 2. Override with Environment Variables
    env_keys = {
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_MODEL": "gemini_model",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "LM_STUDIO_URL": "lm_studio_url",
        "LM_STUDIO_MODEL": "lm_studio_model",
        "SELECTED_PROVIDER": "selected_provider"
    }
    for env_key, config_key in env_keys.items():
        if os.environ.get(env_key):
            config[config_key] = os.environ[env_key]
            
    if os.environ.get("PREFER_GEMINI"):
        val = os.environ["PREFER_GEMINI"].lower() in ["true", "1", "yes"]
        config["prefer_gemini"] = val
        
    return config


def save_config(config: Dict[str, Any]):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving LLM config: {e}")

class LLMService:
    def __init__(self):
        self.config = load_config()
        # True when the most recent generate_text() call produced canned text
        # because every configured provider failed. Callers must surface this
        # rather than presenting fabricated output as a model response.
        self.last_response_simulated = False

    def reload_config(self):
        self.config = load_config()

    def generate_text(self, system_prompt: str, user_prompt: str, require_json: bool = False) -> str:
        self.reload_config()
        self.last_response_simulated = False

        provider = self.config.get("selected_provider") or os.environ.get("SELECTED_PROVIDER")
        if not provider:
            if self.config.get("prefer_gemini", True):
                provider = "gemini"
            else:
                provider = "lm_studio"
                
        provider = provider.lower()
        
        # Build attempt order: selected provider first, then fallbacks
        providers_to_try = [provider]
        for p in ["gemini", "openai", "lm_studio"]:
            if p not in providers_to_try:
                providers_to_try.append(p)
                
        for current_p in providers_to_try:
            if current_p == "gemini":
                api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting generation via Google Gemini API...")
                        return self._call_gemini(api_key, system_prompt, user_prompt, require_json)
                    except Exception as e:
                        logger.warning(f"Gemini API call failed: {e}.")
            elif current_p == "openai":
                api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting generation via OpenAI API...")
                        return self._call_openai(api_key, system_prompt, user_prompt, require_json)
                    except Exception as e:
                        logger.warning(f"OpenAI API call failed: {e}.")
            elif current_p == "lm_studio":
                lm_url = self.config.get("lm_studio_url", "http://localhost:1234/v1")
                try:
                    logger.info(f"Attempting generation via local LM Studio at {lm_url}...")
                    return self._call_lm_studio(lm_url, system_prompt, user_prompt)
                except Exception as e:
                    logger.warning(f"LM Studio API call failed: {e}.")
                    
        # Every provider failed or none was configured.
        if not _simulation_enabled():
            raise LLMUnavailable(
                "No LLM provider is reachable. Check your API keys and that the "
                "selected model is available in Settings."
            )

        # The canned response below is NOT model output -- flag it so callers
        # can label it. See backend/dev/fixtures.py.
        logger.warning(
            "No LLM provider succeeded; returning simulated content. "
            "Check API keys and provider availability in Settings."
        )
        self.last_response_simulated = True
        from dev.fixtures import generate_simulated_response
        return generate_simulated_response(system_prompt, user_prompt, require_json)

    def _call_openai(self, api_key: str, system_prompt: str, user_prompt: str, require_json: bool) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        model = self.config.get("openai_model", "gpt-4o-mini")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7
        }
        
        if require_json:
            payload["response_format"] = {"type": "json_object"}
            
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API returned code {response.status_code}: {response.text}")
            
        resp_json = response.json()
        try:
            text = resp_json["choices"][0]["message"]["content"]
            return text
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse OpenAI response payload: {resp_json}. Error: {e}")

    def _call_gemini(self, api_key: str, system_prompt: str, user_prompt: str, require_json: bool) -> str:
        configured_model = self.config.get("gemini_model", "gemini-1.5-flash")
        candidate_models = [configured_model, "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
        # Remove duplicates preserving order
        candidate_models = list(dict.fromkeys(candidate_models))
        
        headers = {
            "Content-Type": "application/json"
        }
        
        last_error = None
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [{"text": user_prompt}]
                    }
                ]
            }
            if system_prompt:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_prompt}]
                }
            generation_config = {"temperature": 0.7}
            if require_json:
                generation_config["responseMimeType"] = "application/json"
            payload["generationConfig"] = generation_config
            
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=45)
                if response.status_code == 200:
                    resp_json = response.json()
                    text = resp_json["candidates"][0]["content"]["parts"][0]["text"]
                    return text
                else:
                    last_error = f"Gemini API ({model}) returned code {response.status_code}: {response.text[:200]}"
                    logger.warning(last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Error calling Gemini model {model}: {e}")
                
        raise Exception(f"All Gemini models failed. Last error: {last_error}")

    def _call_lm_studio(self, base_url: str, system_prompt: str, user_prompt: str) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }
        
        model = self.config.get("lm_studio_model", "meta-llama-3-8b-instruct")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code != 200:
            raise Exception(f"LM Studio API returned code {response.status_code}: {response.text}")
            
        resp_json = response.json()
        try:
            text = resp_json["choices"][0]["message"]["content"]
            return text
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse LM Studio response payload: {resp_json}. Error: {e}")

def clean_json_response(raw_text: str) -> str:
    """Helper to remove markdown code blocks wrapping JSON."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        # Find first newline
        lines = cleaned.splitlines()
        if lines[0].startswith("```json") or lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned

llm_service = LLMService()

