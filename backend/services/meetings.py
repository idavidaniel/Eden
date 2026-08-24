"""Meetings that have to produce something.

A meeting between agents that ends in a transcript is a way to spend money on
prose. Every meeting here ends in a forced tool call — decisions, action items
with owners, risks — and the action items become real work items. A retro
additionally writes procedural memory, subject to the same learning gate as
everything else: it may only distil a procedure from work that passed.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from db import session
from models import Company, Employee, Meeting, Project, WorkItem
from models.work import OPEN_STATUSES

from . import events, packs, roles

log = logging.getLogger(__name__)

KINDS = ["standup", "planning", "design_review", "retro"]
MAX_ATTENDEES = 8

OUTCOME_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "description": "Things now settled. Each one a single sentence.",
            "items": {"type": "string"},
        },
        "action_items": {
            "type": "array",
            "description": "Work that follows from this meeting. Each becomes a real item.",
            "items": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "A colleague's name"},
                    "what": {"type": "string"},
                    "capability": {"type": "string"},
                    "acceptance": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["owner", "what"],
            },
        },
        "risks": {
            "type": "array",
            "description": "What could go wrong, and what would show it early.",
            "items": {"type": "string"},
        },
        "lesson": {
            "type": "object",
            "description": "Retro only: how this team should do this next time.",
            "properties": {
                "title": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
    "required": ["decisions", "action_items"],
}

PURPOSE = {
    "standup": "What moved since last time, what is next, and what is in the way.",
    "planning": "Decide what the team does next and who does it.",
    "design_review": "Decide whether the approach is right before more is built on it.",
    "retro": "Work out what actually happened and what should change.",
}


def schedule(
    db: Session,
    *,
    company: Company,
    kind: str,
    project: Project | None = None,
    title: str = "",
    attendee_ids: list[str] | None = None,
) -> Meeting:
    team = list(db.scalars(select(Employee).where(Employee.company_id == company.id)))
    if attendee_ids:
        attendees = [person for person in team if person.id in set(attendee_ids)]
    else:
        attendees = team[:MAX_ATTENDEES]
    meeting = Meeting(
        company_id=company.id,
        project_id=project.id if project else None,
        kind=kind,
        title=title or f"{kind.replace('_', ' ').capitalize()}"
        + (f" — {project.name}" if project else ""),
        attendees=[person.id for person in attendees],
        status="scheduled",
    )
    db.add(meeting)
    db.flush()
    return meeting


def start(meeting_id: str) -> None:
    from agents import engine

    engine.get_executor().submit(hold, meeting_id)


def hold(meeting_id: str) -> dict:
    """Run the meeting: gather positions, then force an outcome."""
    from agents import runtime
    from agents.llm import structured_call
    from agents.tools.base import ToolContext

    db = session()
    try:
        meeting = db.get(Meeting, meeting_id)
        if not meeting or meeting.status == "done":
            return {"status": "skipped"}
        company = db.get(Company, meeting.company_id)
        project = db.get(Project, meeting.project_id) if meeting.project_id else None
        attendees = [
            person
            for person in (db.get(Employee, pid) for pid in meeting.attendees or [])
            if person is not None
        ]
        if not attendees:
            meeting.status = "cancelled"
            db.add(meeting)
            db.commit()
            return {"status": "cancelled", "reason": "nobody to attend"}

        meeting.status = "running"
        meeting.started_at = datetime.now(UTC)
        db.add(meeting)
        db.commit()

        board = _board(db, project)
        transcript: list[str] = []
        for person in attendees:
            ctx = ToolContext(db=db, company=company, employee=person, project=project)
            outcome = runtime.run_turn(
                db,
                ctx,
                f"""You are in a {meeting.kind.replace('_', ' ')}. {PURPOSE[meeting.kind]}

{board}

