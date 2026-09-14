import os
import json
import logging
import re
import requests
from datetime import datetime
from typing import List, Dict, Any, Optional


from core.errors import LLMUnavailable
from core.paths import CONFIG_PATH

logger = logging.getLogger("buzzcaf_ai.llm")

# Environments where falling back to canned text is acceptable. Anywhere else,
# an unreachable provider raises instead of fabricating an answer.
_SIMULATION_ENVIRONMENTS = {"development", "dev", "test", "testing", "local"}


def _simulation_enabled() -> bool:
    return os.environ.get("APP_ENV", "development").strip().lower() in _SIMULATION_ENVIRONMENTS


# Every provider we know how to reach, in the order we fall back through them.
FALLBACK_ORDER = ["gemini", "openai", "lm_studio", "llamacpp"]
LOCAL_PROVIDERS = {"lm_studio", "llamacpp"}
DEFAULT_TEMPERATURE = 0.7

# What we tell Sentinel an LM Studio request may cost when the model name says
# nothing useful. LM Studio's own default (an 8B at a 4-bit quant) lands here.
LM_STUDIO_DEFAULT_MIB = 6144


def estimate_model_mib(name: str) -> int:
    """A rough VRAM figure for a model id like `meta-llama-3-8b-instruct`.

    The Studio never loads a model itself, so it cannot measure one; all it has
    is the id in Settings. Parameter count is the only part of that id that
    reliably means anything, and at the 4-bit quants LM Studio ships by default
    ~0.6 GiB per billion parameters plus a GiB of context and runtime overhead
    is close enough for an admission decision. When the id says nothing, the
    default above is used rather than a number that pretends to knowledge.
    """
    match = re.search(r"(\d+(?:\.\d+)?)\s*b\b", (name or "").lower())
    if not match:
        return LM_STUDIO_DEFAULT_MIB
    try:
        billions = float(match.group(1))
    except ValueError:
        return LM_STUDIO_DEFAULT_MIB
    if billions <= 0 or billions > 1000:
        return LM_STUDIO_DEFAULT_MIB
    return max(1024, int(billions * 640) + 1024)


# Two tiers, so cheap work (tags, titles, checklists) can go to the local model
# and the writing stays on the strong one (roadmap v9, F1). An empty provider
# means "use the globally selected one".
DEFAULT_TIERS = {
    "fast": {"provider": "llamacpp", "model": ""},
    "strong": {"provider": "", "model": ""},
}


