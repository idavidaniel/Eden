"""What a check is handed, and what it must return."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from models import Artifact, Check, Company, Employee, Project, WorkItem


@dataclass
class CheckContext:
    """Everything a check needs to reach a verdict on its own."""

    db: Session
    company: Company
    project: Project | None = None
    work_item: WorkItem | None = None
    artifact: Artifact | None = None
    # The artifact's text, read once and shared between checks in a batch.
    content: str = ""
    run_id: str | None = None
    task_id: str | None = None
    # Who produced the work. Evaluators never see this.
    author: Employee | None = None


@dataclass
class Verdict:
    status: str  # pass | fail | error | skipped | pending
    detail: str = ""
    score: float | None = None
    evidence: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def skipped(reason: str) -> Verdict:
    return Verdict(status="skipped", detail=reason)


def error(reason: str) -> Verdict:
    return Verdict(status="error", detail=reason)


def needs_artifact(check: Check, ctx: CheckContext) -> Verdict | None:
    if ctx.artifact is None:
        return skipped(f"{check.name}: nothing to check yet — no artifact was produced.")
    if not ctx.content.strip():
        return Verdict(
            status="fail",
            detail=f"{check.name}: the artifact is empty.",
            evidence={"content_hash": ctx.artifact.content_hash, "chars": 0},
        )
    return None
