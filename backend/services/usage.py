"""Records what every model call cost, and who spent it.

`llm.py` does not know which employee it is serving, so the caller declares that
with `scope()`. It is a context variable rather than an argument because the
model client is called from a dozen places and none of them should have to
thread bookkeeping through.
"""

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Employee, UsageEvent

from .pricing import cost_micros

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Attribution:
    company_id: str | None = None
    employee_id: str | None = None
    task_id: str | None = None
    run_id: str | None = None
    purpose: str | None = None


_EMPTY = Attribution()
_current: ContextVar[Attribution | None] = ContextVar("usage_attribution", default=None)


def current() -> Attribution:
    return _current.get() or _EMPTY


@contextmanager
def scope(**fields):
    """Attribute every model call made inside this block."""
    token = _current.set(replace(current(), **fields))
    try:
        yield
    finally:
        _current.reset(token)


def record(
    model: str,
    *,
    kind: str = "chat",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    ok: bool = True,
    attribution: Attribution | None = None,
) -> None:
    """Write one usage row. Never raises: bookkeeping must not break a turn."""
    who = attribution or current()
    from db import session  # imported late: config may not be loaded at import time

    db = session()
    try:
        db.add(
            UsageEvent(
                created_at=datetime.now(UTC),
                company_id=who.company_id,
                employee_id=who.employee_id,
                task_id=who.task_id,
                run_id=who.run_id,
                model=model,
                kind=kind,
                purpose=who.purpose,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_micros=cost_micros(model, prompt_tokens, completion_tokens),
                latency_ms=latency_ms,
                ok=ok,
            )
        )
        db.commit()
    except Exception:
        log.debug("could not record usage", exc_info=True)
        db.rollback()
    finally:
        db.close()


def _totals(db: Session, *filters) -> dict:
    row = db.execute(
        select(
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0.0),
        ).where(*filters)
    ).one()
    return {
        "calls": int(row[0] or 0),
        "prompt_tokens": int(row[1] or 0),
        "completion_tokens": int(row[2] or 0),
        "cost_micros": float(row[3] or 0.0),
    }


def _start_of_day() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_month() -> datetime:
    now = datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def for_employee(db: Session, employee_id: str) -> dict:
    return {
        "today": _totals(
            db,
            UsageEvent.employee_id == employee_id,
            UsageEvent.created_at >= _start_of_day(),
        ),
        "month": _totals(
            db,
            UsageEvent.employee_id == employee_id,
            UsageEvent.created_at >= _start_of_month(),
        ),
        "all_time": _totals(db, UsageEvent.employee_id == employee_id),
    }


def for_company(db: Session, company_id: str) -> dict:
    return {
        "today": _totals(
            db, UsageEvent.company_id == company_id, UsageEvent.created_at >= _start_of_day()
        ),
        "month": _totals(
            db, UsageEvent.company_id == company_id, UsageEvent.created_at >= _start_of_month()
        ),
        "all_time": _totals(db, UsageEvent.company_id == company_id),
    }


def spend_today_micros(db: Session, employee_id: str) -> float:
    return _totals(
        db, UsageEvent.employee_id == employee_id, UsageEvent.created_at >= _start_of_day()
    )["cost_micros"]


def by_employee(db: Session, company_id: str, since: datetime | None = None) -> list[dict]:
    """Per-employee spend for the company, newest window first."""
    filters = [UsageEvent.company_id == company_id]
    if since:
        filters.append(UsageEvent.created_at >= since)
    rows = db.execute(
        select(
            UsageEvent.employee_id,
            func.count(UsageEvent.id),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0.0),
        )
        .where(*filters)
        .group_by(UsageEvent.employee_id)
    ).all()
    names = {
        e.id: e.name for e in db.scalars(select(Employee).where(Employee.company_id == company_id))
    }
    return sorted(
        [
            {
                "employee_id": row[0],
                "name": names.get(row[0], "—"),
                "calls": int(row[1] or 0),
                "prompt_tokens": int(row[2] or 0),
                "completion_tokens": int(row[3] or 0),
                "cost_micros": float(row[4] or 0.0),
            }
            for row in rows
        ],
        key=lambda item: item["cost_micros"],
        reverse=True,
    )
