"""Company CRUD, hiring, org chart and the live activity feed."""

import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db import get_db, session
from models import Channel, Company, Employee, Project, WorkItem
from services import events, identity, packs
from services import roles as roles_service

from . import serializers

router = APIRouter(tags=["companies"])

# A stream is deliberately short-lived; the browser reconnects transparently.
STREAM_SECONDS = float(os.getenv("STREAM_SECONDS", "120"))
STREAM_POLL_SECONDS = 1.0

DEFAULT_CHANNELS = [
    ("general", "Company-wide announcements and standups"),
    ("engineering", "Implementation chatter"),
    ("random", "Everything else"),
]


class CompanyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    tagline: str | None = None
    description: str | None = None
    industry: str | None = None
    mission: str | None = None
    handbook: str | None = None
    # Hire a starting team straight away; empty list means an empty company.
    starting_team: list[str] | None = None


class CompanyPatch(BaseModel):
    name: str | None = None
    tagline: str | None = None
    description: str | None = None
    industry: str | None = None
    mission: str | None = None
    handbook: str | None = None


class EmployeeIn(BaseModel):
    name: str | None = None
    role_key: str = "generalist"
    title: str | None = None
    seniority: str = "Mid"
    persona: str | None = None
    skills: list[str] | None = None
    toolbelt: list[str] | None = None
    capabilities: list[str] | None = None
    model_policy: dict | None = None
    manager_id: str | None = None
    avatar: str | None = None


NAME_POOL = [
    "Ada",
    "Bo",
    "Cleo",
    "Dara",
    "Eli",
    "Faye",
    "Gus",
    "Hana",
    "Iris",
    "Jae",
    "Kit",
    "Lior",
    "Mika",
    "Nils",
    "Ora",
    "Pax",
    "Quinn",
    "Remy",
    "Sana",
    "Tao",
]
SURNAMES = [
    "Kern",
    "Vance",
    "Oyelaran",
    "Marsh",
    "Idris",
    "Novak",
    "Reyes",
    "Sato",
    "Okafor",
    "Lindqvist",
]


def unique_slug(db: Session, name: str) -> str:
    base = identity.slugify(name, "company")
    slug, counter = base, 2
    while db.scalar(select(Company.id).where(Company.slug == slug)):
        slug, counter = f"{base}-{counter}", counter + 1
    return slug


