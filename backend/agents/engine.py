"""The company runtime: plan a brief, work the tickets, review, wrap up.

A run is executed by one background worker thread. Every step writes to the
database as it happens, so the dashboard's live feed is simply a tail of the
activity table, and a crash mid-run leaves the tickets it already finished.
"""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents import prompts, tools
from agents.llm import chat, structured_call
from agents.tools.base import ToolContext
from config import get_settings
from db import session
from models import (
    Channel,
    Document,
    Employee,
    Message,
    Project,
    Run,
    RunStep,
    Ticket,
    TicketComment,
)
from services import events, workspace
from services.roles import ROLES, get_role, match_role

log = logging.getLogger(__name__)

# How many steps before the limit an employee is told to wrap up.
WARN_BEFORE_STEPS = 3

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=get_settings().run_concurrency, thread_name_prefix="run"
            )
        return _executor


# --------------------------------------------------------------------------
# context helpers
# --------------------------------------------------------------------------


def _chat_log(db: Session, company_id: str, limit: int = 12) -> str:
    rows = list(
        db.scalars(
            select(Message)
            .join(Channel, Message.channel_id == Channel.id)
            .where(Channel.company_id == company_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    )
    return "\n".join(f"{m.author_label}: {m.body}" for m in reversed(rows))


def _wiki_index(db: Session, company_id: str) -> str:
    rows = list(db.scalars(select(Document).where(Document.company_id == company_id)))
    return "\n".join(f"- {d.title} (slug: {d.slug})" for d in rows)


def _file_list(company_slug: str, project: Project) -> str:
    space = workspace.for_project(company_slug, project.key)
    space.init(project.name)
    return "\n".join(f"- {entry['path']}" for entry in space.tree()[:60])


def _pick(team: list[Employee], role_key: str) -> Employee | None:
    """Find someone for a role, falling back to anyone who can plausibly do it."""
    exact = [e for e in team if e.role_key == role_key]
    if exact:
        return exact[0]
    role = get_role(role_key)
    same_department = [
        e for e in team if e.department == role.department and not get_role(e.role_key).manages
    ]
    if same_department:
        return same_department[0]
    doers = [e for e in team if not get_role(e.role_key).manages]
    return doers[0] if doers else (team[0] if team else None)


def _set_status(db: Session, employee: Employee, status: str, note: str = "") -> None:
    employee.status = status
    employee.status_note = note[:240] or None
    db.add(employee)
    db.commit()


# --------------------------------------------------------------------------
# one employee's turn
# --------------------------------------------------------------------------


def run_agent_turn(
    db: Session,
    ctx: ToolContext,
    task_prompt: str,
    kind: str = "work",
    max_steps: int | None = None,
) -> RunStep:
    """Let an employee work with their tools until they stop calling them."""
    settings = get_settings()
    max_steps = max_steps or settings.max_agent_steps
    colleagues = list(db.scalars(select(Employee).where(Employee.company_id == ctx.company.id)))

    messages = [
        {
            "role": "system",
            "content": prompts.employee_system_prompt(
                ctx.company, ctx.employee, colleagues, ctx.project
            ),
        },
        {"role": "user", "content": task_prompt},
    ]
    available = tools.for_employee(ctx.employee)
    schemas = tools.schemas(available)

    step = RunStep(
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        ticket_id=ctx.ticket.id if ctx.ticket else None,
        kind=kind,
        status="running",
    )
    if ctx.run:
        db.add(step)
        db.commit()

    reasoning_parts: list[str] = []
    calls_made: list[dict] = []
    final_text = ""
    hit_limit = False

    for index in range(max_steps):
        # Warn before the budget runs out so the turn lands instead of being cut
        # off mid-thought.
        if index == max_steps - WARN_BEFORE_STEPS:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"You have {WARN_BEFORE_STEPS} tool calls left. Finish now: save "
                        "your work, commit it if you changed files, update the ticket, "
                        "then reply with what you did."
                    ),
                }
            )

        reply = chat(messages, tools=schemas)
        if reply.reasoning:
            reasoning_parts.append(reply.reasoning)

        if not reply.tool_calls:
            final_text = reply.content
            break

        messages.append(
            {
                "role": "assistant",
                "content": reply.content or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {"name": call["name"], "arguments": _dumps(call["arguments"])},
                    }
                    for call in reply.tool_calls
                ],
            }
        )

        for call in reply.tool_calls:
            result = tools.execute(call["name"], ctx, call["arguments"])
            db.commit()
            calls_made.append(
                {"name": call["name"], "arguments": call["arguments"], "result": result[:800]}
            )
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": result[:4000]})
            log.info("%s -> %s", call["name"], result[:120])
    else:
        hit_limit = True
        final_text = (
            f"Ran out of tool calls ({max_steps}) before finishing this task. "
            "Raise MAX_AGENT_STEPS or split the ticket into smaller pieces."
        )

    step.reasoning = "\n\n".join(reasoning_parts)[:20000]
    step.output = final_text[:8000]
    step.tool_calls = calls_made
    step.status = "step_limit" if hit_limit else "done"
    if ctx.run:
        db.add(step)
        db.commit()
    return step


