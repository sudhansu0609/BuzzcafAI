import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

class ContextFilter(logging.Filter):
    """Filter that injects project_id and workflow_id into log records if not present."""
    def filter(self, record):
        if not hasattr(record, 'project_id'):
            record.project_id = 'N/A'
        if not hasattr(record, 'workflow_id'):
            record.workflow_id = 'N/A'
        return True

class LoggingManager:
    _initialized = False

    @classmethod
    def setup(cls, log_level: str = "INFO", log_dir: Optional[str] = None):
        if cls._initialized:
            return
            
        if not log_dir:
            log_dir = r"b:\youtubeProjects\Buzzcaf Media\SpilledCoffeeAI\backend\logs"
            
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")
        
        # Get root logger
        root_logger = logging.getLogger()
        
        # Clear existing handlers
        root_logger.handlers = []
        
        # Set level
        level = getattr(logging, log_level.upper(), logging.INFO)
        root_logger.setLevel(level)
        
        # Custom Formatter incorporating project_id and workflow_id
        fmt_str = '%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s] [Project:%(project_id)s, Workflow:%(workflow_id)s] - %(message)s'
        formatter = logging.Formatter(fmt_str)
        
        # Add context filter
        context_filter = ContextFilter()
        
        # Console Handler
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.addFilter(context_filter)
        root_logger.addHandler(console)
        
        # Rotating File Handler
        file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        root_logger.addHandler(file_handler)
        
        cls._initialized = True
        logging.info("LoggingManager initialized. Output routed to console and rotating file log.")

    @staticmethod
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

# Auto-setup logging using configuration defaults
from .config import config_manager
LoggingManager.setup(log_level=config_manager.get("LOG_LEVEL"))
logger = LoggingManager.get_logger("spilled_coffee_ai")
