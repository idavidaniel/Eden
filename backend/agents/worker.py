"""Executing one task addressed to one agent.

Everything that makes an employee act ends up here: an HTTP request to their
API, a colleague's message, the org clock picking up ready work, a meeting
action item. The turn loop is the same in every case, which is the point — an
employee behaves identically whether a human curled them or a manager assigned
them something.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from agents import engine, prompts, runtime
from agents.tools.base import ToolContext
from db import session
from models import AgentTask, Company, Employee, Project, WorkItem
from services import events, inbox

log = logging.getLogger(__name__)

TASK_KINDS = ["message", "work_item", "inbox", "meeting", "review"]


def enqueue(
    db: Session,
    *,
    company: Company,
    employee: Employee,
    kind: str,
    request: dict,
    source: str = "api",
    created_by: str = "You",
    work_item_id: str | None = None,
    run_id: str | None = None,
    priority: int = 100,
) -> AgentTask:
    task = AgentTask(
        company_id=company.id,
        employee_id=employee.id,
        source=source,
        kind=kind,
        request=request,
        status="queued",
        created_by=created_by[:120],
        work_item_id=work_item_id,
        run_id=run_id,
        priority=priority,
    )
    db.add(task)
    db.flush()
    events.record(
        db,
        company_id=company.id,
        employee_id=employee.id,
        actor=created_by,
        kind="task.queued",
        summary=f"queued {kind} for {employee.name}",
        payload={"task_id": task.id, "kind": kind, "source": source},
    )
    return task


def start(task_id: str) -> None:
    engine.get_executor().submit(execute_task, task_id)


def execute_task(task_id: str) -> dict:
    """Run one task to completion. Never raises; failures land on the row."""
    db = session()
    try:
        task = db.get(AgentTask, task_id)
        if not task:
            return {"status": "missing"}
        if task.status in {"done", "failed", "cancelled"}:
            return {"status": task.status}

        employee = db.get(Employee, task.employee_id)
        company = db.get(Company, task.company_id)
        if not employee or not company:
            return _fail(db, task, "The employee or company no longer exists.")

        task.status = "running"
        task.started_at = datetime.now(UTC)
        task.attempts += 1
        employee.heartbeat_at = datetime.now(UTC)
        db.add(task)
        db.add(employee)
        db.commit()

        try:
            result = _dispatch(db, task, company, employee)
        except Exception as exc:
            log.exception("task %s failed", task_id)
            db.rollback()
            return _fail(db, task, str(exc)[:2000])

        db.refresh(task)
        task.status = "done"
        task.result = result
        task.finished_at = datetime.now(UTC)
        task.lease_until = None
        db.add(task)
        employee.heartbeat_at = None
        db.add(employee)
        db.commit()
        return result
    finally:
        runtime.clear_cancel(task_id)
        db.close()


def _fail(db: Session, task: AgentTask, message: str) -> dict:
    db.refresh(task)
    task.status = "failed"
    task.error = message
    task.finished_at = datetime.now(UTC)
    task.lease_until = None
    db.add(task)
    db.commit()
    return {"status": "failed", "error": message}


def _dispatch(db: Session, task: AgentTask, company: Company, employee: Employee) -> dict:
    request = task.request or {}
    project = _project_for(db, task, company, request)
    work_item = db.get(WorkItem, task.work_item_id) if task.work_item_id else None

    if task.kind == "work_item" and work_item and project:
        engine.work_item_turn(db, None, project, work_item, company)
        db.refresh(work_item)
        return {
            "kind": "work_item",
            "work_item": work_item.key,
            "status": work_item.status,
            "result": work_item.result,
        }

    if task.kind == "review" and work_item and project:
        engine.review_work_item(db, None, project, work_item, company, employee)
        db.refresh(work_item)
        return {"kind": "review", "work_item": work_item.key, "status": work_item.status}

    if task.kind == "inbox":
        return _handle_inbox(db, company, employee, project)

    prompt = request.get("message") or request.get("prompt") or ""
    if not prompt:
        return {"kind": task.kind, "text": "", "note": "Nothing was asked."}

    ctx = ToolContext(
        db=db,
        company=company,
        employee=employee,
        project=project,
        work_item=work_item,
        task_id=task.id,
    )
    outcome = runtime.run_turn(
        db,
        ctx,
        prompt,
        kind=task.kind,
        purpose=request.get("purpose") or "chat",
        max_steps=request.get("max_steps"),
    )
    return {
        "kind": task.kind,
        "text": outcome.text,
        "status": outcome.status,
        "tool_calls": outcome.tool_calls,
        "context": outcome.context_report,
        "step_id": outcome.step.id,
    }


def _handle_inbox(
    db: Session, company: Company, employee: Employee, project: Project | None
) -> dict:
    """Answer whatever colleagues have sent, in one turn."""
    messages = inbox.unread(db, employee.id, limit=6)
    if not messages:
        return {"kind": "inbox", "handled": 0}

    rendered = "\n\n".join(
        f"[{message.kind}] from {message.from_label} — {message.subject}\n{message.body}"
        for message in messages
    )
    work_item = None
    for message in messages:
        if message.work_item_id:
            work_item = db.get(WorkItem, message.work_item_id)
            if work_item:
                project = project or db.get(Project, work_item.project_id)
                break

    ctx = ToolContext(
        db=db, company=company, employee=employee, project=project, work_item=work_item
    )
    outcome = runtime.run_turn(
        db,
        ctx,
        f"""Your colleagues have sent you these:

