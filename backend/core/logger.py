import os
import sys
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
            from core.paths import LOGS_DIR
            log_dir = LOGS_DIR
            
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "app.log")
        
        # Get root logger
        root_logger = logging.getLogger()
        
        # Keep existing handlers if they already write to studio.log or app.log
        existing_log_files = set()
        for h in root_logger.handlers:
            if isinstance(h, RotatingFileHandler) and hasattr(h, 'baseFilename'):
                existing_log_files.add(os.path.abspath(h.baseFilename))
        
        # Set level
        level = getattr(logging, log_level.upper(), logging.INFO)
        root_logger.setLevel(level)
        
        # Custom Formatter incorporating project_id and workflow_id
        fmt_str = '%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s] [Project:%(project_id)s, Workflow:%(workflow_id)s] - %(message)s'
        formatter = logging.Formatter(fmt_str)
        
        # Add context filter
        context_filter = ContextFilter()
        
        # Console Handler (only if a real console/terminal stderr or stdout is available)
        stream = None
        for s in (sys.stderr, sys.stdout):
            if s is not None and hasattr(s, "fileno"):
                try:
                    s.fileno()
                    stream = s
                    break
                except Exception:
                    pass
        if stream is not None:
            console = logging.StreamHandler(stream)
            console.setFormatter(formatter)
            console.addFilter(context_filter)
            root_logger.addHandler(console)
        
        # Rotating File Handler (add only if not already present)
        abs_log_file = os.path.abspath(log_file)
        if abs_log_file not in existing_log_files:
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
