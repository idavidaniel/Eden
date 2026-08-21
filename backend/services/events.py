"""The activity feed: every meaningful thing an employee does lands here.

Consumers (the live feed in the dashboard) poll by `seq`, which is a monotonic
cursor, so a reconnecting client never misses or repeats an event.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Activity


def record(
    db: Session,
    *,
    company_id: str,
    kind: str,
    summary: str,
    actor: str = "System",
    employee_id: str | None = None,
    project_id: str | None = None,
    run_id: str | None = None,
    payload: dict | None = None,
) -> Activity:
    activity = Activity(
        company_id=company_id,
        project_id=project_id,
        run_id=run_id,
        employee_id=employee_id,
        actor=actor,
        kind=kind,
        summary=summary[:400],
        payload=payload or {},
    )
    db.add(activity)
    db.flush()
    return activity


def since(
    db: Session,
    company_id: str,
    cursor: int = 0,
    limit: int = 100,
    project_id: str | None = None,
) -> list[Activity]:
    query = (
        select(Activity)
        .where(Activity.company_id == company_id, Activity.seq > cursor)
        .order_by(Activity.seq)
        .limit(limit)
    )
    if project_id:
        query = query.where(Activity.project_id == project_id)
    return list(db.scalars(query))


def latest(db: Session, company_id: str, limit: int = 50) -> list[Activity]:
    query = (
        select(Activity)
        .where(Activity.company_id == company_id)
        .order_by(Activity.seq.desc())
        .limit(limit)
    )
    return list(reversed(list(db.scalars(query))))
