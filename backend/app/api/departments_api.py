"""
Departments as something you can actually call (roadmap v9, E1).

    GET  /api/departments                  who is in each department
    POST /api/departments/{name}/execute   ask a department to do a piece of work

The manager takes the task unless `role` names one of its specialists. Nothing
here fabricates: when no provider answered, the reply comes back with
`simulated: true` and the UI badges it.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.departments import get_department, list_departments
from app.services.events import bus
from core.errors import LLMUnavailable

logger = logging.getLogger("buzzcaf_ai.departments_api")

router = APIRouter(prefix="/api/departments", tags=["Departments"])


class DepartmentTaskSchema(BaseModel):
    task: str
    role: Optional[str] = None
    require_json: Optional[bool] = False


@router.get("")
def get_departments():
    departments = [
        {
            "name": dept.name,
            "manager": dept.manager_role,
            "specialists": list(dept.specialist_roles),
        }
        for dept in list_departments()
    ]
    return {"status": "success", "count": len(departments), "departments": departments}


@router.post("/{name}/execute")
def execute_department_task(name: str, payload: DepartmentTaskSchema) -> Dict[str, Any]:
    dept = get_department(name)
    if not dept:
        raise HTTPException(status_code=404, detail=f"No department named '{name}'.")

    task = (payload.task or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="task is empty")

    role = (payload.role or "").strip() or dept.manager_role
    known = {r.lower() for r in dept.list_agents()}
    if role.lower() not in known:
        raise HTTPException(
            status_code=404,
            detail=f"'{role}' is not in the {dept.name} department. Members: {', '.join(dept.list_agents())}",
        )

    try:
        output = dept.execute_task(role, task, require_json=bool(payload.require_json))
    except LLMUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception as exc:
        logger.error("Department %s failed on '%s': %s", dept.name, role, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"{dept.name} could not run that task: {exc}")

    simulated = bool(getattr(dept.llm_service, "last_response_simulated", False))
    bus.publish("department_task", {
        "department": dept.name,
        "agent": role,
        "task_preview": task[:200],
        "simulated": simulated,
    })
    return {
        "status": "simulated" if simulated else "success",
        "department": dept.name,
        "agent": role,
        "simulated": simulated,
        "output": str(output),
    }
