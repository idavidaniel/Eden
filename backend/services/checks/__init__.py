"""Running checks, and writing down what happened.

Nothing in here asks an agent whether its work is good. Every kind either
executes something, parses something, matches text against a source, or asks a
person. The rubric kind uses a model, and is the one place that does — which is
why it carries a mechanical quote check on the evaluator.
"""

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Artifact, Check, CheckResult, Company, Employee, Project, WorkItem

from .. import artifacts as artifact_service
from .. import events, ledger
from . import assertion, citation, command, human, rubric, schema
from .base import CheckContext, Verdict, error

log = logging.getLogger(__name__)

RUNNERS = {
    "command": command.run,
    "schema": schema.run,
    "assertion": assertion.run,
    "citation": citation.run,
    "rubric": rubric.run,
    "human": human.run,
}

# Kinds that reach a verdict by reading a deliverable. A check of one of these
# kinds bound to a work item is about the thing the item produced, so it has to
# be handed that artifact rather than run against nothing.
READS_AN_ARTIFACT = {"schema", "assertion", "citation", "rubric"}

# A verdict of `pending` blocks closure just as firmly as a failure; it is
# separated so the interface can say "waiting on you" rather than "broken".
BLOCKING = {"fail", "error", "pending"}


def applicable(
    db: Session,
    company: Company,
    *,
    project: Project | None = None,
    work_item: WorkItem | None = None,
    artifact: Artifact | None = None,
) -> list[Check]:
    """Checks in scope, narrowest binding first.

    A check bound to this work item always applies. A check bound to an artifact
    kind applies when an artifact of that kind is present. A project-wide check
    applies to the project. Company-level checks with no artifact kind are
    templates and are not run directly.
    """
    rows = list(
        db.scalars(
            select(Check).where(Check.company_id == company.id, Check.enabled.is_(True))
        )
    )
    chosen: list[Check] = []
    for check in rows:
        if check.work_item_id:
            if work_item and check.work_item_id == work_item.id:
                chosen.append(check)
            continue
        if check.artifact_kind:
            if artifact and artifact.kind == check.artifact_kind:
                chosen.append(check)
            continue
        if check.project_id:
            if project and check.project_id == project.id:
                chosen.append(check)
            continue
    return sorted(chosen, key=lambda check: (check.position, check.key))


def run_one(
    db: Session,
    check: Check,
    *,
    company: Company,
    project: Project | None = None,
    work_item: WorkItem | None = None,
    artifact: Artifact | None = None,
    author: Employee | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> CheckResult:
    runner = RUNNERS.get(check.kind)
    started = time.perf_counter()
    if not runner:
        verdict = error(f"Unknown check kind '{check.kind}'.")
    else:
        ctx = CheckContext(
            db=db,
            company=company,
            project=project,
            work_item=work_item,
            artifact=artifact,
            content=artifact_service.read(db, artifact) if artifact else "",
            run_id=run_id,
            task_id=task_id,
            author=author,
        )
        try:
            verdict = runner(check, ctx)
        except Exception as exc:  # a broken check must not look like a passing one
            log.exception("check %s blew up", check.key)
            verdict = error(f"{check.name}: the check itself failed — {exc}")

    return _record(
        db,
        check=check,
        verdict=verdict,
        company=company,
        project=project,
        work_item=work_item,
        artifact=artifact,
        run_id=run_id,
        task_id=task_id,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def run_for_work_item(
    db: Session,
    *,
    company: Company,
    project: Project,
    work_item: WorkItem,
    author: Employee | None = None,
    run_id: str | None = None,
    task_id: str | None = None,
) -> list[CheckResult]:
    """Every check that applies to this item and the artifacts it produced."""
    produced = list(
        db.scalars(
            select(Artifact).where(
                Artifact.work_item_id == work_item.id, Artifact.superseded_by.is_(None)
            )
        )
    )
    results: list[CheckResult] = []

    for check in applicable(db, company, project=project, work_item=work_item):
        # A document check with nothing to read would record "skipped" and then
        # be passed over by the artifact loop below, so the deliverable it was
        # written for would never actually be judged.
        targets = produced if (check.kind in READS_AN_ARTIFACT and produced) else [None]
        for artifact in targets:
            results.append(
                run_one(
                    db,
                    check,
                    company=company,
                    project=project,
                    work_item=work_item,
                    artifact=artifact,
                    author=author,
                    run_id=run_id,
                    task_id=task_id,
                )
            )

    for artifact in produced:
        for check in applicable(
            db, company, project=project, work_item=work_item, artifact=artifact
        ):
            if any(result.check_id == check.id for result in results):
                continue
            results.append(
                run_one(
                    db,
                    check,
                    company=company,
                    project=project,
                    work_item=work_item,
                    artifact=artifact,
                    author=author,
                    run_id=run_id,
                    task_id=task_id,
                )
            )
    return results


def verdict_for(results: list[CheckResult]) -> dict:
    """One answer for a set of results: did this work pass, and if not, why."""
    required = [result for result in results if result.evidence.get("required", True)]
    considered = required or results
    failed = [result for result in considered if result.status in {"fail", "error"}]
    pending = [result for result in considered if result.status == "pending"]
    return {
        "ran": len(results),
        "passed": len([r for r in considered if r.status == "pass"]),
        "failed": len(failed),
        "pending": len(pending),
        "ok": not failed and not pending,
        "blocked": bool(pending) and not failed,
        "summary": _summary(considered, failed, pending),
    }


def _summary(considered: list[CheckResult], failed: list, pending: list) -> str:
    if not considered:
        return "No checks apply to this yet."
    if failed:
        return "; ".join(result.detail for result in failed[:3])
    if pending:
        return "; ".join(result.detail for result in pending[:3])
    return f"{len(considered)} check(s) passed."


def latest_for_work_item(db: Session, work_item_id: str) -> list[CheckResult]:
    """The most recent result per check, so a board shows now rather than history."""
    rows = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.work_item_id == work_item_id)
            .order_by(CheckResult.created_at.desc())
        )
    )
    seen: set[str] = set()
    latest: list[CheckResult] = []
    for row in rows:
        marker = f"{row.check_id}:{row.artifact_id}"
        if marker in seen:
            continue
        seen.add(marker)
        latest.append(row)
    return list(reversed(latest))


