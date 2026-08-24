"""The org clock: the company keeps working without anyone starting a run.

One daemon thread wakes every few seconds and does four things:

1. reclaims tasks whose lease expired, because a worker died mid-turn;
2. leases queued tasks with `SELECT … FOR UPDATE SKIP LOCKED`, so two processes
   never pick up the same one;
3. turns ready work into tasks — items nothing is blocking, and inboxes that
   have unread messages;
4. retires memories nothing has used.

A Run becomes a label that groups tasks rather than the thing that executes
them. `execute_run` still works exactly as before, so nothing regresses.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from config import get_settings
from db import session
from models import AgentMessage, AgentTask, Company, Employee, Project

log = logging.getLogger(__name__)

TICK_SECONDS = 5.0
LEASE_SECONDS = 900
# Never start more than this many tasks in one tick, however much is waiting.
MAX_DISPATCH_PER_TICK = 4
# How often to look for new work rather than just draining the queue.
SCHEDULE_EVERY_TICKS = 4
MEMORY_SWEEP_EVERY_TICKS = 720  # roughly hourly

_thread: threading.Thread | None = None
_stop = threading.Event()
_lock = threading.Lock()
_state = {"ticks": 0, "dispatched": 0, "reclaimed": 0, "last_tick": None, "last_error": None}


def status() -> dict:
    return {**_state, "running": bool(_thread and _thread.is_alive()), "tick_seconds": TICK_SECONDS}


def start() -> None:
    """Start the clock. Safe to call more than once."""
    global _thread
    with _lock:
        if _thread and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="org-clock", daemon=True)
        _thread.start()
        log.info("org clock started, ticking every %.0fs", TICK_SECONDS)


def stop() -> None:
    _stop.set()


def _loop() -> None:
    ticks = 0
    while not _stop.is_set():
        ticks += 1
        try:
            tick(
                schedule=ticks % SCHEDULE_EVERY_TICKS == 1,
                sweep=ticks % MEMORY_SWEEP_EVERY_TICKS == 0,
            )
        except Exception as exc:
            _state["last_error"] = str(exc)[:300]
            log.exception("clock tick failed")
        _stop.wait(TICK_SECONDS)


def tick(schedule: bool = True, sweep: bool = False) -> dict:
    """One pass. Exposed so it can be driven by hand in a test or from the API."""
    from agents import worker

    db = session()
    started = datetime.now(UTC)
    reclaimed = dispatched = created = 0
    try:
        reclaimed = reclaim_expired(db)
        if schedule:
            created = schedule_ready_work(db)
        if sweep:
            sweep_memories(db)

        for task in lease_next(db, MAX_DISPATCH_PER_TICK):
            worker.start(task.id)
            dispatched += 1
    finally:
        db.close()

    _state["ticks"] += 1
    _state["dispatched"] += dispatched
    _state["reclaimed"] += reclaimed
    _state["last_tick"] = started.isoformat()
    return {"reclaimed": reclaimed, "created": created, "dispatched": dispatched}


# --------------------------------------------------------------------------
# leasing
# --------------------------------------------------------------------------


def lease_next(db: Session, limit: int) -> list[AgentTask]:
    """Claim up to `limit` runnable tasks, skipping ones another worker holds."""
    now = datetime.now(UTC)
    query = (
        select(AgentTask)
        .where(
            AgentTask.status == "queued",
            AgentTask.cancel_requested.is_(False),
            or_(AgentTask.scheduled_for.is_(None), AgentTask.scheduled_for <= now),
        )
        .order_by(AgentTask.priority, AgentTask.created_at)
        .limit(limit)
    )
    if db.bind and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    claimed: list[AgentTask] = []
    # Claims made in this batch are not in the database yet, so the one-turn-per
    # -employee rule has to remember them here as well as query for them.
    taken: set[str] = set()
    for task in db.scalars(query):
        if task.employee_id in taken:
            continue
        if _busy(db, task.employee_id) or _halted(db, task.company_id):
            continue
        task.status = "leased"
        task.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        db.add(task)
        taken.add(task.employee_id)
        claimed.append(task)
    db.commit()
    return claimed


def _busy(db: Session, employee_id: str) -> bool:
    """One turn per employee at a time. They have one workspace and one identity."""
    return bool(
        db.scalar(
            select(AgentTask.id)
            .where(
                AgentTask.employee_id == employee_id,
                AgentTask.status.in_(["leased", "running"]),
            )
            .limit(1)
        )
    )


def _halted(db: Session, company_id: str) -> bool:
    return bool(db.scalar(select(Company.halted).where(Company.id == company_id)))


def reclaim_expired(db: Session) -> int:
    """A worker that died mid-turn leaves a lease behind. Take it back."""
    now = datetime.now(UTC)
    stale = list(
        db.scalars(
            select(AgentTask).where(
                AgentTask.status.in_(["leased", "running"]),
                AgentTask.lease_until.is_not(None),
                AgentTask.lease_until < now,
            )
        )
    )
    for task in stale:
        if task.attempts >= 3:
            task.status = "failed"
            task.error = "Gave up after three attempts that never finished."
            task.finished_at = now
        else:
            task.status = "queued"
            task.lease_until = None
        db.add(task)
        employee = db.get(Employee, task.employee_id)
        if employee and employee.status == "working":
            employee.status, employee.status_note, employee.heartbeat_at = "idle", None, None
            db.add(employee)
    if stale:
        log.warning("reclaimed %s task(s) whose lease expired", len(stale))
        db.commit()
    return len(stale)


# --------------------------------------------------------------------------
# finding work
# --------------------------------------------------------------------------


def schedule_ready_work(db: Session) -> int:
    """Turn the state of the world into tasks: ready items, and full inboxes."""
    from agents import engine, worker

    created = 0
    companies = list(db.scalars(select(Company).where(Company.halted.is_(False))))
    for company in companies:
        if not _autonomous(company):
            continue
        for project in db.scalars(
            select(Project).where(
                Project.company_id == company.id,
                Project.status.in_(["in_progress", "planning"]),
            )
        ):
            for item in engine.ready_items(db, project.id)[:3]:
                if not item.assignee_id or _has_task_for(db, item.id):
                    continue
                worker.enqueue(
                    db,
                    company=company,
                    employee=db.get(Employee, item.assignee_id),
                    kind="work_item",
                    request={"project_id": project.id},
                    source="clock",
                    created_by="Org clock",
                    work_item_id=item.id,
                    priority=50,
                )
                created += 1

        for employee in db.scalars(
            select(Employee).where(Employee.company_id == company.id)
        ):
            if _busy(db, employee.id) or _has_inbox_task(db, employee.id):
                continue
            waiting = db.scalar(
                select(AgentMessage.id)
                .where(
                    AgentMessage.to_id == employee.id,
                    AgentMessage.handled_at.is_(None),
                )
                .limit(1)
            )
            if waiting:
                worker.enqueue(
                    db,
                    company=company,
                    employee=employee,
                    kind="inbox",
                    request={},
                    source="clock",
                    created_by="Org clock",
                    priority=40,
                )
                created += 1

    if created:
        db.commit()
    return created


def _autonomous(company: Company) -> bool:
    """Off by default. The clock spends money, so it is opt-in per company."""
    return bool((company.settings or {}).get("autonomous"))


def _has_task_for(db: Session, work_item_id: str) -> bool:
    return bool(
        db.scalar(
            select(AgentTask.id)
            .where(
                AgentTask.work_item_id == work_item_id,
                AgentTask.status.in_(["queued", "leased", "running"]),
            )
            .limit(1)
        )
    )


def _has_inbox_task(db: Session, employee_id: str) -> bool:
    return bool(
        db.scalar(
            select(AgentTask.id)
            .where(
                AgentTask.employee_id == employee_id,
                AgentTask.kind == "inbox",
                AgentTask.status.in_(["queued", "leased", "running"]),
            )
            .limit(1)
        )
    )


def sweep_memories(db: Session) -> int:
    from services import memory

    total = 0
    for company in db.scalars(select(Company)):
        total += memory.archive_stale(db, company.id)
        memory.backfill_embeddings(db, company.id)
    if total:
        db.commit()
        log.info("archived %s stale memories", total)
    return total


def enabled() -> bool:
    import os

    return os.getenv("ORG_CLOCK", "true").lower() not in {"0", "false", "no"} and bool(
        get_settings().database_url
    )


def wait_for(task_id: str, timeout: float = 60.0) -> AgentTask | None:
    """Block until a task finishes. For tests and synchronous callers."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db = session()
        try:
            task = db.get(AgentTask, task_id)
            if task and task.status in {"done", "failed", "cancelled"}:
                return task
        finally:
            db.close()
        time.sleep(0.2)
    return None
