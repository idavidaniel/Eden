"""Tool registry: what each employee is allowed to call.

The set an employee sees is derived from their toolbelt, so a technical writer
never gets offered `commit_changes` and a manager never edits code.
"""

from models import Employee

from .base import Tool, ToolContext
from .chat import TOOLS as CHAT_TOOLS
from .code import DIRECTORY_TOOLS
from .code import TOOLS as WORKSPACE_TOOLS
from .tracker import TOOLS as TRACKER_TOOLS
from .wiki import TOOLS as WIKI_TOOLS

ALL_TOOLS: list[Tool] = [
    *TRACKER_TOOLS,
    *WIKI_TOOLS,
    *CHAT_TOOLS,
    *WORKSPACE_TOOLS,
    *DIRECTORY_TOOLS,
]
BY_NAME: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}


def for_employee(employee: Employee) -> list[Tool]:
    allowed = set(employee.toolbelt or []) | {"directory"}
    return [tool for tool in ALL_TOOLS if tool.group in allowed]


def schemas(tools: list[Tool]) -> list[dict]:
    return [tool.schema() for tool in tools]


def execute(name: str, ctx: ToolContext, arguments: dict) -> str:
    tool = BY_NAME.get(name)
    if not tool:
        return f"Unknown tool: {name}"
    allowed = {t.name for t in for_employee(ctx.employee)}
    if name not in allowed:
        return f"You do not have access to {name}."
    try:
        return str(tool.handler(ctx, **arguments))
    except TypeError as exc:
        return f"Bad arguments for {name}: {exc}"
    except Exception as exc:  # surfaced to the model so it can recover
        return f"{name} failed: {exc}"


__all__ = ["ALL_TOOLS", "BY_NAME", "Tool", "ToolContext", "execute", "for_employee", "schemas"]