def _dumps(value) -> str:
    import json

    return json.dumps(value)


# --------------------------------------------------------------------------
# run phases
# --------------------------------------------------------------------------


def plan_run(db: Session, run: Run, project: Project, team: list[Employee]) -> list[Ticket]:
    """The manager turns the brief into assigned tickets."""
    manager = next((e for e in team if get_role(e.role_key).manages), None) or team[0]
    _set_status(db, manager, "working", f"planning {project.key}")

    events.record(
        db,
        company_id=run.company_id,
        project_id=project.id,
        run_id=run.id,
        employee_id=manager.id,
        actor=f"{manager.name} ({manager.title})",
        kind="run.planning",
        summary=f"is breaking down the brief for {project.name}",
    )
    db.commit()

    role_keys = sorted({e.role_key for e in team})
    messages = [
        {
            "role": "system",
            "content": prompts.employee_system_prompt(project.company, manager, team, project),
        },
        {"role": "user", "content": prompts.planner_prompt(project, role_keys, team)},
    ]
    plan = structured_call(
        messages,
        name="submit_plan",
        description="Submit the ticket breakdown for this project.",
        parameters=prompts.plan_schema(role_keys),
    )

    created: list[Ticket] = []
    limit = get_settings().max_tickets_per_run
    for index, item in enumerate(plan.get("tickets", [])[:limit]):
        role_key = item.get("role") or match_role(
            f"{item.get('title', '')} {item.get('description', '')}"
        )
        if role_key not in ROLES:
            role_key = match_role(item.get("title", ""))
        assignee = _pick(team, role_key)
        project.ticket_counter += 1
        ticket = Ticket(
            project_id=project.id,
            key=f"{project.key}-{project.ticket_counter}",
            title=str(item.get("title", "Untitled"))[:240],
            description=str(item.get("description", "")),
            type=item.get("type", "task"),
            status="todo",
            priority=item.get("priority", "medium"),
            assignee_id=assignee.id if assignee else None,
            reporter_id=manager.id,
            role_hint=role_key,
            acceptance_criteria=[str(c) for c in item.get("acceptance_criteria", [])][:8],
            order=index,
        )
        db.add(ticket)
        db.flush()
        created.append(ticket)
        events.record(
            db,
            company_id=run.company_id,
            project_id=project.id,
            run_id=run.id,
            employee_id=manager.id,
            actor=f"{manager.name} ({manager.title})",
            kind="ticket.created",
            summary=(
                f"created {ticket.key}: {ticket.title}"
                f" → {assignee.name if assignee else 'unassigned'}"
            ),
            payload={"ticket_id": ticket.id, "key": ticket.key},
        )

    project.status = "in_progress"
    db.add(project)
    _set_status(db, manager, "idle")
    db.commit()
    return created


def work_ticket(db: Session, run: Run, project: Project, ticket: Ticket, company) -> None:
    employee = db.get(Employee, ticket.assignee_id) if ticket.assignee_id else None
    if not employee:
        ticket.status = "blocked"
        db.add(ticket)
        db.commit()
        return

    _set_status(db, employee, "working", f"{ticket.key}: {ticket.title}")
    ticket.status = "in_progress"
    db.add(ticket)
    events.record(
        db,
        company_id=run.company_id,
        project_id=project.id,
        run_id=run.id,
        employee_id=employee.id,
        actor=f"{employee.name} ({employee.title})",
        kind="ticket.started",
        summary=f"started {ticket.key}: {ticket.title}",
        payload={"ticket_id": ticket.id, "key": ticket.key},
    )
    db.commit()

    ctx = ToolContext(
        db=db, company=company, employee=employee, project=project, ticket=ticket, run=run
    )
    task_prompt = prompts.ticket_prompt(
        ticket,
        project,
        _chat_log(db, company.id),
        _wiki_index(db, company.id),
        _file_list(company.slug, project),
    )
    step = run_agent_turn(db, ctx, task_prompt, kind="work")

    if step.status == "step_limit":
        db.add(
            TicketComment(
                ticket_id=ticket.id,
                author_id=employee.id,
                author_label=f"{employee.name} ({employee.title})",
                body=step.output,
            )
        )
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            run_id=run.id,
            employee_id=employee.id,
            actor=f"{employee.name} ({employee.title})",
            kind="ticket.step_limit",
            summary=f"ran out of tool calls on {ticket.key}",
            payload={"ticket_id": ticket.id, "key": ticket.key},
        )
        db.commit()

    _autocommit(db, run, project, ticket, employee, company)

    db.refresh(ticket)
    if ticket.status == "in_progress":
        ticket.status = "in_review"
    if not ticket.result:
        ticket.result = step.output[:2000]
    db.add(ticket)
    _set_status(db, employee, "idle")
    db.commit()