{rendered}

Deal with them. If something is a request you can do, do it now. If it belongs to
somebody else, hand it over with the reason. If it needs a decision only the
human can make, use ask_human. Do not simply acknowledge them.""",
        kind="inbox",
        purpose="work",
    )
    inbox.mark_handled(db, messages)
    db.commit()
    return {
        "kind": "inbox",
        "handled": len(messages),
        "text": outcome.text,
        "status": outcome.status,
    }


def _project_for(
    db: Session, task: AgentTask, company: Company, request: dict
) -> Project | None:
    if request.get("project_id"):
        return db.get(Project, request["project_id"])
    if task.work_item_id:
        item = db.get(WorkItem, task.work_item_id)
        if item:
            return db.get(Project, item.project_id)
    return None


def ask_now(
    db: Session,
    *,
    company: Company,
    employee: Employee,
    message: str,
    project: Project | None = None,
    work_item: WorkItem | None = None,
    max_steps: int | None = None,
    created_by: str = "API",
) -> dict:
    """One synchronous turn, for callers that want the answer in the response."""
    task = enqueue(
        db,
        company=company,
        employee=employee,
        kind="message",
        request={
            "message": message,
            "project_id": project.id if project else None,
            "max_steps": max_steps,
        },
        source="api",
        created_by=created_by,
        work_item_id=work_item.id if work_item else None,
    )
    task.status = "running"
    task.started_at = datetime.now(UTC)
    db.add(task)
    db.commit()

    ctx = ToolContext(
        db=db,
        company=company,
        employee=employee,
        project=project,
        work_item=work_item,
        task_id=task.id,
    )
    outcome = runtime.run_turn(
        db, ctx, message, kind="message", purpose="chat", max_steps=max_steps
    )

    task.status = "done" if outcome.status in {"done", "step_limit"} else outcome.status
    task.result = {
        "text": outcome.text,
        "status": outcome.status,
        "tool_calls": outcome.tool_calls,
    }
    task.finished_at = datetime.now(UTC)
    db.add(task)
    db.commit()
    return {
        "task_id": task.id,
        "reply": outcome.text,
        "status": outcome.status,
        "tool_calls": outcome.tool_calls,
        "context": outcome.context_report,
        "step_id": outcome.step.id,
    }


def system_prompt_for(db: Session, employee: Employee, project: Project | None = None) -> str:
    """Exposed so the agent card can show exactly who this agent thinks it is."""
    from sqlalchemy import select

    colleagues = list(
        db.scalars(select(Employee).where(Employee.company_id == employee.company_id))
    )
    return prompts.employee_system_prompt(employee.company, employee, colleagues, project)
