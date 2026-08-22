"""Workspace tools — the built-in equivalent of an editor plus git."""

from sqlalchemy import select

from models import Employee
from services import events, workspace

from .base import Tool, ToolContext, obj, string


def _workspace(ctx: ToolContext) -> workspace.Workspace:
    if not ctx.project:
        raise ValueError("No project is in scope, so there is no workspace.")
    space = workspace.for_project(ctx.company.slug, ctx.project.key)
    space.init(ctx.project.name)
    return space


def list_files(ctx: ToolContext, path: str = "") -> str:
    entries = _workspace(ctx).tree()
    if path:
        entries = [e for e in entries if e["path"].startswith(path.lstrip("/"))]
    if not entries:
        return "The workspace is empty."
    return "\n".join(
        f"{'DIR ' if e['type'] == 'dir' else 'FILE'} {e['path']}" for e in entries[:200]
    )


def read_file(ctx: ToolContext, path: str) -> str:
    return _workspace(ctx).read(path)


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    space = _workspace(ctx)
    result = space.write(path, content)
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="code.write",
        summary=f"{'created' if result['created'] else 'edited'} {path}",
        payload={"path": path, "bytes": result["bytes"]},
    )
    return f"{'Created' if result['created'] else 'Updated'} {path} ({result['bytes']} bytes)."


def delete_file(ctx: ToolContext, path: str) -> str:
    _workspace(ctx).delete(path)
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="code.delete",
        summary=f"deleted {path}",
        payload={"path": path},
    )
    return f"Deleted {path}."


def run_command(ctx: ToolContext, command: str, cwd: str = "") -> str:
    """Run a test or script inside the workspace and return what it printed."""
    space = _workspace(ctx)
    try:
        result = space.run(command, cwd=cwd)
    except Exception as exc:
        return f"Could not run it: {exc}"

    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="code.run",
        summary=f"ran `{command[:80]}` → exit {result['exit_code']}",
        payload={
            "command": command,
            "exit_code": result["exit_code"],
            "output": result["output"][:2000],
        },
    )
    verdict = "succeeded" if result["exit_code"] == 0 else f"failed (exit {result['exit_code']})"
    return f"$ {command}\n{result['output']}\n[{verdict}]"


def commit_changes(ctx: ToolContext, message: str) -> str:
    space = _workspace(ctx)
    result = space.commit(message, ctx.git_author)
    if not result["committed"]:
        return "Nothing to commit — the workspace matches the last commit."
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="code.commit",
        summary=f"committed {result['sha']}: {message[:120]}",
        payload=result,
    )
    return f"Committed {result['sha']}: {message}"


def list_colleagues(ctx: ToolContext) -> str:
    people = list(ctx.db.scalars(select(Employee).where(Employee.company_id == ctx.company.id)))
    return "\n".join(
        f"{p.name} — {p.title} ({p.department}){' [you]' if p.id == ctx.employee.id else ''}"
        for p in people
    )


TOOLS = [
    Tool(
        name="list_files",
        group="workspace",
        description="List files in the project workspace.",
        parameters=obj({"path": string("Optional path prefix")}, required=[]),
        handler=list_files,
    ),
    Tool(
        name="read_file",
        group="workspace",
        description="Read a file from the project workspace.",
        parameters=obj({"path": string("Path relative to the workspace root")}),
        handler=read_file,
    ),
    Tool(
        name="write_file",
        group="workspace",
        description="Create or overwrite a file in the project workspace with full content.",
        parameters=obj(
            {
                "path": string("Path relative to the workspace root"),
                "content": string("Full file content"),
            }
        ),
        handler=write_file,
    ),
    Tool(
        name="delete_file",
        group="workspace",
        description="Delete a file from the project workspace.",
        parameters=obj({"path": string("Path relative to the workspace root")}),
        handler=delete_file,
    ),
    Tool(
        name="run_command",
        group="workspace",
        description=(
            "Run a command in the workspace to check your work, e.g. 'pytest -q', "
            "'flutter analyze', 'flutter test', 'python3 main.py --help'. No shell "
            "features (no pipes, redirection or chaining). Allowed programs: "
            + ", ".join(sorted(workspace.ALLOWED_COMMANDS))
            + "."
        ),
        parameters=obj(
            {
                "command": string("The command line to run"),
                "cwd": string(
                    "Subdirectory to run it in, relative to the workspace root. "
                    "Required for per-package commands, e.g. cwd='teleprompter_mobile' "
                    "with command='flutter pub get'."
                ),
            },
            required=["command"],
        ),
        handler=run_command,
    ),
    Tool(
        name="commit_changes",
        group="workspace",
        description="Commit everything currently in the workspace, authored by you.",
        parameters=obj({"message": string("Commit message")}),
        handler=commit_changes,
    ),
]

DIRECTORY_TOOLS = [
    Tool(
        name="list_colleagues",
        group="directory",
        description="List everyone who works at this company and what they do.",
        parameters=obj({}, required=[]),
        handler=list_colleagues,
    ),
]
