"""Issue-tracker tools — the built-in equivalent of Jira."""

from sqlalchemy import select

from models import Employee, Ticket, TicketComment
from models.work import TICKET_STATUSES, TICKET_TYPES
from services import events

from .base import Tool, ToolContext, obj, string


def _require_project(ctx: ToolContext):
    if not ctx.project:
        raise ValueError("No project is in scope for this action.")
    return ctx.project


def _next_key(ctx: ToolContext) -> str:
    project = _require_project(ctx)
    project.ticket_counter += 1
    ctx.db.add(project)
    return f"{project.key}-{project.ticket_counter}"


def list_tickets(ctx: ToolContext, status: str = "", assignee: str = "") -> str:
    project = _require_project(ctx)
    query = select(Ticket).where(Ticket.project_id == project.id).order_by(Ticket.order, Ticket.key)
    if status:
        query = query.where(Ticket.status == status)
    tickets = list(ctx.db.scalars(query))
    if assignee:
        tickets = [t for t in tickets if t.assignee_id == assignee]
    if not tickets:
        return "No tickets match."
    names = {
        e.id: e.name
        for e in ctx.db.scalars(select(Employee).where(Employee.company_id == ctx.company.id))
    }
    return "\n".join(
        f"{t.key} [{t.status}] {t.title} — {names.get(t.assignee_id, 'unassigned')}"
        for t in tickets
    )


def create_ticket(
    ctx: ToolContext,
    title: str,
    description: str = "",
    type: str = "task",
    role_hint: str = "",
    priority: str = "medium",
) -> str:
    project = _require_project(ctx)
    ticket = Ticket(
        project_id=project.id,
        key=_next_key(ctx),
        title=title[:240],
        description=description,
        type=type if type in TICKET_TYPES else "task",
        status="backlog",
        priority=priority,
        reporter_id=ctx.employee.id,
        role_hint=role_hint or None,
        order=project.ticket_counter,
    )
    ctx.db.add(ticket)
    ctx.db.flush()
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="ticket.created",
        summary=f"created {ticket.key}: {ticket.title}",
        payload={"ticket_id": ticket.id, "key": ticket.key},
    )
    return f"Created {ticket.key}: {ticket.title}"


def update_ticket(
    ctx: ToolContext, key: str, status: str = "", assignee_name: str = "", result: str = ""
) -> str:
    project = _require_project(ctx)
    ticket = ctx.db.scalar(select(Ticket).where(Ticket.project_id == project.id, Ticket.key == key))
    if not ticket:
        return f"No ticket named {key}."

    changes = []
    if status:
        if status not in TICKET_STATUSES:
            return f"Invalid status. Use one of: {', '.join(TICKET_STATUSES)}"
        ticket.status = status
        changes.append(f"status→{status}")
    if assignee_name:
        employee = ctx.db.scalar(
            select(Employee).where(
                Employee.company_id == ctx.company.id, Employee.name.ilike(f"%{assignee_name}%")
            )
        )
        if not employee:
            return f"No colleague matches '{assignee_name}'."
        ticket.assignee_id = employee.id
        changes.append(f"assignee→{employee.name}")
    if result:
        ticket.result = result
        changes.append("result recorded")

    ctx.db.add(ticket)
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="ticket.updated",
        summary=f"updated {ticket.key}: {', '.join(changes) or 'no change'}",
        payload={"ticket_id": ticket.id, "key": ticket.key, "status": ticket.status},
    )
    return f"{ticket.key}: {', '.join(changes) or 'nothing changed'}"


def comment_ticket(ctx: ToolContext, key: str, body: str) -> str:
    project = _require_project(ctx)
    ticket = ctx.db.scalar(select(Ticket).where(Ticket.project_id == project.id, Ticket.key == key))
    if not ticket:
        return f"No ticket named {key}."
    ctx.db.add(
        TicketComment(
            ticket_id=ticket.id, author_id=ctx.employee.id, author_label=ctx.actor, body=body
        )
    )
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="ticket.comment",
        summary=f"commented on {ticket.key}",
        payload={"ticket_id": ticket.id, "key": ticket.key, "body": body[:400]},
    )
    return f"Commented on {ticket.key}."


TOOLS = [
    Tool(
        name="list_tickets",
        group="tracker",
        description="List tickets on the current project, optionally filtered by status.",
        parameters=obj(
            {
                "status": string(
                    "Optional status filter: backlog, todo, in_progress, in_review, done, blocked"
                ),
                "assignee": string("Optional employee id filter"),
            },
            required=[],
        ),
        handler=list_tickets,
    ),
    Tool(
        name="create_ticket",
        group="tracker",
        description="Create a ticket in the current project.",
        parameters=obj(
            {
                "title": string("Short imperative title"),
                "description": string("What must be done, and how it will be verified"),
                "type": string("epic, story, task, bug or chore"),
                "role_hint": string("Role best suited to this work, e.g. backend_engineer"),
                "priority": string("low, medium or high"),
            },
            required=["title"],
        ),
        handler=create_ticket,
    ),
    Tool(
        name="update_ticket",
        group="tracker",
        description="Change a ticket's status, assignee, or record its result.",
        parameters=obj(
            {
                "key": string("Ticket key, e.g. APOLLO-3"),
                "status": string("backlog, todo, in_progress, in_review, done or blocked"),
                "assignee_name": string("Colleague's name to assign it to"),
                "result": string("Short summary of the outcome"),
            },
            required=["key"],
        ),
        handler=update_ticket,
    ),
    Tool(
        name="comment_ticket",
        group="tracker",
        description="Add a comment to a ticket, visible to the whole team.",
        parameters=obj({"key": string("Ticket key"), "body": string("Comment text")}),
        handler=comment_ticket,
    ),
]