def load_config() -> Dict[str, Any]:
    default_config = {
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash",
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": "meta-llama-3-8b-instruct",
        "llamacpp_url": "http://127.0.0.1:8089/v1",
        "llamacpp_model": "local-model",
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
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
        "LLAMACPP_URL": "llamacpp_url",
        "LLAMACPP_MODEL": "llamacpp_model",
        "SELECTED_PROVIDER": "selected_provider"
    }
    for env_key, config_key in env_keys.items():
        if os.environ.get(env_key):
            config[config_key] = os.environ[env_key]

    if os.environ.get("PREFER_GEMINI"):
        val = os.environ["PREFER_GEMINI"].lower() in ["true", "1", "yes"]
        config["prefer_gemini"] = val

    # A config file written before v9 has no tiers, and a partial one must not
    # lose a tier: fill in whatever is missing.
    tiers = config.get("tiers")
    merged = {k: dict(v) for k, v in DEFAULT_TIERS.items()}
    if isinstance(tiers, dict):
        for name, entry in tiers.items():
            if isinstance(entry, dict):
                merged.setdefault(name, {}).update(entry)
    config["tiers"] = merged

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

    def _tier_settings(self, tier: Optional[str]) -> Dict[str, Any]:
        entry = (self.config.get("tiers") or {}).get(tier) if tier else None
        return entry if isinstance(entry, dict) else {}

    def _provider_order(self, tier: Optional[str] = None) -> List[str]:
        """Which providers to try, in order: the tier's own first, then the
        globally selected one, then everything else (roadmap v9, F1)."""
        order: List[str] = []
        tier_provider = str(self._tier_settings(tier).get("provider") or "").strip().lower()
        if tier_provider:
            order.append(tier_provider)

        provider = self.config.get("selected_provider") or os.environ.get("SELECTED_PROVIDER")
        if not provider:
            provider = "gemini" if self.config.get("prefer_gemini", True) else "lm_studio"
        order.append(str(provider).lower())
        order.extend(FALLBACK_ORDER)

        seen, unique = set(), []
        for name in order:
            if name and name not in seen:
                seen.add(name)
                unique.append(name)
        return unique

    def _model_for(self, provider: str, tier: Optional[str]) -> str:
        override = str(self._tier_settings(tier).get("model") or "").strip()
        if override:
            return override
        return {
            "gemini": self.config.get("gemini_model", "gemini-1.5-flash"),
            "openai": self.config.get("openai_model", "gpt-4o-mini"),
            "lm_studio": self.config.get("lm_studio_model", "meta-llama-3-8b-instruct"),
            "llamacpp": self.config.get("llamacpp_model", "local-model"),
        }.get(provider, "")

    def _local_url(self, provider: str) -> str:
        key = "lm_studio_url" if provider == "lm_studio" else "llamacpp_url"
        default = "http://localhost:1234/v1" if provider == "lm_studio" else "http://127.0.0.1:8089/v1"
        return str(self.config.get(key) or default).rstrip("/")

    def _sentinel_allows(self, provider: str, tier: Optional[str] = None) -> bool:
        """May we send a request that could make a model load? (roadmap v10, S1)

        Only `lm_studio` is gated. The Studio never loads a model itself, but an
        LM Studio server with JIT loading on will pull several GB onto the card
        the moment a request arrives, and that is exactly the load Sentinel is
        there to admit or refuse. `llamacpp` is buzzcode's engine, which does
        its own reserving before it starts — asking twice for the same VRAM
        would double-count it.

        `query()` books nothing: it answers "would this be granted". A refusal
        is not an error, it is a routing decision, so the caller moves on to the
        next provider in FALLBACK_ORDER. An absent or older Sentinel answers
        "granted", which is the behaviour the Studio had before this existed.
        """
        if provider != "lm_studio":
            return True
        mib = estimate_model_mib(self._model_for(provider, tier))
        try:
            from integrations.sentinel_client import client as sentinel_client

            granted, details = sentinel_client().query(mib=mib)
        except Exception as exc:
            # A guardian we cannot even talk to must not stop the Studio.
            logger.debug("Sentinel query failed (%s); proceeding with lm_studio.", exc)
            return True
        if granted:
            return True
        holders = ", ".join(
            str(b.get("client") or b.get("process") or "?") for b in (details.get("blockers") or [])
        )
        logger.warning(
            "Sentinel refused %d MiB for lm_studio (%s%s); trying the next provider.",
            mib,
            details.get("reason") or "no reason given",
            f"; held by {holders}" if holders else "",
        )
        return False

    def generate_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool = False,
        tier: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """
        Multi-turn generation: `messages` is an ordered list of
        {"role": "user"|"assistant", "content": ...}. Same provider order and
        fallback rules as generate_text; the last user message is what the
        simulated fixture answers when no provider is reachable.
        """
        self.reload_config()
        self.last_response_simulated = False
        temp = DEFAULT_TEMPERATURE if temperature is None else float(temperature)

        for current_p in self._provider_order(tier):
            model = self._model_for(current_p, tier)
            if current_p == "gemini":
                api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting chat via Google Gemini API...")
                        return self._chat_gemini(api_key, system_prompt, messages, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"Gemini API chat failed: {e}.")
            elif current_p == "openai":
                api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting chat via OpenAI API...")
                        return self._chat_openai_compat(
                            "https://api.openai.com/v1/chat/completions",
                            {"Authorization": f"Bearer {api_key}"},
                            model, system_prompt, messages, require_json, temp,
                        )
                    except Exception as e:
                        logger.warning(f"OpenAI API chat failed: {e}.")
            elif current_p in LOCAL_PROVIDERS:
                if not self._sentinel_allows(current_p, tier):
                    continue
                url = self._local_url(current_p)
                try:
                    logger.info(f"Attempting chat via local {current_p} at {url}...")
                    return self._chat_openai_compat(
                        f"{url}/chat/completions", {}, model,
                        system_prompt, messages, False, temp, timeout=180,
                    )
                except Exception as e:
                    logger.warning(f"{current_p} chat failed: {e}.")

        if not _simulation_enabled():
            raise LLMUnavailable(
                "No LLM provider is reachable. Check your API keys and that the "
                "selected model is available in Settings."
            )
        logger.warning("No LLM provider succeeded; returning simulated content.")
        self.last_response_simulated = True
        from dev.fixtures import generate_simulated_response

        last_user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        return generate_simulated_response(system_prompt, last_user, require_json)

    def _chat_openai_compat(
        self,
        url: str,
        headers: Dict[str, str],
        model: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout: int = 90,
    ) -> str:
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(
            {"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages
        )
        payload: Dict[str, Any] = {"model": model, "messages": payload_messages, "temperature": temperature}
        if require_json:
            payload["response_format"] = {"type": "json_object"}
        response = requests.post(
            url, headers={"Content-Type": "application/json", **headers}, json=payload, timeout=timeout
        )
        if response.status_code != 200:
            raise Exception(f"{url} returned code {response.status_code}: {response.text[:300]}")
        resp_json = response.json()
        try:
            return resp_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse chat response payload: {resp_json}. Error: {e}")

    def _chat_gemini(
        self,
        api_key: str,
        system_prompt: str,
        messages: List[Dict[str, str]],
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        configured_model = model_name or self.config.get("gemini_model", "gemini-1.5-flash")
        candidate_models = list(dict.fromkeys(
            [configured_model, "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash-exp"]
        ))
        contents = [
            {"role": "user" if m.get("role") == "user" else "model", "parts": [{"text": m.get("content", "")}]}
            for m in messages
        ]
        last_error = None
        for model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            payload: Dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": temperature}}
            if system_prompt:
                payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
            if require_json:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            try:
                response = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
                if response.status_code == 200:
                    return response.json()["candidates"][0]["content"]["parts"][0]["text"]
                last_error = f"Gemini API ({model}) returned code {response.status_code}: {response.text[:200]}"
                logger.warning(last_error)
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Error calling Gemini model {model}: {e}")
        raise Exception(f"All Gemini models failed. Last error: {last_error}")

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        require_json: bool = False,
        tier: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        self.reload_config()
        self.last_response_simulated = False
        temp = DEFAULT_TEMPERATURE if temperature is None else float(temperature)

        for current_p in self._provider_order(tier):
            model = self._model_for(current_p, tier)
            if current_p == "gemini":
                api_key = self.config.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting generation via Google Gemini API...")
                        return self._call_gemini(api_key, system_prompt, user_prompt, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"Gemini API call failed: {e}.")
            elif current_p == "openai":
                api_key = self.config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
                if api_key:
                    try:
                        logger.info("Attempting generation via OpenAI API...")
                        return self._call_openai(api_key, system_prompt, user_prompt, require_json, model, temp)
                    except Exception as e:
                        logger.warning(f"OpenAI API call failed: {e}.")
            elif current_p in LOCAL_PROVIDERS:
                if not self._sentinel_allows(current_p, tier):
                    continue
                url = self._local_url(current_p)
                try:
                    logger.info(f"Attempting generation via local {current_p} at {url}...")
                    return self._call_local(url, model, system_prompt, user_prompt, temp)
                except Exception as e:
                    logger.warning(f"{current_p} API call failed: {e}.")


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

    def _call_openai(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        model = model_name or self.config.get("openai_model", "gpt-4o-mini")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
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

    def _call_gemini(
        self,
        api_key: str,
        system_prompt: str,
        user_prompt: str,
        require_json: bool,
        model_name: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        configured_model = model_name or self.config.get("gemini_model", "gemini-1.5-flash")
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
            generation_config = {"temperature": temperature}
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

    def _call_local(
        self,
        base_url: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        """LM Studio and llama.cpp both speak the OpenAI chat API."""
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }

        response = requests.post(url, headers=headers, json=payload, timeout=180)

        if response.status_code != 200:
            raise Exception(f"{url} returned code {response.status_code}: {response.text[:300]}")

        resp_json = response.json()
        try:
            text = resp_json["choices"][0]["message"]["content"]
            return text
        except (KeyError, IndexError) as e:
            raise Exception(f"Failed to parse local model response payload: {resp_json}. Error: {e}")

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

