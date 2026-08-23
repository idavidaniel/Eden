"""Employee profiles, credentials and per-person activity."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import Activity, Employee, Identity, Project, WorkItem
from services import events
from services import identity as identity_service

from . import serializers

router = APIRouter(tags=["employees"])


class EmployeePatch(BaseModel):
    name: str | None = None
    title: str | None = None
    department: str | None = None
    seniority: str | None = None
    persona: str | None = None
    skills: list[str] | None = None
    toolbelt: list[str] | None = None
    manager_id: str | None = None
    avatar: str | None = None
    status: str | None = None


def get_employee(db: Session, employee_id: str) -> Employee:
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return employee


@router.get("/employees/{employee_id}")
def read_employee(employee_id: str, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    work_items = list(
        db.scalars(
            select(WorkItem)
            .join(Project, WorkItem.project_id == Project.id)
            .where(WorkItem.assignee_id == employee.id)
            .order_by(WorkItem.updated_at.desc())
            .limit(50)
        )
    )
    recent = list(
        db.scalars(
            select(Activity)
            .where(Activity.employee_id == employee.id)
            .order_by(Activity.seq.desc())
            .limit(30)
        )
    )
    manager = db.get(Employee, employee.manager_id) if employee.manager_id else None
    return {
        **serializers.employee(employee),
        "manager": serializers.employee(manager) if manager else None,
        "work_items": [serializers.work_item(t) for t in work_items],
        "activity": [serializers.activity(a) for a in recent],
    }


@router.patch("/employees/{employee_id}")
def update_employee(employee_id: str, payload: EmployeePatch, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(employee, key, value)
    db.add(employee)

    # Being issued a new tool means being issued an account for it.
    if "toolbelt" in changes:
        identity_service.provision(db, employee, employee.company.slug, employee.toolbelt)
    db.commit()
    return serializers.employee(employee)


@router.delete("/employees/{employee_id}", status_code=204)
def delete_employee(employee_id: str, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    events.record(
        db,
        company_id=employee.company_id,
        actor="You",
        kind="employee.offboarded",
        summary=f"offboarded {employee.name} ({employee.title})",
    )
    db.delete(employee)
    db.commit()


@router.get("/employees/{employee_id}/credentials")
def reveal_credentials(employee_id: str, db: Session = Depends(get_db)):
    """Show this employee's service-account credentials, like an admin console."""
    employee = get_employee(db, employee_id)
    events.record(
        db,
        company_id=employee.company_id,
        employee_id=employee.id,
        actor="You",
        kind="identity.revealed",
        summary=f"viewed {employee.name}'s credentials",
    )
    db.commit()
    return {
        "employee_id": employee.id,
        "accounts": [identity_service.reveal(i) for i in employee.identities],
    }


@router.post("/employees/{employee_id}/credentials/{tool}/rotate")
def rotate_credentials(employee_id: str, tool: str, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    record = db.scalar(
        select(Identity).where(Identity.employee_id == employee.id, Identity.tool == tool)
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"No {tool} account for this employee.")
    identity_service.revoke(db, record)
    events.record(
        db,
        company_id=employee.company_id,
        employee_id=employee.id,
        actor="You",
        kind="identity.rotated",
        summary=f"rotated {employee.name}'s {tool} credentials",
    )
    db.commit()
    return identity_service.reveal(record)