Say your part in three sentences or fewer: what you did, what you are doing next,
and anything that is in your way. Do not do the work now — this is the meeting.""",
                kind="meeting",
                purpose="chat",
                max_steps=3,
            )
            transcript.append(f"{person.name} ({person.title}): {outcome.text.strip()}")

        chair = roles.manager_of(db, attendees, company) or attendees[0]
        outcome = structured_call(
            [
                {
                    "role": "system",
                    "content": (
                        f"You chaired a {meeting.kind.replace('_', ' ')} at {company.name}. "
                        "Turn what was said into decisions and action items. An action item "
                        "must have an owner who was in the room and be finishable by one "
                        "person. Do not invent work nobody mentioned."
                    ),
                },
                {
                    "role": "user",
                    "content": f"{board}\n\nWhat everyone said:\n" + "\n".join(transcript),
                },
            ],
            name="record_meeting_outcome",
            description="Record what this meeting decided and what happens next.",
            parameters=OUTCOME_SCHEMA,
            max_tokens=1500,
        )

        created = _create_action_items(db, company, project, attendees, outcome, chair)
        if meeting.kind == "retro":
            _record_lesson(db, company, project, chair, outcome)

        meeting.transcript = "\n\n".join(transcript)[:40000]
        meeting.outcome = {
            "decisions": outcome.get("decisions", []),
            "action_items": outcome.get("action_items", []),
            "risks": outcome.get("risks", []),
            "created_items": created,
        }
        meeting.status = "done"
        meeting.ended_at = datetime.now(UTC)
        db.add(meeting)
        events.record(
            db,
            company_id=company.id,
            project_id=meeting.project_id,
            actor=f"{chair.name} ({chair.title})",
            kind="meeting.held",
            summary=(
                f"{meeting.kind.replace('_', ' ')}: {len(outcome.get('decisions', []))} "
                f"decision(s), {len(created)} action item(s)"
            ),
            payload={"meeting_id": meeting.id, "created": created},
        )
        db.commit()
        return {"status": "done", "created": created}
    except Exception as exc:
        log.exception("meeting %s failed", meeting_id)
        db.rollback()
        meeting = db.get(Meeting, meeting_id)
        if meeting:
            meeting.status = "failed"
            meeting.outcome = {"error": str(exc)[:500]}
            db.add(meeting)
            db.commit()
        return {"status": "failed", "error": str(exc)[:200]}
    finally:
        db.close()


def _board(db: Session, project: Project | None) -> str:
    if not project:
        return "No project is in scope for this meeting."
    items = list(
        db.scalars(
            select(WorkItem)
            .where(WorkItem.project_id == project.id)
            .order_by(WorkItem.order, WorkItem.key)
        )
    )
    lines = "\n".join(f"- {item.key} [{item.status}] {item.title}" for item in items[:40])
    return f"Project {project.name} [{project.key}]\nBrief: {project.brief}\n\nThe board:\n{lines}"


def _create_action_items(
    db: Session,
    company: Company,
    project: Project | None,
    attendees: list[Employee],
    outcome: dict,
    chair: Employee,
) -> list[str]:
    if not project:
        return []
    kinds = packs.kinds_for(company)
    created: list[str] = []
    existing = {
        item.title.strip().lower()
        for item in db.scalars(
            select(WorkItem).where(
                WorkItem.project_id == project.id, WorkItem.status.in_(OPEN_STATUSES)
            )
        )
    }

    for action in (outcome.get("action_items") or [])[:8]:
        what = (action.get("what") or "").strip()
        if not what or what.lower() in existing:
            continue
        owner = _match(attendees, action.get("owner", ""))
        if owner is None:
            owner = roles.pick_for(
                db, company, attendees, capability=action.get("capability")
            )
        project.ticket_counter += 1
        item = WorkItem(
            project_id=project.id,
            key=f"{project.key}-{project.ticket_counter}",
            title=what[:240],
            description=f"From a {outcome.get('kind', 'meeting')}. Owner named in the room.",
            kind=kinds[0] if kinds else "task",
            status="todo",
            assignee_id=owner.id if owner else None,
            reporter_id=chair.id,
            capability_hint=action.get("capability"),
            acceptance_criteria=[str(c) for c in (action.get("acceptance") or [])][:6],
            order=project.ticket_counter,
        )
        db.add(item)
        db.add(project)
        db.flush()
        created.append(item.key)
        existing.add(what.lower())
    return created


def _record_lesson(
    db: Session, company: Company, project: Project | None, chair: Employee, outcome: dict
) -> None:
    """A retro may write a procedure — but only from work that actually passed.

    Same gate as reflection. A team that failed and then wrote down "how to do
    this" is recording a hope, not a procedure.
    """
    from . import checks as check_service
    from . import memory

    lesson = outcome.get("lesson") or {}
    if not lesson.get("title") or not lesson.get("steps"):
        return
    if not project:
        return

    closed = list(
        db.scalars(
            select(WorkItem).where(
                WorkItem.project_id == project.id, WorkItem.status == "done"
            )
        )
    )
    passed = [
        item
        for item in closed
        if check_service.verdict_for(check_service.latest_for_work_item(db, item.id))["ok"]
    ]
    if not passed:
        log.info("retro lesson refused: nothing on this project passed its checks")
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            actor="Platform",
            kind="memory.gated",
            summary="the retro's lesson was refused — no work here has passed its checks",
        )
        return

    steps = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(lesson["steps"][:12]))
    memory.remember(
        db,
        company_id=company.id,
        employee_id=None,
        scope="company",
        kind="procedure",
        title=lesson["title"][:240],
        body=f"Agreed in a retrospective after {len(passed)} item(s) passed.\n\n{steps}",
        confidence=0.75,
        source_kind="meeting",
        outcome="shipped",
        created_by=f"{chair.name} (retro)",
    )


def _match(people: list[Employee], name: str) -> Employee | None:
    lowered = (name or "").strip().lower()
    if not lowered:
        return None
    return next((person for person in people if person.name.lower() == lowered), None) or next(
        (person for person in people if lowered in person.name.lower()), None
    )
