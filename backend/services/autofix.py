"""Automated debugging: build, read the failure, fix it, build again.

The manual loop was: notice the preview failed, read the compiler output,
reopen a work_item, start a run, check again. This does that on its own, and stops
as soon as the check passes or it stops making progress.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Employee, Project, WorkItem
from services import roles as roles_service
from services import workspace

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 4
# Errors quoted into the prompt. Enough to see the pattern, not enough to drown.
MAX_ERROR_LINES = 25


@dataclass
class CommandOutcome:
    passed: bool
    command: str
    output: str

    def errors(self) -> list[str]:
        """The lines that look like compiler errors, most useful first."""
        lines = [
            line.strip()
            for line in self.output.splitlines()
            if re.search(r"\berror\b|\bError:|^\s*\^|Undefined|not found", line, re.IGNORECASE)
        ]
        return lines[:MAX_ERROR_LINES] or self.output.splitlines()[-MAX_ERROR_LINES:]

    def snippets(self, space: "workspace.Workspace", cwd: str = "", radius: int = 6) -> str:
        """The source around each reported error.

        Without this the fixer has to grep its way to the line, which is where
        its whole step budget went - and it still edited the wrong places.
        """
        seen: set[tuple[str, int]] = set()
        blocks: list[str] = []
        for line in self.errors():
            match = re.search(r"([\w./-]+\.\w+):(\d+):(\d+)", line)
            if not match:
                continue
            path, number = match.group(1), int(match.group(2))
            if (path, number) in seen:
                continue
            seen.add((path, number))

            relative = f"{cwd.rstrip('/')}/{path}" if cwd else path
            try:
                source = space.read(relative).splitlines()
            except Exception:
                continue

            start = max(0, number - radius - 1)
            end = min(len(source), number + radius)
            body = "\n".join(
                f"{'>' if index + 1 == number else ' '} {index + 1:4} | {source[index]}"
                for index in range(start, end)
            )
            blocks.append(f"--- {relative}:{number}\n{body}")
            if len(blocks) >= 6:
                break
        return "\n\n".join(blocks)

    def signature(self) -> str:
        """Used to notice that an attempt changed nothing."""
        return "\n".join(sorted(self.errors()))


def run_check(project: Project, company: Company, command: str, cwd: str = "") -> CommandOutcome:
    space = workspace.for_project(company.slug, project.key)
    space.init(project.name)
    try:
        result = space.run(command, cwd=cwd)
    except Exception as exc:
        return CommandOutcome(passed=False, command=command, output=str(exc))
    return CommandOutcome(passed=result["exit_code"] == 0, command=command, output=result["output"])


def pick_fixer(db: Session, company_id: str, hint: str) -> Employee | None:
    """Whoever is most plausibly responsible for the failing code."""
    team = list(db.scalars(select(Employee).where(Employee.company_id == company_id)))
    if not team:
        return None
    company = db.get(Company, company_id)

    lowered = hint.lower()
    if any(token in lowered for token in (".dart", "flutter", "widget", "pubspec")):
        preferred = ["frontend_engineer", "architect", "backend_engineer"]
    elif any(token in lowered for token in (".py", "pytest", "traceback")):
        preferred = ["backend_engineer", "devops_engineer", "architect"]
    else:
        preferred = ["backend_engineer", "frontend_engineer", "architect"]

    for role in preferred:
        match = next((e for e in team if e.role_key == role), None)
        if match:
            return match
    return roles_service.pick_for(db, company, team, capability="debug") or team[0]


def ensure_bug_ticket(
    db: Session, project: Project, fixer: Employee, check: CommandOutcome
) -> WorkItem:
    """One reusable bug work_item per project, so attempts do not litter the board."""
    work_item = db.scalar(
        select(WorkItem).where(
            WorkItem.project_id == project.id,
            WorkItem.kind == "bug",
            WorkItem.title.like("Auto-debug:%"),
            WorkItem.status != "done",
        )
    )
    errors = "\n".join(check.errors())
    description = (
        f"`{check.command}` is failing. Fix the code until it passes.\n\n"
        f"Reported problems:\n```\n{errors}\n```"
    )

    if work_item:
        work_item.description = description
        work_item.assignee_id = fixer.id
        work_item.status = "in_progress"
    else:
        project.ticket_counter += 1
        work_item = WorkItem(
            project_id=project.id,
            key=f"{project.key}-{project.ticket_counter}",
            title=f"Auto-debug: make `{check.command}` pass",
            description=description,
            kind="bug",
            status="in_progress",
            priority="high",
            assignee_id=fixer.id,
            role_hint=fixer.role_key,
            acceptance_criteria=[f"`{check.command}` exits 0"],
            order=999,
        )
        db.add(project)
    db.add(work_item)
    db.flush()
    return work_item
