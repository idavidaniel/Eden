"""Delivering messages between agents, and raising things that need a person."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AgentMessage, Approval, Company, Employee, WorkItem
from models.base import new_id
from models.collab import MAX_HOPS

from . import events, roles


def send(
    db: Session,
    *,
    company: Company,
    sender: Employee | None,
    recipient: Employee,
    kind: str,
    subject: str,
    body: str,
    work_item: WorkItem | None = None,
    thread_id: str | None = None,
    replies_to: str | None = None,
    hops: int = 0,
    payload: dict | None = None,
) -> AgentMessage:
    message = AgentMessage(
        company_id=company.id,
        kind=kind,
        from_id=sender.id if sender else None,
        from_label=f"{sender.name} ({sender.title})" if sender else "You",
        to_id=recipient.id,
        work_item_id=work_item.id if work_item else None,
        thread_id=thread_id or new_id(),
        replies_to=replies_to,
        hops=hops,
        subject=subject[:240],
        body=body,
        payload=payload or {},
    )
    db.add(message)
    db.flush()

    events.record(
        db,
        company_id=company.id,
        project_id=work_item.project_id if work_item else None,
        employee_id=sender.id if sender else None,
        actor=message.from_label,
        kind="agent.message",
        summary=f"{kind} → {recipient.name}: {subject}"[:400],
        payload={
            "message_id": message.id,
            "to": recipient.name,
            "kind": kind,
            "thread_id": message.thread_id,
        },
    )
    return message


def unread(db: Session, employee_id: str, limit: int = 10) -> list[AgentMessage]:
    return list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.to_id == employee_id, AgentMessage.handled_at.is_(None))
            .order_by(AgentMessage.created_at)
            .limit(limit)
        )
    )


def mark_read(db: Session, messages: list[AgentMessage]) -> None:
    now = datetime.now(UTC)
    for message in messages:
        message.read_at = message.read_at or now
        db.add(message)
    if messages:
        db.flush()


def mark_handled(db: Session, messages: list[AgentMessage]) -> None:
    now = datetime.now(UTC)
    for message in messages:
        message.handled_at = now
        message.read_at = message.read_at or now
        db.add(message)
    if messages:
        db.flush()


def current_thread(db: Session, employee_id: str, work_item_id: str | None) -> dict | None:
    """The thread this employee is currently answering, if any.

    Used to keep a reply in the same thread and to carry the hop count forward,
    which is what makes the ping-pong limit work at all.
    """
    query = (
        select(AgentMessage)
        .where(AgentMessage.to_id == employee_id)
        .order_by(AgentMessage.created_at.desc())
        .limit(1)
    )
    if work_item_id:
        query = query.where(AgentMessage.work_item_id == work_item_id)
    latest = db.scalar(query)
    if not latest:
        return None
    return {"thread_id": latest.thread_id, "hops": latest.hops, "message_id": latest.id}


def escalate(
    db: Session,
    *,
    company: Company,
    from_employee: Employee,
    work_item: WorkItem | None,
    thread_id: str,
    reason: str,
) -> str:
    """Send a stuck thread up: to the manager, and if there is none, to you."""
    manager = None
    if from_employee.manager_id:
        manager = db.get(Employee, from_employee.manager_id)
    if manager is None:
        team = list(db.scalars(select(Employee).where(Employee.company_id == company.id)))
        manager = roles.manager_of(db, team, company)

    if manager and manager.id != from_employee.id:
        send(
            db,
            company=company,
            sender=from_employee,
            recipient=manager,
            kind="escalate",
            subject=f"Stuck: {work_item.key if work_item else 'a request'}",
            body=reason,
            work_item=work_item,
            thread_id=thread_id,
            hops=MAX_HOPS,
        )
        return manager.name

    ask_human(
        db,
        company=company,
        employee=from_employee,
        work_item=work_item,
        question=reason,
        reason="This request has been passed around without being done and there is no manager.",
    )
    return "you"


def ask_human(
    db: Session,
    *,
    company: Company,
    employee: Employee | None,
    work_item: WorkItem | None,
    question: str,
    reason: str = "",
) -> Approval:
    approval = Approval(
        company_id=company.id,
        project_id=work_item.project_id if work_item else None,
        work_item_id=work_item.id if work_item else None,
        subject_kind="question",
        subject_id=work_item.id if work_item else None,
        requested_by=employee.id if employee else None,
        requested_label=f"{employee.name} ({employee.title})" if employee else "System",
        title=question[:240],
        reason=reason,
        payload={"work_item_key": work_item.key if work_item else None},
    )
    db.add(approval)

    if work_item:
        work_item.status = "blocked"
        work_item.blocked_reason = f"Waiting on you: {question[:400]}"
        db.add(work_item)

    events.record(
        db,
        company_id=company.id,
        project_id=work_item.project_id if work_item else None,
        employee_id=employee.id if employee else None,
        actor=approval.requested_label,
        kind="approval.requested",
        summary=f"needs you: {question[:200]}",
        payload={"approval_id": approval.id, "kind": "question"},
    )
    db.flush()
    return approval


def pending_approvals(db: Session, company_id: str) -> list[Approval]:
    return list(
        db.scalars(
            select(Approval)
            .where(Approval.company_id == company_id, Approval.status == "pending")
            .order_by(Approval.created_at)
        )
    )


def decide(
    db: Session, approval: Approval, *, approved: bool, by: str = "You", note: str = ""
) -> Approval:
    from . import ledger

    approval.status = "approved" if approved else "rejected"
    approval.decided_by = by[:160]
    approval.decided_at = datetime.now(UTC)
    approval.note = note
    db.add(approval)

    if approval.work_item_id:
        item = db.get(WorkItem, approval.work_item_id)
        if item and item.status == "blocked":
            item.status = "todo"
            item.blocked_reason = None
            db.add(item)

    ledger.append(
        db,
        company_id=approval.company_id,
        project_id=approval.project_id,
        kind="approval.decided",
        actor_label=by,
        subject_kind="approval",
        subject_id=approval.id,
        payload={
            "title": approval.title,
            "status": approval.status,
            "subject_kind": approval.subject_kind,
            "subject_id": approval.subject_id,
            "note": note[:500],
        },
    )
    events.record(
        db,
        company_id=approval.company_id,
        project_id=approval.project_id,
        actor=by,
        kind="approval.decided",
        summary=f"{approval.status} — {approval.title}"[:400],
        payload={"approval_id": approval.id, "status": approval.status},
    )
    db.flush()
    return approval
