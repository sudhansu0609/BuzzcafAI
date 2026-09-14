"""The studio's departments: who reports to whom, and how to reach them.

Until v9 these classes had no caller outside a test. They now back
`GET /api/departments`, the Departments tab, and a workflow step that names a
department instead of a persona. Instances are cached here and build their
agents lazily, so importing this module costs nothing.
"""

from typing import Dict, List, Optional

from app.departments.base import Department
from app.departments.executive import ExecutiveDepartment
from app.departments.project_management import ProjectManagementDepartment
from app.departments.research import ResearchDepartment
from app.departments.writing import WritingDepartment
from app.departments.production import ProductionDepartment
from app.departments.publishing import PublishingDepartment
from app.departments.marketing import MarketingDepartment
from app.departments.analytics import AnalyticsDepartment
from app.departments.knowledge import KnowledgeDepartment
from app.departments.automation import AutomationDepartment
from app.departments.infrastructure import InfrastructureDepartment
from app.departments.support import SupportDepartment
from app.departments.creative import CreativeDepartment

DEPARTMENT_CLASSES = [
    ExecutiveDepartment,
    ProjectManagementDepartment,
    ResearchDepartment,
    WritingDepartment,
    ProductionDepartment,
    PublishingDepartment,
    MarketingDepartment,
    AnalyticsDepartment,
    KnowledgeDepartment,
    AutomationDepartment,
    InfrastructureDepartment,
    SupportDepartment,
    CreativeDepartment,
]

_instances: Optional[Dict[str, Department]] = None


def list_departments() -> List[Department]:
    """One cached instance per department class, in catalogue order."""
    global _instances
    if _instances is None:
        _instances = {}
        for cls in DEPARTMENT_CLASSES:
            dept = cls()
            _instances[dept.name.lower()] = dept
    return list(_instances.values())


def get_department(name: str) -> Optional[Department]:
    """A department by name, case- and space-insensitive ('project management')."""
    if not name:
        return None
    list_departments()
    key = name.strip().lower()
    assert _instances is not None
    if key in _instances:
        return _instances[key]
    squashed = key.replace(" ", "").replace("_", "")
    for dept_key, dept in _instances.items():
        if dept_key.replace(" ", "").replace("_", "") == squashed:
            return dept
    return None


__all__ = [
    "Department",
    "ExecutiveDepartment",
    "ProjectManagementDepartment",
    "ResearchDepartment",
    "WritingDepartment",
    "ProductionDepartment",
    "PublishingDepartment",
    "MarketingDepartment",
    "AnalyticsDepartment",
    "KnowledgeDepartment",
    "AutomationDepartment",
    "InfrastructureDepartment",
    "SupportDepartment",
    "CreativeDepartment",
    "DEPARTMENT_CLASSES",
    "list_departments",
    "get_department",
]
