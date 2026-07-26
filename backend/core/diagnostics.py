import os
import sys
import time
import logging
from typing import Dict, Any

logger = logging.getLogger("spilled_coffee_ai.core.diagnostics")

START_TIME = time.time()

class Diagnostics:
    @staticmethod
    def get_report() -> Dict[str, Any]:
        from core.config import config_manager
        from core.workflow import workflow_registry
        from core.markdown import markdown_loader
        
        elapsed = time.time() - START_TIME
        
        # Count agents dynamically from registry
        from core.agent import agent_registry
        agent_count = len(agent_registry.list())

        
        return {
            "startup_time_seconds": round(elapsed, 4),
            "app_name": config_manager.get("APP_NAME"),
            "environment": config_manager.get("APP_ENV"),
            "log_level": config_manager.get("LOG_LEVEL"),
            "loaded_workflows_count": len(workflow_registry.list()),
            "loaded_workflows": [wf.id for wf in workflow_registry.list()],
            "registered_agents_count": agent_count,
            "cached_markdown_documents": len(markdown_loader.cache),
            "python_version": sys.version,
            "platform": sys.platform
        }

    @staticmethod
    def log_summary():
        report = Diagnostics.get_report()
        logger.info(f"--- Spilled Coffee AI Studio Diagnostics ---")
        logger.info(f"Application: {report['app_name']} ({report['environment']})")
        logger.info(f"Startup Time: {report['startup_time_seconds']}s")
        logger.info(f"Loaded Workflows: {report['loaded_workflows_count']}")
        logger.info(f"Registered Agents: {report['registered_agents_count']}")
        logger.info(f"---------------------------------------------")
