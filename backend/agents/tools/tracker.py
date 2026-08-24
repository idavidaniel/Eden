"""Issue-tracker tools — the built-in equivalent of Jira."""

from sqlalchemy import select

from models import Employee, WorkItem, WorkItemComment
from models.work import WORK_ITEM_STATUSES
from services import connectors, events
from services.packs import kinds_for

from .base import Tool, ToolContext, ToolResult, failed, obj, string


def _external(ctx: ToolContext):
    """The company's real tracker, when one is connected.

    Same tool surface either way: an employee never learns "the Jira version" of
    create_ticket, because there is not one.
    """
    return connectors.tracker_for(ctx.db, ctx.company)


def _require_project(ctx: ToolContext):
    if not ctx.project:
        raise ValueError("No project is in scope for this action.")
    return ctx.project


def _next_key(ctx: ToolContext) -> str:
    project = _require_project(ctx)
    project.ticket_counter += 1
    ctx.db.add(project)
    return f"{project.key}-{project.ticket_counter}"


def list_tickets(ctx: ToolContext, status: str = "", assignee: str = "") -> ToolResult:
    tracker = _external(ctx)
    if tracker:
        try:
            items = tracker.list_items(status=status, assignee=assignee)
        except connectors.ConnectorError as exc:
            return failed(f"{tracker.provider} would not answer: {exc}", "")
        if not items:
            return ToolResult(text="No items match.")
        return ToolResult(text="\n".join(item.line() for item in items))

    project = _require_project(ctx)
    query = (
        select(WorkItem)
        .where(WorkItem.project_id == project.id)
        .order_by(WorkItem.order, WorkItem.key)
    )
    if status:
        query = query.where(WorkItem.status == status)
    work_items = list(ctx.db.scalars(query))
    if assignee:
        work_items = [t for t in work_items if t.assignee_id == assignee]
    if not work_items:
        return ToolResult(text="No work items match.")
    names = {
        e.id: e.name
        for e in ctx.db.scalars(select(Employee).where(Employee.company_id == ctx.company.id))
    }
    return ToolResult(
        text="\n".join(
            f"{t.key} [{t.status}] {t.title} — {names.get(t.assignee_id, 'unassigned')}"
            for t in work_items
        )
    )


def create_ticket(
    ctx: ToolContext,
    title: str,
    description: str = "",
    kind: str = "task",
    role_hint: str = "",
    priority: str = "medium",
) -> ToolResult:
    tracker = _external(ctx)
    if tracker:
        try:
            item = tracker.create_item(title=title, description=description, kind=kind)
        except connectors.ConnectorError as exc:
            return failed(f"{tracker.provider} would not take it: {exc}", "")
        return ToolResult(text=f"Created {item.key} in {tracker.provider}: {item.title}")

    project = _require_project(ctx)
    work_item = WorkItem(
        project_id=project.id,
        key=_next_key(ctx),
        title=title[:240],
        description=description,
        kind=kind if kind in kinds_for(ctx.company) else "task",
        status="backlog",
        priority=priority,
        reporter_id=ctx.employee.id,
        role_hint=role_hint or None,
        order=project.ticket_counter,
    )
    ctx.db.add(work_item)
    ctx.db.flush()
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="work_item.created",
        summary=f"created {work_item.key}: {work_item.title}",
        payload={"work_item_id": work_item.id, "key": work_item.key},
    )
    return ToolResult(text=f"Created {work_item.key}: {work_item.title}")


def update_ticket(
    ctx: ToolContext, key: str, status: str = "", assignee_name: str = "", result: str = ""
) -> ToolResult:
    tracker = _external(ctx)
    if tracker:
        try:
            item = tracker.update_item(
                key=key, status=status, assignee=assignee_name, result=result
            )
        except connectors.ConnectorError as exc:
            return failed(f"{tracker.provider} would not update {key}: {exc}", "")
        return ToolResult(
            text=f"{item.key} is now {item.status or 'updated'} in {tracker.provider}."
        )

    project = _require_project(ctx)
    work_item = ctx.db.scalar(
        select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.key == key)
    )
    if not work_item:
        return failed(f"No work item named {key}.", "Call list_tickets to see the keys.")

    changes = []
    if status:
        if status not in WORK_ITEM_STATUSES:
            return failed(
                f"'{status}' is not a status here.",
                f"Use one of: {', '.join(WORK_ITEM_STATUSES)}",
            )
        work_item.status = status
        changes.append(f"status→{status}")
    if assignee_name:
        employee = ctx.db.scalar(
            select(Employee).where(
                Employee.company_id == ctx.company.id, Employee.name.ilike(f"%{assignee_name}%")
            )
        )
        if not employee:
            return failed(
                f"No colleague matches '{assignee_name}'.", "Call list_colleagues."
            )
        work_item.assignee_id = employee.id
        changes.append(f"assignee→{employee.name}")
    if result:
        work_item.result = result
        changes.append("result recorded")

    ctx.db.add(work_item)
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="work_item.updated",
        summary=f"updated {work_item.key}: {', '.join(changes) or 'no change'}",
        payload={"work_item_id": work_item.id, "key": work_item.key, "status": work_item.status},
    )
    return ToolResult(text=f"{work_item.key}: {', '.join(changes) or 'nothing changed'}")


def comment_ticket(ctx: ToolContext, key: str, body: str) -> ToolResult:
    tracker = _external(ctx)
    if tracker:
        try:
            return ToolResult(text=tracker.comment(key=key, body=body))
        except connectors.ConnectorError as exc:
            return failed(f"{tracker.provider} would not take the comment: {exc}", "")

    project = _require_project(ctx)
    work_item = ctx.db.scalar(
        select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.key == key)
    )
    if not work_item:
        return failed(f"No work item named {key}.", "Call list_tickets to see the keys.")
    ctx.db.add(
        WorkItemComment(
            work_item_id=work_item.id, author_id=ctx.employee.id, author_label=ctx.actor, body=body
        )
    )
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=project.id,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="work_item.comment",
        summary=f"commented on {work_item.key}",
        payload={"work_item_id": work_item.id, "key": work_item.key, "body": body[:400]},
    )
    return ToolResult(text=f"Commented on {work_item.key}.")


TOOLS = [
    Tool(
        name="list_tickets",
        group="tracker",
        description="List work_items on the current project, optionally filtered by status.",
        parameters=obj(
            {
                "status": string(
                    "Optional status filter: backlog, todo, in_progress, in_review, done, blocked"
                ),
                "assignee": string("Optional employee id filter"),
            },
            required=[],
        ),
        read_only=True,
        handler=list_tickets,
    ),
    Tool(
        name="create_ticket",
        group="tracker",
        description="Create a work_item in the current project.",
        parameters=obj(
            {
                "title": string("Short imperative title"),
                "description": string("What must be done, and how it will be verified"),
                "kind": string("Kind of work item, e.g. task, bug, matter or research_question"),
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
        description="Change a work_item's status, assignee, or record its result.",
        parameters=obj(
            {
                "key": string("WorkItem key, e.g. APOLLO-3"),
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
        description="Add a comment to a work_item, visible to the whole team.",
        parameters=obj({"key": string("WorkItem key"), "body": string("Comment text")}),
        handler=comment_ticket,
    ),
]
