"""Workspace tools — the built-in equivalent of an editor plus git."""

from sqlalchemy import select

from models import Employee
from services import artifacts as artifact_service
from services import events, runners, workspace

from .base import Tool, ToolContext, ToolResult, failed, obj, string


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


def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
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
    artifact = _register(ctx, path)
    return ToolResult(
        text=f"{'Created' if result['created'] else 'Updated'} {path} ({result['bytes']} bytes).",
        artifacts=[artifact] if artifact else [],
    )


def _register(ctx: ToolContext, path: str):
    """Record the file as an artifact so checks and the ledger can see it."""
    if not ctx.project:
        return None
    return artifact_service.record_workspace_file(
        ctx.db,
        company=ctx.company,
        project=ctx.project,
        path=path,
        work_item_id=ctx.work_item.id if ctx.work_item else None,
        produced_by=ctx.employee,
    )


def edit_file(ctx: ToolContext, path: str, old_text: str, new_text: str) -> ToolResult:
    """Replace one exact snippet in a file.

    Without this, changing one line of a 400-line file means re-emitting the
    whole file, which is what employees kept running out of budget doing.
    """
    space = _workspace(ctx)
    try:
        content = space.read(path)
    except Exception as exc:
        return failed(f"Could not read {path}: {exc}", "Call list_files to see what exists.")

    occurrences = content.count(old_text)
    if occurrences == 0:
        return failed(
            f"No match in {path}.",
            "The text must match exactly, including indentation. Read the file again "
            "and copy the snippet verbatim.",
        )
    if occurrences > 1:
        return failed(
            f"{occurrences} matches in {path}; the snippet must be unique.",
            "Include a surrounding line or two to disambiguate.",
        )

    space.write(path, content.replace(old_text, new_text, 1))
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="code.write",
        summary=f"edited {path}",
        payload={"path": path, "lines_changed": new_text.count("\n") - old_text.count("\n")},
    )
    artifact = _register(ctx, path)
    return ToolResult(text=f"Edited {path}.", artifacts=[artifact] if artifact else [])


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


def run_command(ctx: ToolContext, command: str, cwd: str = "", profile: str = "") -> ToolResult:
    """Run a test or script inside the workspace and return what it printed."""
    space = _workspace(ctx)
    try:
        result = space.run(command, cwd=cwd, profile=profile or None)
    except Exception as exc:
        return failed(
            f"Could not run it: {exc}",
            f"Programs available here: {', '.join(sorted(workspace.allowed_commands()))}.",
        )

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
    passed = result["exit_code"] == 0
    verdict = "succeeded" if passed else f"failed (exit {result['exit_code']})"
    return ToolResult(
        text=f"$ {command}\n{result['output']}\n[{verdict}]",
        ok=passed,
        error_hint="" if passed else "Fix what it reported, then run it again.",
    )


def commit_changes(ctx: ToolContext, message: str) -> ToolResult:
    space = _workspace(ctx)
    result = space.commit(message, ctx.git_author)
    if not result["committed"]:
        return ToolResult(text="Nothing to commit — the workspace matches the last commit.")
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
    return ToolResult(text=f"Committed {result['sha']}: {message}")


def list_colleagues(ctx: ToolContext) -> ToolResult:
    people = list(ctx.db.scalars(select(Employee).where(Employee.company_id == ctx.company.id)))
    lines = []
    for person in people:
        capabilities = ", ".join(person.capabilities or []) or "—"
        mine = " [you]" if person.id == ctx.employee.id else ""
        lines.append(
            f"{person.name} — {person.title} ({person.department}){mine}"
            f"\n    can: {capabilities}"
        )
    return ToolResult(text="\n".join(lines))


def toolchains(ctx: ToolContext) -> ToolResult:
    """What can actually be run here, so nobody spends a call finding out."""
    status = runners.status()
    lines = [
        f"{item['name']}: {', '.join(item['commands'])} — {item['where']}"
        + ("" if item["available"] else " (not available)")
        for item in status["profiles"]
    ]
    return ToolResult(text="\n".join(lines))


TOOLS = [
    Tool(
        name="list_files",
        group="workspace",
        description="List files in the project workspace.",
        parameters=obj({"path": string("Optional path prefix")}, required=[]),
        read_only=True,
        handler=list_files,
    ),
    Tool(
        name="read_file",
        group="workspace",
        description="Read a file from the project workspace.",
        parameters=obj({"path": string("Path relative to the workspace root")}),
        read_only=True,
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
        name="edit_file",
        group="workspace",
        description=(
            "Change part of an existing file by replacing an exact snippet. Prefer "
            "this over write_file for edits: it does not require re-sending the "
            "whole file. The snippet must appear exactly once."
        ),
        parameters=obj(
            {
                "path": string("Path relative to the workspace root"),
                "old_text": string("Exact text to replace, copied verbatim from the file"),
                "new_text": string("Replacement text"),
            }
        ),
        handler=edit_file,
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
            "features (no pipes, redirection or chaining). Available programs: "
            + ", ".join(sorted(workspace.allowed_commands()))
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
                "profile": string(
                    "Toolchain to run it under. Leave empty to pick automatically."
                ),
            },
            required=["command"],
        ),
        handler=run_command,
        cost_hint="slow",
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
        description="List everyone who works at this company, what they do and what they can do.",
        parameters=obj({}, required=[]),
        read_only=True,
        handler=list_colleagues,
    ),
    Tool(
        name="list_toolchains",
        group="directory",
        description="List the toolchains available in this workspace and which commands each runs.",
        parameters=obj({}, required=[]),
        read_only=True,
        handler=toolchains,
    ),
]