def generate_name(db: Session, company_id: str) -> str:
    taken = {e.name for e in db.scalars(select(Employee).where(Employee.company_id == company_id))}
    # Walk first names and surnames at different rates so a team does not end up
    # with six people who share a first name.
    for index in range(len(NAME_POOL) * len(SURNAMES)):
        first = NAME_POOL[index % len(NAME_POOL)]
        last = SURNAMES[(index // len(NAME_POOL)) % len(SURNAMES)]
        if f"{first} {last}" not in taken:
            return f"{first} {last}"
    return f"Agent {len(taken) + 1}"


def hire(db: Session, company: Company, spec: EmployeeIn) -> Employee:
    role = roles_service.get_role(db, company, spec.role_key)
    employee = Employee(
        company_id=company.id,
        name=spec.name or generate_name(db, company.id),
        title=spec.title or role.title,
        department=role.department,
        seniority=spec.seniority,
        role_key=role.key,
        persona=spec.persona or role.persona,
        skills=spec.skills or list(role.skills),
        toolbelt=spec.toolbelt or list(role.toolbelt),
        capabilities=spec.capabilities or list(role.capabilities or []),
        manager_id=spec.manager_id,
        avatar=spec.avatar or role.avatar,
        model_policy=spec.model_policy or {},
    )
    db.add(employee)
    db.flush()
    identity.provision(db, employee, company.slug, employee.toolbelt)
    events.record(
        db,
        company_id=company.id,
        employee_id=employee.id,
        actor="You",
        kind="employee.hired",
        summary=f"hired {employee.name} as {employee.title}",
        payload={"employee_id": employee.id, "role": role.key},
    )
    return employee


def company_stats(db: Session, company_id: str) -> dict:
    employees = db.scalar(
        select(func.count()).select_from(Employee).where(Employee.company_id == company_id)
    )
    projects = db.scalar(
        select(func.count()).select_from(Project).where(Project.company_id == company_id)
    )
    work_items = db.scalar(
        select(func.count())
        .select_from(WorkItem)
        .join(Project, WorkItem.project_id == Project.id)
        .where(Project.company_id == company_id)
    )
    done = db.scalar(
        select(func.count())
        .select_from(WorkItem)
        .join(Project, WorkItem.project_id == Project.id)
        .where(Project.company_id == company_id, WorkItem.status == "done")
    )
    working = db.scalar(
        select(func.count())
        .select_from(Employee)
        .where(Employee.company_id == company_id, Employee.status == "working")
    )
    return {
        "employees": employees or 0,
        "projects": projects or 0,
        "work_items": work_items or 0,
        "tickets_done": done or 0,
        "working_now": working or 0,
    }


def get_company(db: Session, company_id: str) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    return company


def _role_json(role) -> dict:
    return {
        "key": role.key,
        "title": role.title,
        "department": role.department,
        "avatar": role.avatar,
        "summary": role.summary,
        "skills": role.skills or [],
        "toolbelt": role.toolbelt or [],
        "capabilities": role.capabilities or [],
        "manages": role.manages,
        "persona": role.persona,
    }


@router.get("/packs")
def list_industry_packs():
    """Every industry a company can be founded in."""
    return [
        {
            "key": pack.key,
            "name": pack.name,
            "tagline": pack.tagline,
            "description": pack.description,
            "departments": pack.departments,
            "work_item_kinds": pack.work_item_kinds,
            "default_team": pack.default_team,
            "roles": [_role_json(role) for role in pack.roles],
            "artifact_kinds": pack.artifact_kinds,
            "checks": [
                {"key": c["key"], "name": c.get("name", c["key"]), "kind": c["kind"]}
                for c in pack.checks
            ],
        }
        for pack in packs.list_packs()
    ]


@router.get("/capabilities")
def list_capabilities():
    return [{"key": key, "label": label} for key, label in packs.CAPABILITY_LABELS.items()]


@router.get("/roles")
def roles(company_id: str | None = None, pack: str | None = None, db: Session = Depends(get_db)):
    """Hireable roles: a company's own if one is named, otherwise a pack's."""
    if company_id:
        company = get_company(db, company_id)
        return [_role_json(role) for role in roles_service.list_roles(db, company)]
    return [_role_json(role) for role in packs.get_pack(pack).roles]


@router.get("/companies/{company_id}/roles")
def company_roles(company_id: str, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    return [_role_json(role) for role in roles_service.list_roles(db, company)]


@router.get("/companies")
def list_companies(db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Company).order_by(Company.created_at.desc())))
    return [serializers.company(row, company_stats(db, row.id)) for row in rows]


@router.post("/companies", status_code=201)
def create_company(payload: CompanyIn, db: Session = Depends(get_db)):
    company = Company(
        name=payload.name,
        slug=unique_slug(db, payload.name),
        tagline=payload.tagline,
        description=payload.description,
        industry=payload.industry,
        mission=payload.mission,
        handbook=payload.handbook,
    )
    db.add(company)
    db.flush()

    for name, purpose in DEFAULT_CHANNELS:
        db.add(Channel(company_id=company.id, name=name, purpose=purpose))

    events.record(
        db,
        company_id=company.id,
        actor="You",
        kind="company.created",
        summary=f"founded {company.name}",
    )

    team = (
        payload.starting_team
        if payload.starting_team is not None
        else roles_service.default_team(company)
    )
    manager = None
    for role_key in team:
        employee = hire(db, company, EmployeeIn(role_key=role_key))
        if roles_service.get_role(db, company, role_key).manages and manager is None:
            manager = employee
    if manager:
        for employee in db.scalars(select(Employee).where(Employee.company_id == company.id)):
            if employee.id != manager.id and employee.manager_id is None:
                employee.manager_id = manager.id
                db.add(employee)

    db.commit()
    return serializers.company(company, company_stats(db, company.id))


@router.get("/companies/{company_id}")
def read_company(company_id: str, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    return serializers.company(company, company_stats(db, company.id))


@router.patch("/companies/{company_id}")
def update_company(company_id: str, payload: CompanyPatch, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, key, value)
    db.add(company)
    db.commit()
    return serializers.company(company, company_stats(db, company.id))


@router.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: str, db: Session = Depends(get_db)):
    db.delete(get_company(db, company_id))
    db.commit()


@router.get("/companies/{company_id}/employees")
def list_employees(company_id: str, db: Session = Depends(get_db)):
    get_company(db, company_id)
    rows = list(
        db.scalars(
            select(Employee).where(Employee.company_id == company_id).order_by(Employee.created_at)
        )
    )
    return [serializers.employee(row) for row in rows]


@router.post("/companies/{company_id}/employees", status_code=201)
def create_employee(company_id: str, payload: EmployeeIn, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    employee = hire(db, company, payload)
    db.commit()
    return serializers.employee(employee)


@router.get("/companies/{company_id}/activity")
def activity_feed(
    company_id: str,
    cursor: int = 0,
    limit: int = Query(60, le=200),
    project_id: str | None = None,
    db: Session = Depends(get_db),
):
    get_company(db, company_id)
    rows = (
        events.since(db, company_id, cursor, limit, project_id)
        if cursor
        else events.latest(db, company_id, limit)
    )
    return {
        "events": [serializers.activity(row) for row in rows],
        "cursor": rows[-1].seq if rows else cursor,
    }


@router.get("/companies/{company_id}/stream")
async def activity_stream(company_id: str, request: Request, cursor: int = 0):
    """Server-sent events: a tail of the activity log for this company.

    The stream closes itself after STREAM_SECONDS. EventSource reconnects on its
    own and sends back the last id it saw, so nothing is missed - and no
    long-lived connection is left holding the server open through a restart.
    """
    start_from = int(request.headers.get("last-event-id") or cursor)

    async def publisher():
        last = start_from
        elapsed = 0.0
        while elapsed < STREAM_SECONDS:
            if await request.is_disconnected():
                return
            db = session()
            try:
                payload = [serializers.activity(row) for row in events.since(db, company_id, last)]
            finally:
                db.close()

            if payload:
                last = payload[-1]["seq"]
                for item in payload:
                    yield f"id: {item['seq']}\ndata: {json.dumps(item)}\n\n"
            elif int(elapsed) % 15 == 0:  # keep proxies from closing an idle stream
                yield ": keep-alive\n\n"

            await asyncio.sleep(STREAM_POLL_SECONDS)
            elapsed += STREAM_POLL_SECONDS

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
