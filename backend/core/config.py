import os
import json
import logging
from typing import Dict, Any, Optional
import dotenv

logger = logging.getLogger("spilled_coffee_ai.core.config")

DOTENV_PATH = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\.env"
CONFIG_PATH = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\config\config.json"

class ConfigurationManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigurationManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return
        self.settings: Dict[str, Any] = {}
        self.load()
        self.initialized = True

    def load(self):
        # 1. Load defaults
        self.settings = {
            "APP_NAME": "Spilled Coffee AI Studio",
            "APP_ENV": "development",
            "LOG_LEVEL": "INFO",
            "PROJECTS_PATH": r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\projects",
            "KNOWLEDGE_PATH": r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\knowledge",
            "PROMPTS_PATH": r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\prompts",
            "GEMINI_API_KEY": "",
            "LM_STUDIO_URL": "http://localhost:1234/v1",
            "LM_STUDIO_MODEL": "meta-llama-3-8b-instruct",
            "PREFER_GEMINI": True
        }

        # 2. Load from .env if present
        if os.path.exists(DOTENV_PATH):
            dotenv.load_dotenv(DOTENV_PATH, override=True)
            logger.info("Loaded configuration overrides from .env")

        # 3. Resolve using Priority: Env -> Config file -> Default
        # Resolve config file values first
        file_config = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
            except Exception as e:
                logger.error(f"Error loading LLM config file: {e}")

        # Update settings with file values
        for k, v in file_config.items():
            # Translate keys if necessary
            upper_k = k.upper()
            if upper_k in self.settings:
                self.settings[upper_k] = v
            else:
                self.settings[upper_k] = v

        # Update settings with environment variables
        for k in self.settings.keys():
            if os.environ.get(k) is not None:
                env_val = os.environ[k]
                # Cast bools
                if env_val.lower() in ["true", "1", "yes"]:
                    self.settings[k] = True
                elif env_val.lower() in ["false", "0", "no"]:
                    self.settings[k] = False
                else:
                    self.settings[k] = env_val

        self.validate()

    def reload(self):
        self.load()

    def get(self, key: str, default: Any = None) -> Any:
        return self.settings.get(key.upper(), default)

    def validate(self):
        # Validate required fields
        required_keys = [
            "APP_NAME", "APP_ENV", "LOG_LEVEL", 
            "PROJECTS_PATH", "KNOWLEDGE_PATH", "PROMPTS_PATH"
        ]
        for key in required_keys:
            if not self.settings.get(key):
                raise ValueError(f"CRITICAL CONFIG ERROR: Required configuration key '{key}' is missing or empty.")

        # Validate directory permissions and exists
        paths = ["PROJECTS_PATH", "KNOWLEDGE_PATH", "PROMPTS_PATH"]
        for path_key in paths:
            path_val = self.settings[path_key]
            if not os.path.exists(path_val):
                try:
                    os.makedirs(path_val, exist_ok=True)
                except Exception as e:
                    raise ValueError(f"CRITICAL CONFIG ERROR: Directory path '{path_val}' specified in '{path_key}' does not exist and cannot be created. Error: {e}")

        # Validate log levels
        valid_log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if self.settings["LOG_LEVEL"].upper() not in valid_log_levels:
            raise ValueError(f"CRITICAL CONFIG ERROR: Invalid LOG_LEVEL value: '{self.settings['LOG_LEVEL']}'. Must be one of {valid_log_levels}")

config_manager = ConfigurationManager()
