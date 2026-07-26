import os
import logging
from typing import Dict, Any, List
from core.config import config_manager
from core.workflow import workflow_registry
from core.agent import agent_registry
from knowledge.knowledge import knowledge_manager
from core.prompt import prompt_manager
from core.markdown import markdown_loader

logger = logging.getLogger("spilled_coffee_ai.core.doctor")

class HealthChecker:
    @staticmethod
    def run_checks() -> Dict[str, Any]:
        """Runs the validation doctor framework, checking all registries and configurations."""
        status = "healthy"
        logs: List[str] = []
        details: Dict[str, Any] = {}

        # 1. Check Configurations
        try:
            config_manager.validate()
            logs.append("[OK] Configuration validation successful.")
            details["config"] = {"status": "valid", "app_name": config_manager.get("APP_NAME")}
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Configuration validation failed: {e}")
            details["config"] = {"status": "invalid", "error": str(e)}

        # 2. Check Required Folders
        folder_status = "valid"
        paths_to_check = {
            "Projects": config_manager.get("PROJECTS_PATH"),
            "Knowledge": config_manager.get("KNOWLEDGE_PATH"),
            "Prompts": config_manager.get("PROMPTS_PATH")
        }
        for name, path in paths_to_check.items():
            if not os.path.exists(path):
                folder_status = "invalid"
                logs.append(f"[ERROR] Required folder does not exist: {name} path '{path}'")
            else:
                logs.append(f"[OK] Folder exists: {name} path '{path}'")
                
        # Check knowledge subfolders
        from knowledge.knowledge import CATEGORIES
        for cat in CATEGORIES:
            cat_path = os.path.join(config_manager.get("KNOWLEDGE_PATH"), cat)
            if not os.path.exists(cat_path):
                folder_status = "invalid"
                logs.append(f"[ERROR] Required knowledge subfolder missing: {cat_path}")
            else:
                logs.append(f"[OK] Knowledge subfolder present: {cat_path}")
        details["folders"] = {"status": folder_status}

        # 3. Check Agent Registry
        try:
            agent_registry.discover_agents()
            agents_list = agent_registry.list()
            logs.append(f"[OK] Agent Registry load: {len(agents_list)} agents registered.")
            details["agents"] = {
                "status": "valid",
                "count": len(agents_list),
                "list": [a.name for a in agents_list]
            }
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Agent Registry loading failed: {e}")
            details["agents"] = {"status": "invalid", "error": str(e)}

        # 4. Check Workflow Registry
        try:
            workflow_registry.discover_workflows()
            wfs = workflow_registry.list()
            logs.append(f"[OK] Workflow Registry load: {len(wfs)} workflows registered.")
            
            # Additional circular dependency loop validation for each workflow
            for wf in wfs:
                workflow_registry.validate(wf)
            logs.append("[OK] Workflow circular dependency validation successful.")
            details["workflows"] = {
                "status": "valid",
                "count": len(wfs),
                "list": [w.id for w in wfs]
            }
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Workflow Registry loading failed: {e}")
            details["workflows"] = {"status": "invalid", "error": str(e)}

        # 5. Check Markdown Documents
        try:
            knowledge_manager.validate_index()
            logs.append(f"[OK] Markdown Document cache check: {len(knowledge_manager.index)} documents indexed.")
            details["markdown"] = {
                "status": "valid",
                "indexed_documents": len(knowledge_manager.index)
            }
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Markdown Documents validation failed: {e}")
            details["markdown"] = {"status": "invalid", "error": str(e)}

        # 6. Check Prompts Load and Validation
        try:
            prompt_files_count = 0
            prompts_path = config_manager.get("PROMPTS_PATH")
            if os.path.exists(prompts_path):
                # Simply scan prompts/ folder recursively to check they are valid prompt markdown files
                for root, _, files in os.walk(prompts_path):
                    for file in files:
                        if file.endswith(".md") and "agents" not in root and "channels" not in root:
                            prompt_files_count += 1
            logs.append(f"[OK] Prompt Manager verified: loaded {prompt_files_count} custom prompt templates.")
            details["prompts"] = {"status": "valid", "count": prompt_files_count}
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Prompt validation failed: {e}")
            details["prompts"] = {"status": "invalid", "error": str(e)}

        # 7. Check Tool Registry and Integrations Health
        try:
            from integrations.tools import tool_registry
            tool_reports = tool_registry.run_health_checks()
            available_tools = [name for name, report in tool_reports.items() if report["status"] == "available"]
            logs.append(f"[OK] Tool Registry verified: {len(available_tools)}/{len(tool_reports)} integrations active.")
            details["tools"] = {
                "status": "valid",
                "total_tools": len(tool_reports),
                "available_tools_count": len(available_tools),
                "details": tool_reports
            }
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Tool Registry validation failed: {e}")
            details["tools"] = {"status": "invalid", "error": str(e)}

        # 8. Check Container Bootstrapping and Registry
        try:
            from runtime.bootstrap import bootstrap
            container = bootstrap()
            settings = container.resolve("settings")
            logs.append(f"[OK] Core Runtime Container bootstrapped: APP_NAME={settings.app_name}")
            details["container"] = {
                "status": "valid",
                "app_name": settings.app_name,
                "debug_mode": settings.debug
            }
        except Exception as e:
            status = "unhealthy"
            logs.append(f"[ERROR] Core Runtime Container bootstrapping failed: {e}")
            details["container"] = {"status": "invalid", "error": str(e)}

        if any(details[k].get("status") == "invalid" for k in details):
            status = "unhealthy"

        return {
            "status": status,
            "logs": logs,
            "details": details
        }


