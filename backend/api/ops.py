"""Running the company: what needs you, what it cost, and what can be proved.

These are the endpoints behind the "needs you" queue, the operations view and
the ledger. The ledger endpoints are the ones that matter most: they are how a
finished deliverable stops being a claim and becomes something you can re-prove.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db
from models import (
    AgentMessage,
    AgentTask,
    Approval,
    Artifact,
    CheckResult,
    Employee,
    Meeting,
    Project,
    Source,
    ToolCall,
    WorkItem,
)
from services import artifacts as artifact_service
from services import checks as check_service
from services import clock, inbox, ledger, meetings, performance, pricing, usage

from . import serializers
from .companies import get_company

router = APIRouter(tags=["ops"])


class DecisionIn(BaseModel):
    approved: bool
    note: str = ""


class HaltIn(BaseModel):
    halted: bool
    reason: str = ""


class MeetingIn(BaseModel):
    kind: str = "standup"
    project_id: str | None = None
    title: str = ""
    attendees: list[str] | None = None


# --------------------------------------------------------------------------
# what needs you
# --------------------------------------------------------------------------


@router.get("/companies/{company_id}/inbox")
def needs_you(company_id: str, db: Session = Depends(get_db)):
    """One queue: approvals, questions, and anything blocked waiting on a person."""
    company = get_company(db, company_id)
    approvals = inbox.pending_approvals(db, company.id)
    blocked = list(
        db.scalars(
            select(WorkItem)
            .join(Project, WorkItem.project_id == Project.id)
            .where(Project.company_id == company.id, WorkItem.status == "blocked")
            .order_by(WorkItem.updated_at.desc())
            .limit(50)
        )
    )
    return {
        "approvals": [serializers.approval(row) for row in approvals],
        "blocked_items": [serializers.work_item(row) for row in blocked],
        "count": len(approvals) + len(blocked),
    }


@router.post("/approvals/{approval_id}/decide")
def decide(approval_id: str, payload: DecisionIn, db: Session = Depends(get_db)):
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="No such approval.")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {approval.status}.")
    inbox.decide(db, approval, approved=payload.approved, by="You", note=payload.note)
    db.commit()
    return serializers.approval(approval)


@router.get("/companies/{company_id}/messages")
def message_log(
    company_id: str, limit: int = Query(60, le=200), db: Session = Depends(get_db)
):
    """What the agents have been saying to each other."""
    get_company(db, company_id)
    rows = list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.company_id == company_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
        )
    )
    return [serializers.agent_message(row) for row in reversed(rows)]


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------


@router.get("/companies/{company_id}/ops")
def operations(company_id: str, db: Session = Depends(get_db)):
    """Live state: tasks in flight, recent checks, spend, and the clock."""
    company = get_company(db, company_id)
    tasks = list(
        db.scalars(
            select(AgentTask)
            .where(AgentTask.company_id == company.id)
            .order_by(AgentTask.created_at.desc())
            .limit(40)
        )
    )
    recent_checks = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.company_id == company.id)
            .order_by(CheckResult.created_at.desc())
            .limit(30)
        )
    )
    totals = usage.for_company(db, company.id)
    return {
        "clock": clock.status(),
        "autonomous": bool((company.settings or {}).get("autonomous")),
        "halted": company.halted,
        "halt_reason": company.halt_reason,
        "tasks": [serializers.agent_task(row) for row in tasks],
        "in_flight": len([t for t in tasks if t.status in {"queued", "leased", "running"}]),
        "checks": [serializers.check_result(row) for row in recent_checks],
        "usage": {
            window: {**values, "display": pricing.format_cost(values["cost_micros"])}
            for window, values in totals.items()
        },
        "by_employee": [
            {**row, "display": pricing.format_cost(row["cost_micros"])}
            for row in usage.by_employee(db, company.id, datetime.now(UTC) - timedelta(days=30))
        ],
        "cost_note": "Cost is estimated from a configurable rate table; tokens are measured.",
    }


@router.post("/companies/{company_id}/halt")
def halt(company_id: str, payload: HaltIn, db: Session = Depends(get_db)):
    """The kill switch. Nothing in this company acts while it is on."""
    from services import events

    company = get_company(db, company_id)
    company.halted = payload.halted
    company.halt_reason = payload.reason[:240] or None
    db.add(company)
    events.record(
        db,
        company_id=company.id,
        actor="You",
        kind="company.halted" if payload.halted else "company.resumed",
        summary=("halted " if payload.halted else "resumed ") + company.name,
        payload={"reason": payload.reason},
    )
    db.commit()
    return serializers.company(company)


@router.post("/companies/{company_id}/autonomy")
def set_autonomy(company_id: str, enabled: bool, db: Session = Depends(get_db)):
    """Let the org clock start work here on its own. Off by default: it spends money."""
    company = get_company(db, company_id)
    settings = dict(company.settings or {})
    settings["autonomous"] = bool(enabled)
    company.settings = settings
    db.add(company)
    db.commit()
    if enabled:
        clock.start()
    return {"company_id": company.id, "autonomous": bool(enabled), "clock": clock.status()}


@router.post("/clock/tick")
def tick_now():
    """Run one clock pass immediately, for when you do not want to wait."""
    return clock.tick()


@router.get("/companies/{company_id}/tool-calls")
def tool_calls(
    company_id: str,
    employee_id: str | None = None,
    limit: int = Query(60, le=200),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    query = (
        select(ToolCall)
        .where(ToolCall.company_id == company_id)
        .order_by(ToolCall.created_at.desc())
        .limit(limit)
    )
    if employee_id:
        query = query.where(ToolCall.employee_id == employee_id)
    return [serializers.tool_call(row) for row in db.scalars(query)]


@router.get("/companies/{company_id}/sources")
def sources(company_id: str, limit: int = Query(60, le=200), db: Session = Depends(get_db)):
    get_company(db, company_id)
    rows = db.scalars(
        select(Source)
        .where(Source.company_id == company_id)
        .order_by(Source.created_at.desc())
        .limit(limit)
    )
    return [serializers.source(row) for row in rows]


@router.get("/companies/{company_id}/performance")
def company_performance(company_id: str, db: Session = Depends(get_db)):
    """Per-employee numbers from check results, not from self-assessment."""
    company = get_company(db, company_id)
    return performance.for_company(db, company)


@router.get("/employees/{employee_id}/performance")
def employee_performance(employee_id: str, db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return performance.for_employee(db, employee)


@router.post("/employees/{employee_id}/coach")
def coach(employee_id: str, db: Session = Depends(get_db)):
    """Propose a change to how this employee works, based on their record."""
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    proposal = performance.propose_coaching(db, employee)
    db.commit()
    return proposal


# --------------------------------------------------------------------------
# meetings
# --------------------------------------------------------------------------


@router.get("/companies/{company_id}/meetings")
def list_meetings(company_id: str, limit: int = Query(30, le=100), db: Session = Depends(get_db)):
    get_company(db, company_id)
    rows = db.scalars(
        select(Meeting)
        .where(Meeting.company_id == company_id)
        .order_by(Meeting.created_at.desc())
        .limit(limit)
    )
    return [serializers.meeting(row) for row in rows]


@router.post("/companies/{company_id}/meetings", status_code=202)
def hold_meeting(company_id: str, payload: MeetingIn, db: Session = Depends(get_db)):
    """Hold a meeting. It has to produce decisions and action items or it did not happen."""
    company = get_company(db, company_id)
    if payload.kind not in meetings.KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind must be one of: {', '.join(meetings.KINDS)}"
        )
    project = db.get(Project, payload.project_id) if payload.project_id else None
    meeting = meetings.schedule(
        db,
        company=company,
        kind=payload.kind,
        project=project,
        title=payload.title,
        attendee_ids=payload.attendees,
    )
    db.commit()
    meetings.start(meeting.id)
    return serializers.meeting(meeting)


@router.get("/meetings/{meeting_id}")
def read_meeting(meeting_id: str, db: Session = Depends(get_db)):
    row = db.get(Meeting, meeting_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such meeting.")
    return serializers.meeting(row)


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------


@router.get("/companies/{company_id}/ledger")
def read_ledger(
    company_id: str,
    project_id: str | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    entries = ledger.chain(db, company_id, project_id)[-limit:]
    return {
        "entries": [serializers.ledger_entry(row) for row in entries],
        "height": entries[-1].height if entries else -1,
        "tip": entries[-1].hash if entries else None,
    }


@router.post("/companies/{company_id}/ledger/verify")
def verify_ledger(company_id: str, db: Session = Depends(get_db)):
    """Recompute the whole chain and say where, if anywhere, it breaks."""
    get_company(db, company_id)
    return ledger.verify_chain(db, company_id)


@router.post("/projects/{project_id}/ledger/verify")
def reverify_project(
    project_id: str, rerun_checks: bool = True, db: Session = Depends(get_db)
):
    """Re-prove a project from its record.

    Recomputes the hash chain, compares every artifact against the hash the
    ledger committed to, and — unless you ask it not to — runs the deterministic
    checks again. "Was this really tested?" becomes a command rather than a
    conversation.
    """
    from services import proof

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    result = proof.reverify(db, project, rerun_checks=rerun_checks)
    db.commit()
    return result


@router.get("/projects/{project_id}/work-record")
def work_record(project_id: str, db: Session = Depends(get_db)):
    """The exportable record: what was asked, what was made, what proved it."""
    from services import proof

    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return proof.work_record(db, project)


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------


@router.get("/projects/{project_id}/artifacts")
def list_artifacts(
    project_id: str, all_versions: bool = False, db: Session = Depends(get_db)
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    rows = artifact_service.for_project(db, project_id, current_only=not all_versions)
    return [serializers.artifact(row) for row in rows]


@router.get("/artifacts/{artifact_id}")
def read_artifact(artifact_id: str, db: Session = Depends(get_db)):
    row = db.get(Artifact, artifact_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such artifact.")
    versions = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.project_id == row.project_id, Artifact.name == row.name)
            .order_by(Artifact.version.desc())
        )
    )
    results = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.artifact_id == row.id)
            .order_by(CheckResult.created_at.desc())
        )
    )
    return {
        **serializers.artifact(row, content=artifact_service.read(db, row)),
        "integrity": artifact_service.verify_content_hash(db, row),
        "versions": [serializers.artifact(version) for version in versions],
        "checks": [serializers.check_result(result) for result in results],
    }


@router.get("/companies/{company_id}/artifacts")
def company_artifacts(
    company_id: str, kind: str | None = None, db: Session = Depends(get_db)
):
    get_company(db, company_id)
    query = (
        select(Artifact)
        .where(Artifact.company_id == company_id, Artifact.superseded_by.is_(None))
        .order_by(Artifact.updated_at.desc())
    )
    if kind:
        query = query.where(Artifact.kind == kind)
    rows = list(db.scalars(query.limit(300)))
    counts = db.execute(
        select(Artifact.kind, func.count())
        .where(Artifact.company_id == company_id, Artifact.superseded_by.is_(None))
        .group_by(Artifact.kind)
    ).all()
    return {
        "artifacts": [serializers.artifact(row) for row in rows],
        "by_kind": {kind_name: count for kind_name, count in counts},
    }


@router.post("/work-items/{work_item_id}/checks/run")
def run_checks(work_item_id: str, db: Session = Depends(get_db)):
    """Run this item's checks now. The same code path the platform uses itself."""
    item = db.get(WorkItem, work_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found.")
    project = db.get(Project, item.project_id)
    company = project.company
    check_service.ensure_project_checks(db, company, project)
    author = db.get(Employee, item.assignee_id) if item.assignee_id else None
    results = check_service.run_for_work_item(
        db, company=company, project=project, work_item=item, author=author
    )
    db.commit()
    return {
        "results": [serializers.check_result(row) for row in results],
        "verdict": check_service.verdict_for(results) if results else None,
    }


@router.get("/work-items/{work_item_id}/checks")
def work_item_checks(work_item_id: str, db: Session = Depends(get_db)):
    """What will be checked, and what the last run said — without running it.

    Separate from the POST because looking at the standard a piece of work is
    held to should not cost anything or change anything.
    """
    item = db.get(WorkItem, work_item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work item not found.")
    project = db.get(Project, item.project_id)
    company = project.company

    produced = list(
        db.scalars(
            select(Artifact).where(
                Artifact.work_item_id == item.id, Artifact.superseded_by.is_(None)
            )
        )
    )
    applicable = check_service.applicable(db, company, project=project, work_item=item)
    for artifact in produced:
        for check in check_service.applicable(
            db, company, project=project, work_item=item, artifact=artifact
        ):
            if all(existing.id != check.id for existing in applicable):
                applicable.append(check)

    results = check_service.latest_for_work_item(db, item.id)
    return {
        "checks": [serializers.check(row) for row in applicable],
        "results": [serializers.check_result(row) for row in results],
        "verdict": check_service.verdict_for(results) if results else None,
        "artifacts": [serializers.artifact(row) for row in produced],
    }
