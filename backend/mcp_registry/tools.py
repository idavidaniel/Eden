"""Bridges the platform's built-in tools onto MCP.

The same handlers the AI employees call internally are exposed over JSON-RPC.
The caller's token decides which employee the call acts as, and which tools it
may reach — an external client gets exactly the surface that employee has, no
more, and the call is audited under their name like any other.
"""

from typing import Any

from sqlalchemy import select

from agents import tools as agent_tools
from agents.tools.base import ToolContext
from db import session
from models import Company, Employee, Project

CONTEXT_PARAMS = {
    "project_id": {
        "type": "string",
        "description": "Project the action applies to. Defaults to the most recent one.",
    },
    "work_item_id": {"type": "string", "description": "Work item the action is about"},
}


def list_definitions(employee: Employee | None = None) -> list[dict]:
    """Tool definitions, narrowed to what this employee may actually call."""
    catalogue = agent_tools.for_employee(employee) if employee else agent_tools.ALL_TOOLS
    definitions = []
    for tool in catalogue:
        schema = tool.schema()["function"]
        definitions.append(
            {
                "name": tool.name,
                "description": f"[{tool.group}] {tool.description}",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        **schema["parameters"].get("properties", {}),
                        **CONTEXT_PARAMS,
                    },
                    "required": list(schema["parameters"].get("required", [])),
                },
                "annotations": {
                    "readOnlyHint": tool.read_only,
                    "destructiveHint": tool.destructive,
                },
            }
        )
    return definitions


def call(name: str, arguments: dict[str, Any], agent: dict | None) -> str:
    if not agent:
        raise ValueError(
            "This call is not authenticated, so there is nobody to attribute it to."
        )

    arguments = dict(arguments or {})
    project_id = arguments.pop("project_id", None)
    work_item_id = arguments.pop("work_item_id", None)

    db = session()
    try:
        employee = db.get(Employee, agent["employee_id"])
        if not employee:
            raise ValueError("That token's employee no longer exists.")
        company = db.get(Company, employee.company_id)

        scopes = set(agent.get("scopes") or [])
        tool = agent_tools.BY_NAME.get(name)
        if tool and scopes and "tools:*" not in scopes and f"tools:{tool.group}" not in scopes:
            raise ValueError(
                f"This token does not carry tools:{tool.group}. It has: "
                f"{', '.join(sorted(scopes)) or 'nothing'}."
            )

        project = db.get(Project, project_id) if project_id else None
        if project is None and project_id is None:
            project = db.scalar(
                select(Project)
                .where(Project.company_id == company.id)
                .order_by(Project.created_at.desc())
            )
        work_item = None
        if work_item_id:
            from models import WorkItem

            work_item = db.get(WorkItem, work_item_id)

        ctx = ToolContext(
            db=db,
            company=company,
            employee=employee,
            project=project,
            work_item=work_item,
        )
        result = agent_tools.execute(name, ctx, arguments)
        db.commit()
        return result.for_model()
    finally:
        db.close()
