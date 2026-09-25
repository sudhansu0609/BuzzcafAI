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
FALLBACK_ORDER = ["gemini", "openai", "lm_studio", "llamacpp", "ollama"]
LOCAL_PROVIDERS = {"lm_studio", "ollama", "llamacpp"}
LOCAL_FALLBACK_ORDER = ["lm_studio", "llamacpp", "ollama"]
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
# means "use the globally selected one". Defaults to local on-device models.
DEFAULT_TIERS = {
    "fast": {"provider": "llamacpp", "model": ""},
    "strong": {"provider": "", "model": ""},
}


def normalize_model_name(name: str) -> str:
    """Normalize model string by removing repo prefix, gguf extension, and non-alphanumeric chars."""
    if not name:
        return ""
    s = name.strip().lower()
    if "/" in s:
        s = s.split("/")[-1]
    s = re.sub(r"[-_.]gguf$", "", s)
    s = re.sub(r"[^a-z0-9]", "", s)
    return s


def models_match(configured: str, candidate: str) -> bool:
    """Fuzzy match between configured model identifier and candidate model identifier."""
    if not configured or not candidate:
        return False
    if configured.strip().lower() == candidate.strip().lower():
        return True
    n_conf = normalize_model_name(configured)
    n_cand = normalize_model_name(candidate)
    if n_conf == n_cand:
        return True
    if len(n_conf) >= 5 and (n_conf in n_cand or n_cand in n_conf):
        return True
    return False