def _record(
    db: Session,
    *,
    check: Check,
    verdict: Verdict,
    company: Company,
    project: Project | None,
    work_item: WorkItem | None,
    artifact: Artifact | None,
    run_id: str | None,
    task_id: str | None,
    duration_ms: int,
) -> CheckResult:
    result = CheckResult(
        created_at=datetime.now(UTC),
        company_id=company.id,
        check_id=check.id,
        check_key=check.key,
        check_kind=check.kind,
        project_id=project.id if project else None,
        work_item_id=work_item.id if work_item else None,
        artifact_id=artifact.id if artifact else None,
        run_id=run_id,
        task_id=task_id,
        status=verdict.status,
        score=verdict.score,
        detail=verdict.detail[:8000],
        evidence={**verdict.evidence, "required": check.required},
        duration_ms=duration_ms,
    )
    db.add(result)
    db.flush()

    ledger.append(
        db,
        company_id=company.id,
        project_id=project.id if project else None,
        kind="check.result",
        actor_label="Verification",
        subject_kind="check_result",
        subject_id=result.id,
        payload={
            "check_key": check.key,
            "check_kind": check.kind,
            "status": verdict.status,
            "score": verdict.score,
            "work_item_id": work_item.id if work_item else None,
            "artifact_id": artifact.id if artifact else None,
            "artifact_hash": artifact.content_hash if artifact else None,
            "detail": verdict.detail[:500],
        },
    )
    events.record(
        db,
        company_id=company.id,
        project_id=project.id if project else None,
        run_id=run_id,
        actor="Verification",
        kind="check.result",
        summary=f"{check.name} → {verdict.status}"
        + (f" ({work_item.key})" if work_item else ""),
        payload={
            "check_key": check.key,
            "status": verdict.status,
            "work_item_id": work_item.id if work_item else None,
            "detail": verdict.detail[:400],
        },
    )
    return result


def ensure_project_checks(db: Session, company: Company, project: Project) -> list[Check]:
    """Give a project the company's checks, plus its legacy verify command.

    `project.verify_command` was the entire verification vocabulary before this.
    It becomes an ordinary `command` check the first time checks are set up, so
    an existing project keeps behaving exactly as it did.
    """
    existing = {
        row.key: row
        for row in db.scalars(select(Check).where(Check.project_id == project.id))
    }
    created: list[Check] = []

    if project.verify_command and "verify_command" not in existing:
        check = Check(
            company_id=company.id,
            project_id=project.id,
            key="verify_command",
            name=f"`{project.verify_command}` passes",
            kind="command",
            spec={"command": project.verify_command},
            required=True,
            position=0,
            created_by="Platform",
        )
        db.add(check)
        created.append(check)

    if created:
        db.flush()
    return created