def _autocommit(db: Session, run: Run, project: Project, ticket: Ticket, employee, company) -> None:
    """Commit whatever the employee left behind.

    They are told to commit, and often do not. Uncommitted work is invisible in
    the history, so the platform commits it for them rather than losing the trail.
    """
    if "workspace" not in (employee.toolbelt or []):
        return
    try:
        space = workspace.for_project(company.slug, project.key)
        handle = employee.name.lower().replace(" ", ".")
        result = space.commit(
            f"{ticket.key}: {ticket.title}", (employee.name, f"{handle}@{company.slug}.eden")
        )
    except Exception as exc:
        log.warning("auto-commit failed for %s: %s", ticket.key, exc)
        return

    if result.get("committed"):
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            run_id=run.id,
            employee_id=employee.id,
            actor=f"{employee.name} ({employee.title})",
            kind="code.commit",
            summary=f"committed {result['sha']}: {ticket.key} {ticket.title}"[:400],
            payload=result,
        )
        db.commit()


def review_ticket(
    db: Session, run: Run, project: Project, ticket: Ticket, company, reviewer: Employee
) -> None:
    _set_status(db, reviewer, "working", f"reviewing {ticket.key}")
    ctx = ToolContext(
        db=db, company=company, employee=reviewer, project=project, ticket=ticket, run=run
    )
    ticket_block = (
        f"{ticket.key}: {ticket.title}\nDescription: {ticket.description}\n"
        f"Acceptance criteria:\n"
        + ("\n".join(f"- {c}" for c in ticket.acceptance_criteria or []) or "- (none stated)")
    )
    prompt = prompts.REVIEW_PROMPT.format(
        ticket_block=ticket_block,
        result=ticket.result or "(nothing recorded)",
        file_list=_file_list(company.slug, project),
    )
    run_agent_turn(db, ctx, prompt, kind="review")
    # Reviewers write too - a failing test they added is part of the record.
    _autocommit(db, run, project, ticket, reviewer, company)

    db.refresh(ticket)
    if ticket.status == "in_review":  # reviewer did not decide - accept it
        ticket.status = "done"
        db.add(ticket)
    _set_status(db, reviewer, "idle")
    db.commit()


def wrap_up(db: Session, run: Run, project: Project, team: list[Employee], company) -> None:
    """Manager posts the outcome; the writer documents it if there is one."""
    manager = next((e for e in team if get_role(e.role_key).manages), None) or team[0]
    tickets = list(db.scalars(select(Ticket).where(Ticket.project_id == project.id)))
    done = [t for t in tickets if t.status == "done"]
    summary_lines = "\n".join(f"- {t.key} [{t.status}] {t.title}" for t in tickets)

    ctx = ToolContext(db=db, company=company, employee=manager, project=project, run=run)
    run_agent_turn(
        db,
        ctx,
        f"""The team has finished working on {project.name}.

Ticket outcomes:
{summary_lines}

Post one short wrap-up message to #general covering what shipped and anything
still open. Then stop.""",
        kind="wrap_up",
        max_steps=4,
    )

    project.status = "delivered" if len(done) == len(tickets) and tickets else "in_progress"
    db.add(project)
    db.commit()


# --------------------------------------------------------------------------
# run orchestration
# --------------------------------------------------------------------------


# `in_progress` counts as pending: a run that was interrupted leaves tickets
# mid-flight, and the next run has to pick them back up.
PENDING_STATUSES = ["todo", "backlog", "in_progress"]


def _pending_tickets(db: Session, project_id: str) -> list[Ticket]:
    """Tickets still waiting for someone, in board order."""
    return list(
        db.scalars(
            select(Ticket)
            .where(Ticket.project_id == project_id, Ticket.status.in_(PENDING_STATUSES))
            .order_by(Ticket.order, Ticket.key)
        )
    )


def _count_done(db: Session, project_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Ticket)
            .where(Ticket.project_id == project_id, Ticket.status == "done")
        )
        or 0
    )


def _outcome_note(done: int, unfinished: list, blocked: list, truncated: int) -> str:
    """One sentence the dashboard can show about how the run ended."""
    parts = [f"{done} ticket{'s' if done != 1 else ''} finished"]
    if unfinished:
        keys = ", ".join(t.key for t in unfinished[:4])
        parts.append(f"{len(unfinished)} still open ({keys}) - run again to continue them")
    if blocked:
        parts.append(f"{len(blocked)} blocked, needs you")
    if truncated:
        parts.append(
            f"{truncated} turn{'s' if truncated != 1 else ''} ran out of tool calls "
            "(raise MAX_AGENT_STEPS or use smaller tickets)"
        )
    return "; ".join(parts) + "."