def find_lms_binary() -> Optional[str]:
    """Find the path to the LM Studio CLI binary (lms or lms.exe)."""
    import shutil
    lms_path = shutil.which("lms")
    if lms_path and os.path.exists(lms_path):
        return lms_path
    candidates = [
        os.path.expanduser(r"~/.lmstudio/bin/lms.exe"),
        os.path.expanduser(r"~/.lmstudio/bin/lms"),
        r"C:\Users\singh\.lmstudio\bin\lms.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\LM Studio\lms.exe"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def get_loaded_lm_studio_models(base_url: str = "http://localhost:1234") -> List[str]:
    """Return list of model IDs currently loaded in LM Studio memory."""
    import subprocess
    loaded: List[str] = []

    # 1. Fast check: LM Studio REST API (/api/v0/models takes ~10ms)
    try:
        clean_url = base_url.rstrip("/").replace("/v1", "")
        r = requests.get(f"{clean_url}/api/v0/models", timeout=0.8)
        if r.status_code == 200:
            data = r.json().get("data", [])
            for m in data:
                if m.get("state") == "loaded":
                    mid = m.get("id")
                    if mid and mid not in loaded:
                        loaded.append(mid)
            if loaded:
                return loaded
    except Exception as exc:
        logger.debug("Failed querying /api/v0/models: %s", exc)

    # 2. Fallback check: lms CLI process list (lms ps)
    try:
        bin_path = find_lms_binary()
        if bin_path:
            res = subprocess.run([bin_path, "ps"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                for line in res.stdout.strip().splitlines()[1:]:
                    parts = line.split()
                    if parts and parts[0] != "IDENTIFIER":
                        mid = parts[0]
                        if mid not in loaded:
                            loaded.append(mid)
    except Exception as exc:
        logger.debug("Failed running lms ps: %s", exc)

    return loaded


def is_model_already_loaded(target_model: Optional[str], loaded_models: List[str]) -> Tuple[bool, Optional[str]]:
    """Determine if target_model is already loaded in memory.
    Returns (True, matched_id) if loaded, or (False, None)."""
    if not loaded_models:
        return False, None
    if not target_model or not target_model.strip() or target_model.lower() in ("auto", "default"):
        return True, loaded_models[0]

    # 1. Exact match
    for mid in loaded_models:
        if target_model.strip().lower() == mid.strip().lower():
            return True, mid

    # 2. Fuzzy / normalized match
    for mid in loaded_models:
        if models_match(target_model, mid) or models_match(mid, target_model):
            return True, mid

    # 3. Substring match on normalized stems
    n_target = normalize_model_name(target_model)
    if len(n_target) >= 4:
        for mid in loaded_models:
            n_mid = normalize_model_name(mid)
            if n_target in n_mid or n_mid in n_target:
                return True, mid

    return False, None


def ensure_local_model_loaded(provider: str = "lm_studio", model_name: Optional[str] = None) -> Dict[str, Any]:
    """Ensure that the requested local model is loaded in LM Studio or Ollama.
    If already loaded, returns status immediately without calling load again.
    If not loaded, attempts to bring it up automatically."""
    import subprocess

    if provider == "lm_studio":
        try:
            base_url = "http://localhost:1234"
            loaded = get_loaded_lm_studio_models(base_url)

            # If target model (or any model if none specified) is already loaded, NEVER reload it!
            already_loaded, matched_mid = is_model_already_loaded(model_name, loaded)
            if already_loaded and matched_mid:
                logger.info(
                    "LM Studio model '%s' (requested: '%s') is ALREADY loaded. Skipping reload.",
                    matched_mid, model_name or "active",
                )
                return {
                    "loaded": True,
                    "model": matched_mid,
                    "already_loaded": True,
                    "all_loaded": loaded,
                    "message": f"Model '{matched_mid}' is already loaded in memory",
                }

            # If target model is truly not loaded, find matching candidate
            lms_bin = find_lms_binary()
            if not lms_bin:
                return {
                    "loaded": False,
                    "model": model_name or "",
                    "already_loaded": False,
                    "all_loaded": loaded,
                    "message": "lms binary not found to load model",
                }

            r = requests.get(f"{base_url}/api/v0/models", timeout=2.0)
            data = r.json().get("data", []) if r.status_code == 200 else []

            target_key = None
            if model_name:
                for m in data:
                    mid = m.get("id", "")
                    if models_match(model_name, mid) or models_match(mid, model_name):
                        target_key = mid
                        break

            # Re-check: Is resolved target_key already loaded?
            if target_key:
                is_target_loaded, loaded_id = is_model_already_loaded(target_key, loaded)
                if is_target_loaded and loaded_id:
                    logger.info("Resolved model '%s' is already loaded. Skipping reload.", loaded_id)
                    return {
                        "loaded": True,
                        "model": loaded_id,
                        "already_loaded": True,
                        "all_loaded": loaded,
                        "message": f"Model '{loaded_id}' is already loaded",
                    }

            # If no target specified or model not found, and some model is already loaded, DO NOT load arbitrary model
            if not target_key and loaded:
                logger.info("Existing model '%s' is already loaded. Skipping reload.", loaded[0])
                return {
                    "loaded": True,
                    "model": loaded[0],
                    "already_loaded": True,
                    "all_loaded": loaded,
                    "message": f"Active model '{loaded[0]}' is already loaded",
                }

            if not target_key and data and not loaded:
                target_key = data[0].get("id")

            if target_key and target_key not in loaded:
                logger.info("Attempting to auto-load LM Studio model '%s' via lms CLI...", target_key)
                cmd = [lms_bin, "load", target_key, "-y"]
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if proc.returncode == 0:
                    logger.info("Successfully loaded LM Studio model '%s'", target_key)
                    return {"loaded": True, "model": target_key, "already_loaded": False, "message": f"Successfully loaded {target_key}"}
                else:
                    logger.warning("lms load failed: %s", proc.stderr)
        except Exception as exc:
            logger.warning("Failed to check or load model in LM Studio: %s", exc)

    elif provider == "ollama":
        try:
            r = requests.get("http://localhost:11434/api/ps", timeout=1.5)
            if r.status_code == 200:
                running = [m.get("name") or m.get("model") for m in r.json().get("models", [])]
                if model_name and any(models_match(model_name, m) for m in running):
                    return {"loaded": True, "model": model_name, "already_loaded": True, "all_loaded": running, "message": "Model already loaded"}
                if not model_name and running:
                    return {"loaded": True, "model": running[0], "already_loaded": True, "all_loaded": running, "message": "Active model loaded"}
            return {"loaded": True, "model": model_name or "ollama", "already_loaded": True, "message": "Ollama ready"}
        except Exception as exc:
            logger.warning("Ollama check failed: %s", exc)

    return {"loaded": False, "model": model_name or "", "already_loaded": False, "message": "Could not verify model"}


def load_config() -> Dict[str, Any]:
    default_config = {
        "gemini_api_key": "",
        "gemini_model": "gemini-1.5-flash",
        "openai_api_key": "",
        "openai_model": "gpt-4o-mini",
        "lm_studio_url": "http://localhost:1234/v1",
        "lm_studio_model": "qwen3.8-27b-gsq-rco",
        "ollama_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3.5:9b",
        "llamacpp_url": "http://127.0.0.1:8089/v1",
        "llamacpp_model": "qwen3.8-27b",
        "tiers": {k: dict(v) for k, v in DEFAULT_TIERS.items()},
        "local_only": True,
        "prefer_gemini": False,
        "selected_provider": "lm_studio"
    }

    config = dict(default_config)

    # 1. Environment variables provide baseline defaults
    env_keys = {
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_MODEL": "gemini_model",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "LM_STUDIO_URL": "lm_studio_url",
        "LM_STUDIO_MODEL": "lm_studio_model",
        "OLLAMA_URL": "ollama_url",
        "OLLAMA_MODEL": "ollama_model",
        "LLAMACPP_URL": "llamacpp_url",
        "LLAMACPP_MODEL": "llamacpp_model",
        "SELECTED_PROVIDER": "selected_provider"
    }
    for env_key, config_key in env_keys.items():
        if os.environ.get(env_key):
            config[config_key] = os.environ[env_key]

    if os.environ.get("LOCAL_ONLY") is not None:
        config["local_only"] = os.environ["LOCAL_ONLY"].lower() in ["true", "1", "yes"]

    if os.environ.get("PREFER_GEMINI"):
        val = os.environ["PREFER_GEMINI"].lower() in ["true", "1", "yes"]
        config["prefer_gemini"] = val

    # 2. Saved configuration in config.json overrides environment defaults
    # so creator settings persist across reloads until explicitly reset
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                file_config = json.load(f)
                for k, v in file_config.items():
                    config[k] = v
        except Exception as e:
            logger.error(f"Error loading LLM config: {e}")

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
        globally selected one, then everything else (roadmap v9, F1).

        When local_only is True (default) or the selected provider is in
        LOCAL_PROVIDERS, all cloud providers (Gemini, OpenAI) are strictly
        filtered out to ensure zero data leaves the machine.
        """
        order: List[str] = []
        tier_provider = str(self._tier_settings(tier).get("provider") or "").strip().lower()
        if tier_provider:
            order.append(tier_provider)

        provider = self.config.get("selected_provider") or os.environ.get("SELECTED_PROVIDER")
        if not provider:
            provider = "lm_studio" if not self.config.get("prefer_gemini", False) else "gemini"
        order.append(str(provider).lower())

        is_local_only = bool(self.config.get("local_only", False))
        if is_local_only:
            order.extend(LOCAL_FALLBACK_ORDER)
        else:
            order.extend(FALLBACK_ORDER)

        seen, unique = set(), []
        for name in order:
            if not name or name in seen:
                continue
            if is_local_only and name not in LOCAL_PROVIDERS:
                continue
            seen.add(name)
            unique.append(name)
        return unique

    def _model_for(self, provider: str, tier: Optional[str]) -> str:
        tier_cfg = self._tier_settings(tier)
        tier_p = str(tier_cfg.get("provider") or "").strip().lower()
        override = str(tier_cfg.get("model") or "").strip()
        if override and (not tier_p or tier_p == provider.lower()):
            return override
        return {
            "gemini": self.config.get("gemini_model", "gemini-1.5-flash"),
            "openai": self.config.get("openai_model", "gpt-4o-mini"),
            "lm_studio": self.config.get("lm_studio_model", "qwen3.8-27b-gsq-rco"),
            "ollama": self.config.get("ollama_model", "qwen3.5:9b"),
            "llamacpp": self.config.get("llamacpp_model", "qwen3.8-27b"),
        }.get(provider, "")

    def _local_url(self, provider: str) -> str:
        if provider == "ollama":
            default = "http://localhost:11434/v1"
            key = "ollama_url"
        elif provider == "lm_studio":
            default = "http://localhost:1234/v1"
            key = "lm_studio_url"
        else:
            default = "http://127.0.0.1:8089/v1"
            key = "llamacpp_url"
        return str(self.config.get(key) or default).rstrip("/")

    def _is_lm_studio_model_loaded(self, model_name: str) -> bool:
        """Check if the requested model is already resident in LM Studio VRAM/RAM."""
        if not model_name:
            return False
        try:
            base_url = self._local_url("lm_studio").replace("/v1", "")
            r = requests.get(f"{base_url}/api/v0/models", timeout=0.8)
            if r.status_code == 200:
                for m in r.json().get("data", []):
                    mid = m.get("id", "")
                    if (m.get("state") == "loaded") and (mid == model_name or models_match(model_name, mid)):
                        return True
        except Exception:
            pass
        return False

    def _resolve_lm_studio_model(self, requested_model: Optional[str] = None) -> str:
        """Resolve a configured model identifier to the actual ID recognized by LM Studio."""
        try:
            base_url = self._local_url("lm_studio").replace("/v1", "")
            r = requests.get(f"{base_url}/api/v0/models", timeout=0.8)
            if r.status_code == 200:
                data = r.json().get("data", [])
                loaded_models = [m.get("id") for m in data if m.get("state") == "loaded"]
                available_models = [m.get("id") for m in data]

                # 1. Match against loaded models first
                if requested_model:
                    for mid in loaded_models:
                        if models_match(requested_model, mid):
                            return mid

                # 2. Match against available models
                if requested_model:
                    for mid in available_models:
                        if models_match(requested_model, mid):
                            return mid

                # 3. Fall back to currently loaded model
                if loaded_models:
                    return loaded_models[0]

                # 4. Fall back to first available model
                if available_models:
                    return available_models[0]
        except Exception as e:
            logger.debug("Could not query LM Studio models: %s", e)
        return requested_model or "qwen3.8-27b-gsq-rco"

    def _sentinel_allows(self, provider: str, tier: Optional[str] = None) -> bool:
        """May we send a request that could make a model load? (roadmap v10, S1)"""
        if provider != "lm_studio":
            return True
        model = self._model_for(provider, tier)
        resolved_model = self._resolve_lm_studio_model(model)
        if self._is_lm_studio_model_loaded(resolved_model):
            return True
        mib = estimate_model_mib(resolved_model)
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
            "Sentinel refused %d MiB for lm_studio (%s%s); evaluating fallback.",
            mib,
            details.get("reason") or "no reason given",
            f"; held by {holders}" if holders else "",
        )
        # If Strict Local is on and no other active client blocks the card, allow LM Studio
        # to manage CPU offloading rather than stranding the user with simulated text.
        if self.config.get("local_only", True) and not holders:
            logger.info("Sentinel refused full VRAM, but LM Studio offloading is available; allowing request.")
            return True
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
                if current_p == "lm_studio":
                    model = self._resolve_lm_studio_model(model)
                url = self._local_url(current_p)
                try:
                    logger.info(f"Attempting chat via local {current_p} at {url} (model: {model})...")
                    return self._chat_openai_compat(
                        f"{url}/chat/completions", {}, model,
                        system_prompt, messages, False, temp, timeout=180,
                    )
                except Exception as e:
                    logger.warning(f"{current_p} chat failed: {e}.")

        if not _simulation_enabled():
            msg = (
                "No local LLM provider is reachable (LM Studio / Ollama / llama.cpp). "
                "Cloud providers are blocked by Strict Local Mode to ensure zero data leaves your PC."
                if self.config.get("local_only", True)
                else "No LLM provider is reachable. Check your API keys and that the selected model is available in Settings."
            )
            raise LLMUnavailable(msg)
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
                if current_p == "lm_studio":
                    model = self._resolve_lm_studio_model(model)
                url = self._local_url(current_p)
                try:
                    logger.info(f"Attempting generation via local {current_p} at {url} (model: {model})...")
                    return self._call_local(url, model, system_prompt, user_prompt, temp)
                except Exception as e:
                    logger.warning(f"{current_p} API call failed: {e}.")


        # Every provider failed or none was configured.
        if not _simulation_enabled():
            msg = (
                "No local LLM provider is reachable (LM Studio / Ollama / llama.cpp). "
                "Cloud providers are blocked by Strict Local Mode to ensure zero data leaves your PC."
                if self.config.get("local_only", True)
                else "No LLM provider is reachable. Check your API keys and that the selected model is available in Settings."
            )
            raise LLMUnavailable(msg)

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

