"""Bridges the platform's built-in tools onto MCP.

The same handlers the AI employees call internally are exposed over JSON-RPC, so
an external MCP client can drive a company's tracker, wiki, chat and workspace
using an employee's identity.
"""

from typing import Any

from sqlalchemy import select

from agents import tools as agent_tools
from agents.tools.base import ToolContext
from db import session
from models import Company, Employee, Project

IDENTITY_PARAMS = {
    "employee_id": {"type": "string", "description": "The employee acting (their platform id)"},
    "project_id": {"type": "string", "description": "Project the action applies to, when relevant"},
}


def list_definitions() -> list[dict]:
    definitions = []
    for tool in agent_tools.ALL_TOOLS:
        schema = tool.schema()["function"]
        parameters = {
            "type": "object",
            "properties": {**schema["parameters"].get("properties", {}), **IDENTITY_PARAMS},
            "required": [*schema["parameters"].get("required", []), "employee_id"],
        }
        definitions.append(
            {
                "name": tool.name,
                "description": f"[{tool.group}] {tool.description}",
                "inputSchema": parameters,
            }
        )
    return definitions


def call(name: str, arguments: dict[str, Any]) -> str:
    arguments = dict(arguments or {})
    employee_id = arguments.pop("employee_id", None)
    project_id = arguments.pop("project_id", None)
    if not employee_id:
        raise ValueError("employee_id is required so the action is attributed to someone.")

    db = session()
    try:
        employee = db.get(Employee, employee_id)
        if not employee:
            raise ValueError(f"No employee with id {employee_id}.")
        company = db.get(Company, employee.company_id)
        project = db.get(Project, project_id) if project_id else None
        if project is None and project_id is None:
            project = db.scalar(
                select(Project)
                .where(Project.company_id == company.id)
                .order_by(Project.created_at.desc())
            )

        ctx = ToolContext(db=db, company=company, employee=employee, project=project)
        result = agent_tools.execute(name, ctx, arguments)
        db.commit()
        return result
    finally:
        db.close()