def _cancelled(db: Session, run_id: str) -> bool:
    status = db.scalar(select(Run.status).where(Run.id == run_id))
    return status in {"cancelling", "cancelled"}


def _await_resume(db: Session, run_id: str) -> bool:
    """Block while a run is paused. Returns False if it was cancelled instead."""
    import time

    while True:
        db.expire_all()
        status = db.scalar(select(Run.status).where(Run.id == run_id))
        if status in {"cancelling", "cancelled"}:
            return False
        if status != "paused":
            return True
        time.sleep(1.5)


def execute_run(run_id: str) -> None:
    """Entry point for the background worker."""
    db = session()
    try:
        run = db.get(Run, run_id)
        if not run:
            return
        project = db.get(Project, run.project_id)
        company = project.company
        team = list(db.scalars(select(Employee).where(Employee.company_id == run.company_id)))
        if not team:
            run.status, run.error = "failed", "This company has no employees yet."
            db.add(run)
            db.commit()
            return

        run.status, run.phase = "running", "planning"
        db.add(run)
        events.record(
            db,
            company_id=run.company_id,
            project_id=project.id,
            run_id=run.id,
            kind="run.started",
            summary=f"Run started for {project.name}",
        )
        db.commit()

        if not _pending_tickets(db, project.id):
            plan_run(db, run, project, team)

        run.phase = "execution"
        db.add(run)
        db.commit()

        reviewer = next((e for e in team if e.role_key == "qa_engineer"), None)
        stopped = False

        # Several passes: work rejected by QA comes back as `todo`, and the
        # person who owns it deserves the review comments before the run ends.
        # A pass that finishes nothing ends the run - another identical pass
        # would only burn tokens.
        for cycle in range(get_settings().max_run_passes):
            pending = _pending_tickets(db, project.id)
            if not pending or stopped:
                break
            if cycle:
                done_before = _count_done(db, project.id)
                log.info("rework pass %s: %s tickets", cycle, len(pending))

            for ticket in pending:
                if not _await_resume(db, run_id) or _cancelled(db, run_id):
                    stopped = True
                    break
                db.refresh(ticket)
                if ticket.status in {"done", "in_review"}:
                    continue
                work_ticket(db, run, project, ticket, company)

                if reviewer and reviewer.id != ticket.assignee_id:
                    db.refresh(ticket)
                    if ticket.status == "in_review":
                        if not _await_resume(db, run_id) or _cancelled(db, run_id):
                            stopped = True
                            break
                        review_ticket(db, run, project, ticket, company, reviewer)

            if cycle and _count_done(db, project.id) == done_before:
                log.info("pass %s finished nothing new - ending the run", cycle)
                break

        if _cancelled(db, run_id):
            run.status, run.phase = "cancelled", "cancelled"
        else:
            run.phase = "wrap_up"
            db.add(run)
            db.commit()
            wrap_up(db, run, project, team, company)
            run.status, run.phase = "completed", "done"

        finished = list(db.scalars(select(Ticket).where(Ticket.project_id == project.id)))
        done = [t for t in finished if t.status == "done"]
        unfinished = [t for t in finished if t.status in PENDING_STATUSES]
        blocked = [t for t in finished if t.status == "blocked"]
        truncated = db.scalar(
            select(func.count())
            .select_from(RunStep)
            .where(RunStep.run_id == run.id, RunStep.status == "step_limit")
        )
        run.stats = {
            "tickets": len(finished),
            "done": len(done),
            "blocked": len(blocked),
            "unfinished": len(unfinished),
            "step_limited": truncated or 0,
            "note": _outcome_note(len(done), unfinished, blocked, truncated or 0),
        }
        db.add(run)
        events.record(
            db,
            company_id=run.company_id,
            project_id=project.id,
            run_id=run.id,
            kind=f"run.{run.status}",
            summary=f"Run {run.status}: {run.stats['done']}/{run.stats['tickets']} tickets done",
            payload=run.stats,
        )
        db.commit()
    except Exception as exc:  # keep the failure visible in the UI
        log.exception("run %s failed", run_id)
        db.rollback()
        run = db.get(Run, run_id)
        if run:
            run.status, run.error = "failed", str(exc)[:2000]
            db.add(run)
            events.record(
                db,
                company_id=run.company_id,
                project_id=run.project_id,
                run_id=run.id,
                kind="run.failed",
                summary=f"Run failed: {exc}"[:400],
            )
            db.commit()
    finally:
        db.close()


def start(run_id: str) -> None:
    get_executor().submit(execute_run, run_id)
