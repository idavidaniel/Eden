"""The original check: run a command and believe the exit code, not the author."""

from models import Check
from services import workspace

from .base import CheckContext, Verdict, error, skipped

MAX_OUTPUT = 4000


def run(check: Check, ctx: CheckContext) -> Verdict:
    spec = check.spec or {}
    command = spec.get("command")
    if not command:
        return error(f"{check.name}: no command was configured.")
    if not ctx.project:
        return skipped(f"{check.name}: no project, so there is no workspace to run in.")

    space = workspace.for_project(ctx.company.slug, ctx.project.key)
    space.init(ctx.project.name)
    try:
        result = space.run(
            command,
            cwd=spec.get("cwd", ""),
            timeout=spec.get("timeout"),
            profile=spec.get("profile"),
        )
    except Exception as exc:
        return Verdict(
            status="fail",
            detail=f"{check.name}: could not run `{command}` — {exc}",
            evidence={"command": command, "cwd": spec.get("cwd", "")},
        )

    output = result["output"][-MAX_OUTPUT:]
    evidence = {
        "command": result["command"],
        "exit_code": result["exit_code"],
        "output": output,
        "cwd": spec.get("cwd", ""),
        "profile": result.get("profile", "host"),
    }
    if result["exit_code"] == 0:
        return Verdict(status="pass", detail=f"`{command}` passed.", evidence=evidence)
    return Verdict(
        status="fail",
        detail=f"`{command}` failed with exit {result['exit_code']}.",
        evidence=evidence,
    )
