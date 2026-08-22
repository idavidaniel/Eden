"""Projects, the ticket board, and autonomous runs."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents import engine
from db import get_db
from models import Channel, Employee, Project, Run, RunStep, Ticket, TicketComment
from models.work import TICKET_STATUSES
from services import events, workspace
from services.identity import slugify

from . import serializers
from .companies import get_company

router = APIRouter(tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    key: str | None = None
    brief: str = ""
    lead_id: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = None
    brief: str | None = None
    status: str | None = None
    lead_id: str | None = None
    # Shell-free command the platform runs to decide whether work is done,
    # e.g. "flutter test" or "python3 -m pytest -q".
    verify_command: str | None = None


class TicketIn(BaseModel):
    title: str
    description: str = ""
    type: str = "task"
    status: str = "backlog"
    priority: str = "medium"
    assignee_id: str | None = None
    acceptance_criteria: list[str] = []


class TicketPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_id: str | None = None
    order: int | None = None
    acceptance_criteria: list[str] | None = None


class CommentIn(BaseModel):
    body: str


class RunIn(BaseModel):
    brief: str | None = None


def get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def project_counts(db: Session, project_id: str) -> dict:
    rows = db.execute(
        select(Ticket.status, func.count())
        .where(Ticket.project_id == project_id)
        .group_by(Ticket.status)
    ).all()
    counts = {status: 0 for status in TICKET_STATUSES}
    counts.update({status: count for status, count in rows})
    counts["total"] = sum(count for _, count in rows)
    return counts


def unique_key(db: Session, company_id: str, name: str) -> str:
    base = "".join(ch for ch in name.upper() if ch.isalnum())[:6] or "PROJ"
    key, counter = base, 2
    while db.scalar(select(Project.id).where(Project.company_id == company_id, Project.key == key)):
        key, counter = f"{base[:5]}{counter}", counter + 1
    return key


@router.get("/companies/{company_id}/projects")
def list_projects(company_id: str, db: Session = Depends(get_db)):
    get_company(db, company_id)
    rows = list(
        db.scalars(
            select(Project)
            .where(Project.company_id == company_id)
            .order_by(Project.created_at.desc())
        )
    )
    return [serializers.project(row, project_counts(db, row.id)) for row in rows]


@router.post("/companies/{company_id}/projects", status_code=201)
def create_project(company_id: str, payload: ProjectIn, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    project = Project(
        company_id=company.id,
        name=payload.name,
        key=(payload.key or unique_key(db, company.id, payload.name)).upper(),
        brief=payload.brief,
        lead_id=payload.lead_id,
    )
    db.add(project)
    db.flush()

    space = workspace.for_project(company.slug, project.key)
    space.init(project.name)
    project.repo_path = str(space.root)

    db.add(
        Channel(
            company_id=company.id,
            project_id=project.id,
            name=slugify(project.name, "project"),
            purpose=f"Coordination for {project.name}",
            kind="project",
        )
    )
    events.record(
        db,
        company_id=company.id,
        project_id=project.id,
        actor="You",
        kind="project.created",
        summary=f"created project {project.name} [{project.key}]",
        payload={"project_id": project.id},
    )
    db.commit()
    return serializers.project(project, project_counts(db, project.id))


@router.get("/projects/{project_id}")
def read_project(project_id: str, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    runs = list(
        db.scalars(
            select(Run)
            .where(Run.project_id == project.id)
            .order_by(Run.created_at.desc())
            .limit(10)
        )
    )
    return {
        **serializers.project(project, project_counts(db, project.id)),
        "runs": [serializers.run(run) for run in runs],
    }


@router.patch("/projects/{project_id}")
def update_project(project_id: str, payload: ProjectPatch, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    changes = payload.model_dump(exclude_unset=True)

    command = changes.get("verify_command")
    if command:
        # Fail early rather than at the end of someone's turn.
        try:
            workspace.check_command(command)
        except workspace.WorkspaceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    for key, value in changes.items():
        setattr(project, key, value)
    db.add(project)
    events.record(
        db,
        company_id=project.company_id,
        project_id=project.id,
        actor="You",
        kind="project.updated",
        summary=f"updated {project.name}: {', '.join(changes) or 'no change'}",
    )
    db.commit()
    return serializers.project(project, project_counts(db, project.id))


@router.get("/projects/{project_id}/tickets")
def list_tickets(project_id: str, db: Session = Depends(get_db)):
    get_project(db, project_id)
    rows = list(
        db.scalars(
            select(Ticket).where(Ticket.project_id == project_id).order_by(Ticket.order, Ticket.key)
        )
    )
    return [serializers.ticket(row) for row in rows]


@router.post("/projects/{project_id}/tickets", status_code=201)
def create_ticket(project_id: str, payload: TicketIn, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    project.ticket_counter += 1
    ticket = Ticket(
        project_id=project.id,
        key=f"{project.key}-{project.ticket_counter}",
        title=payload.title,
        description=payload.description,
        type=payload.type,
        status=payload.status,
        priority=payload.priority,
        assignee_id=payload.assignee_id,
        acceptance_criteria=payload.acceptance_criteria,
        order=project.ticket_counter,
    )
    db.add(ticket)
    db.add(project)
    events.record(
        db,
        company_id=project.company_id,
        project_id=project.id,
        actor="You",
        kind="ticket.created",
        summary=f"created {ticket.key}: {ticket.title}",
        payload={"key": ticket.key},
    )
    db.commit()
    return serializers.ticket(ticket)


@router.get("/tickets/{ticket_id}")
def read_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    comments = list(
        db.scalars(
            select(TicketComment)
            .where(TicketComment.ticket_id == ticket.id)
            .order_by(TicketComment.created_at)
        )
    )
    steps = list(
        db.scalars(
            select(RunStep).where(RunStep.ticket_id == ticket.id).order_by(RunStep.created_at)
        )
    )
    return {
        **serializers.ticket(ticket, comments),
        "steps": [serializers.run_step(step) for step in steps],
    }


@router.patch("/tickets/{ticket_id}")
def update_ticket(ticket_id: str, payload: TicketPatch, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in TICKET_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {TICKET_STATUSES}")
    for key, value in changes.items():
        setattr(ticket, key, value)
    db.add(ticket)
    events.record(
        db,
        company_id=ticket.project.company_id,
        project_id=ticket.project_id,
        actor="You",
        kind="ticket.updated",
        summary=f"updated {ticket.key}: {', '.join(changes) or 'no change'}",
        payload={"key": ticket.key, "status": ticket.status},
    )
    db.commit()
    return serializers.ticket(ticket)


@router.delete("/tickets/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    events.record(
        db,
        company_id=ticket.project.company_id,
        project_id=ticket.project_id,
        actor="You",
        kind="ticket.deleted",
        summary=f"deleted {ticket.key}: {ticket.title}",
        payload={"key": ticket.key},
    )
    db.delete(ticket)
    db.commit()


@router.post("/tickets/{ticket_id}/comments", status_code=201)
def comment_ticket(ticket_id: str, payload: CommentIn, db: Session = Depends(get_db)):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    comment = TicketComment(ticket_id=ticket.id, author_label="You", body=payload.body)
    db.add(comment)
    events.record(
        db,
        company_id=ticket.project.company_id,
        project_id=ticket.project_id,
        actor="You",
        kind="ticket.comment",
        summary=f"commented on {ticket.key}",
        payload={"key": ticket.key, "body": payload.body[:400]},
    )
    db.commit()
    return {
        "id": comment.id,
        "author_label": comment.author_label,
        "body": comment.body,
        "created_at": serializers.iso(comment.created_at),
    }


class AutofixIn(BaseModel):
    # Defaults to the project's verification command.
    command: str | None = None
    cwd: str = ""
    max_attempts: int | None = None


@router.post("/projects/{project_id}/autofix", status_code=202)
def start_autofix(project_id: str, payload: AutofixIn, db: Session = Depends(get_db)):
    """Debug the project automatically until its check passes."""
    project = get_project(db, project_id)
    command = payload.command or project.verify_command
    if not command:
        raise HTTPException(
            status_code=400,
            detail="Set a verification command for this project, or pass one explicitly.",
        )
    try:
        workspace.check_command(command)
    except workspace.WorkspaceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine.get_executor().submit(
        engine.debug_until_green, project.id, command, payload.cwd, payload.max_attempts, "check"
    )
    return {"status": "started", "command": command, "cwd": payload.cwd}


# --- runs ---------------------------------------------------------------


@router.post("/projects/{project_id}/runs", status_code=202)
def start_run(project_id: str, payload: RunIn, db: Session = Depends(get_db)):
    project = get_project(db, project_id)
    team = db.scalar(
        select(func.count()).select_from(Employee).where(Employee.company_id == project.company_id)
    )
    if not team:
        raise HTTPException(
            status_code=400, detail="Hire at least one employee before starting a run."
        )

    active = db.scalar(
        select(Run).where(
            Run.project_id == project.id, Run.status.in_(["queued", "running", "paused"])
        )
    )
    if active:
        raise HTTPException(status_code=409, detail="This project already has a run in flight.")

    if payload.brief:
        project.brief = payload.brief
        db.add(project)

    run = Run(
        company_id=project.company_id, project_id=project.id, brief=project.brief, status="queued"
    )
    db.add(run)
    db.flush()
    events.record(
        db,
        company_id=project.company_id,
        project_id=project.id,
        run_id=run.id,
        actor="You",
        kind="run.queued",
        summary=f"queued a run for {project.name}",
        payload={"run_id": run.id},
    )
    db.commit()

    engine.start(run.id)
    return serializers.run(run)


@router.get("/runs/{run_id}")
def read_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    steps = list(
        db.scalars(select(RunStep).where(RunStep.run_id == run.id).order_by(RunStep.created_at))
    )
    return {**serializers.run(run), "steps": [serializers.run_step(step) for step in steps]}


@router.post("/runs/{run_id}/{action}")
def control_run(run_id: str, action: str, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    transitions = {"pause": "paused", "resume": "running", "cancel": "cancelling"}
    if action not in transitions:
        raise HTTPException(status_code=400, detail="Action must be pause, resume or cancel.")
    if run.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Run is already {run.status}.")

    run.status = transitions[action]
    db.add(run)
    events.record(
        db,
        company_id=run.company_id,
        project_id=run.project_id,
        run_id=run.id,
        actor="You",
        kind=f"run.{action}",
        summary=f"{action}d the run",
    )
    db.commit()
    return serializers.run(run)
