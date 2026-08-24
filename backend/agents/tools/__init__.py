"""Tool registry: what each employee is allowed to call, and a record of every call.

The set an employee sees is derived from their grants, so a technical writer
never gets offered `commit_changes` and a manager never edits code. Grants used
to be implied by a role; they are rows now, so one can expire or be revoked
without rewriting anybody's job description.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select

from models import Connection, Employee, ToolCall, ToolGrant

from .base import Tool, ToolContext, ToolResult, failed
from .chat import TOOLS as CHAT_TOOLS
from .code import DIRECTORY_TOOLS
from .code import TOOLS as WORKSPACE_TOOLS
from .documents import TOOLS as DOCUMENT_TOOLS
from .memory_tools import TOOLS as MEMORY_TOOLS
from .protocol import TOOLS as PROTOCOL_TOOLS
from .research import TOOLS as RESEARCH_TOOLS
from .tracker import TOOLS as TRACKER_TOOLS
from .wiki import TOOLS as WIKI_TOOLS

log = logging.getLogger(__name__)

ALL_TOOLS: list[Tool] = [
    *TRACKER_TOOLS,
    *WIKI_TOOLS,
    *CHAT_TOOLS,
    *WORKSPACE_TOOLS,
    *DOCUMENT_TOOLS,
    *RESEARCH_TOOLS,
    *DIRECTORY_TOOLS,
    *MEMORY_TOOLS,
    *PROTOCOL_TOOLS,
]
BY_NAME: dict[str, Tool] = {tool.name: tool for tool in ALL_TOOLS}

# Groups everybody gets: knowing who your colleagues are, remembering things,
# and being able to answer a colleague are not privileges.
ALWAYS_GRANTED = {"directory", "memory", "protocol"}

# Argument names whose values never reach the audit log.
SECRET_ARGUMENTS = {"password", "token", "secret", "api_key", "authorization", "key"}
MAX_ARGUMENT_CHARS = 2000


def granted_targets(employee: Employee) -> set[str]:
    """Groups and tool names this employee may use.

    The toolbelt is the seed. Explicit grants add to it and can be revoked or
    time-limited without touching the employee record.
    """
    targets = set(employee.toolbelt or []) | set(ALWAYS_GRANTED)
    session = getattr(employee, "_sa_instance_state", None)
    db = session.session if session is not None else None
    if db is None:
        return targets

    now = datetime.now(UTC)
    for grant in db.scalars(select(ToolGrant).where(ToolGrant.employee_id == employee.id)):
        if grant.revoked_at is not None:
            targets.discard(grant.target)
            continue
        if grant.expires_at and _as_utc(grant.expires_at) < now:
            continue
        targets.add(grant.target)
    return targets


def _session_of(employee: Employee):
    state = getattr(employee, "_sa_instance_state", None)
    return state.session if state is not None else None


def remote_tools(employee: Employee) -> list[Tool]:
    """Tools from MCP servers this company has registered.

    Cached definitions, so building the list is a database read rather than a
    round trip to somebody else's server on every turn.
    """
    db = _session_of(employee)
    if db is None:
        return []
    try:
        from services import mcp_client

        return mcp_client.tools_for(db, employee.company)
    except Exception:
        log.debug("could not load remote tools", exc_info=True)
        return []


def for_employee(employee: Employee) -> list[Tool]:
    allowed = granted_targets(employee)
    catalogue = [*ALL_TOOLS, *remote_tools(employee)]
    return [tool for tool in catalogue if tool.group in allowed or tool.name in allowed]


def schemas(tools: list[Tool]) -> list[dict]:
    return [tool.schema() for tool in tools]


def execute(name: str, ctx: ToolContext, arguments: dict) -> ToolResult:
    """Run one tool call as this employee, and write down that it happened."""
    available = for_employee(ctx.employee)
    tool = BY_NAME.get(name) or next((item for item in available if item.name == name), None)
    if not tool:
        close = [known for known in BY_NAME if name in known or known in name][:3]
        return failed(
            f"Unknown tool: {name}",
            f"Did you mean {', '.join(close)}?" if close else "Use one of the tools listed to you.",
        )

    if ctx.company.halted:
        return failed(
            "This company is halted.",
            f"Reason: {ctx.company.halt_reason or 'stopped by the operator'}. Stop and wait.",
        )

    if name not in {allowed.name for allowed in available}:
        return failed(
            f"You do not have access to {name}.",
            "Ask the colleague whose job this is, or say on the work item that you are blocked.",
        )

    if tool.requires_connection and not _connected(ctx, tool.group):
        return failed(
            f"{name} needs a {tool.group} connection, and this company has none configured.",
            "Do the part you can with the built-in tools and say what is missing.",
        )

    started = time.perf_counter()
    try:
        raw = tool.handler(ctx, **arguments)
        result = raw if isinstance(raw, ToolResult) else ToolResult(text=str(raw))
    except TypeError as exc:
        result = failed(
            f"Bad arguments for {name}: {exc}",
            "Check the parameter names in the tool description and call it again.",
        )
    except Exception as exc:  # surfaced to the model so it can recover
        log.warning("%s failed: %s", name, exc)
        result = failed(f"{name} failed: {exc}", "")

    _audit(ctx, tool, arguments, result, int((time.perf_counter() - started) * 1000))
    if result.untrusted:
        ctx.tainted = True
    return result


def _connected(ctx: ToolContext, group: str) -> bool:
    return bool(
        ctx.db.scalar(
            select(Connection).where(
                Connection.company_id == ctx.company.id,
                Connection.tool == group,
                Connection.status == "connected",
            )
        )
    )


def redact(arguments: dict) -> dict:
    """Keep secrets and whole files out of the audit trail."""
    clean: dict = {}
    for key, value in (arguments or {}).items():
        if key.lower() in SECRET_ARGUMENTS:
            clean[key] = "[redacted]"
        elif isinstance(value, str) and len(value) > MAX_ARGUMENT_CHARS:
            clean[key] = value[:MAX_ARGUMENT_CHARS] + f"… [{len(value)} chars]"
        else:
            clean[key] = value
    return clean


def _audit(
    ctx: ToolContext, tool: Tool, arguments: dict, result: ToolResult, duration_ms: int
) -> None:
    try:
        ctx.db.add(
            ToolCall(
                created_at=datetime.now(UTC),
                company_id=ctx.company.id,
                employee_id=ctx.employee.id,
                project_id=ctx.project.id if ctx.project else None,
                work_item_id=ctx.work_item.id if ctx.work_item else None,
                run_id=ctx.run.id if ctx.run else None,
                task_id=ctx.task_id,
                step_id=ctx.step_id,
                tool=tool.name,
                arguments=redact(arguments),
                ok=result.ok,
                error=None if result.ok else result.text[:2000],
                result_preview=result.text[:1000],
                duration_ms=duration_ms,
            )
        )
        ctx.db.flush()
    except Exception:
        log.debug("could not audit %s", tool.name, exc_info=True)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


__all__ = [
    "ALL_TOOLS",
    "BY_NAME",
    "Tool",
    "ToolContext",
    "ToolResult",
    "execute",
    "for_employee",
    "granted_targets",
    "redact",
    "schemas",
]
