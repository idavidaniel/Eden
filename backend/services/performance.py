"""How an employee is actually doing, from check results rather than opinions.

Four numbers, all derived from things the platform ran itself:

- **first-try pass rate** — items that passed without ever being reopened;
- **rework rate** — how often work comes back;
- **tokens per accepted artifact** — what a delivered thing costs;
- **time to done** — from assignment to a closed item that passed.

The coaching loop proposes a change to a persona or a procedure, with the
numbers that motivated it. It proposes; you decide. Nothing here edits an
employee on its own.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Artifact, Company, Employee, Project, UsageEvent, WorkItem

from . import checks as check_service
from . import pricing

log = logging.getLogger(__name__)

# Below this, the numbers are noise and saying anything about them is dishonest.
MIN_ITEMS_FOR_JUDGEMENT = 4


def for_employee(db: Session, employee: Employee) -> dict:
    items = list(
        db.scalars(
            select(WorkItem)
            .join(Project, WorkItem.project_id == Project.id)
            .where(
                WorkItem.assignee_id == employee.id,
                Project.company_id == employee.company_id,
            )
        )
    )
    closed = [item for item in items if item.status == "done"]
    reworked = [item for item in items if item.rework_count > 0]
    first_try = [item for item in closed if item.rework_count == 0]

    accepted_artifacts = (
        db.scalar(
            select(func.count())
            .select_from(Artifact)
            .where(Artifact.produced_by == employee.id, Artifact.superseded_by.is_(None))
        )
        or 0
    )
    tokens = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_micros), 0.0),
        ).where(UsageEvent.employee_id == employee.id)
    ).one()
    total_tokens = int(tokens[0] or 0) + int(tokens[1] or 0)

    durations = [
        (_utc(item.closed_at) - _utc(item.created_at)).total_seconds() / 3600
        for item in closed
        if item.closed_at and item.created_at
    ]

    checks = _check_counts(db, [item.id for item in items])

    return {
        "employee_id": employee.id,
        "name": employee.name,
        "title": employee.title,
        "items_assigned": len(items),
        "items_done": len(closed),
        "first_try_pass_rate": _ratio(len(first_try), len(closed)),
        "rework_rate": _ratio(len(reworked), len(items)),
        "median_hours_to_done": round(_median(durations), 2) if durations else None,
        "artifacts_current": accepted_artifacts,
        "tokens": total_tokens,
        "tokens_per_artifact": (
            round(total_tokens / accepted_artifacts) if accepted_artifacts else None
        ),
        "cost": {
            "micros": round(float(tokens[2] or 0.0), 2),
            "display": pricing.format_cost(float(tokens[2] or 0.0)),
            "estimated": True,
        },
        "checks": checks,
        "enough_data": len(items) >= MIN_ITEMS_FOR_JUDGEMENT,
        "note": (
            "Based on checks the platform ran, not on self-assessment."
            if len(items) >= MIN_ITEMS_FOR_JUDGEMENT
            else f"Only {len(items)} item(s) so far — too few to read anything into."
        ),
    }


def for_company(db: Session, company: Company) -> dict:
    people = list(db.scalars(select(Employee).where(Employee.company_id == company.id)))
    rows = [for_employee(db, person) for person in people]
    ranked = sorted(
        [row for row in rows if row["enough_data"]],
        key=lambda row: (row["first_try_pass_rate"] or 0),
        reverse=True,
    )
    return {
        "company_id": company.id,
        "employees": rows,
        "ranked": [row["employee_id"] for row in ranked],
        "totals": {
            "items_done": sum(row["items_done"] for row in rows),
            "artifacts": sum(row["artifacts_current"] for row in rows),
            "tokens": sum(row["tokens"] for row in rows),
        },
    }


def _check_counts(db: Session, work_item_ids: list[str]) -> dict:
    if not work_item_ids:
        return {"pass": 0, "fail": 0, "pending": 0}
    counts = {"pass": 0, "fail": 0, "pending": 0}
    for item_id in work_item_ids:
        for result in check_service.latest_for_work_item(db, item_id):
            if result.status == "pass":
                counts["pass"] += 1
            elif result.status == "pending":
                counts["pending"] += 1
            elif result.status in {"fail", "error"}:
                counts["fail"] += 1
    return counts


def propose_coaching(db: Session, employee: Employee) -> dict:
    """Suggest one change, with the evidence. Never applies it.

    Applying a persona edit automatically would mean an agent's own record
    silently rewriting how it thinks. That belongs to you.
    """
    from agents.llm import structured_call
    from services import memory, usage

    stats = for_employee(db, employee)
    if not stats["enough_data"]:
        return {
            "employee_id": employee.id,
            "proposal": None,
            "reason": stats["note"],
            "stats": stats,
        }

    failures = list(
        db.scalars(
            select(WorkItem)
            .join(Project, WorkItem.project_id == Project.id)
            .where(
                WorkItem.assignee_id == employee.id,
                Project.company_id == employee.company_id,
                WorkItem.rework_count > 0,
            )
            .order_by(WorkItem.updated_at.desc())
            .limit(6)
        )
    )
    evidence = []
    for item in failures:
        verdicts = check_service.latest_for_work_item(db, item.id)
        detail = "; ".join(
            result.detail for result in verdicts if result.status in {"fail", "error"}
        )
        evidence.append(
            f"{item.key} ({item.rework_count}× reopened): {detail or item.result or ''}"
        )

    hits, _ = memory.search(
        db,
        employee.company_id,
        f"{employee.title} mistakes rework",
        employee_id=employee.id,
        kinds=["episode"],
        limit=5,
    )

    try:
        with usage.scope(
            company_id=employee.company_id, employee_id=employee.id, purpose="reflect"
        ):
            proposal = structured_call(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are a manager writing one specific coaching note about an "
                            "employee, from their record. Propose exactly one change — an "
                            "edit to how they are told to work, or a procedure they should "
                            "follow — and justify it from the evidence given. If the record "
                            "does not support a change, say so instead of inventing one."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"""{employee.name}, {employee.title}.

Numbers:
- first-try pass rate: {stats['first_try_pass_rate']}
- rework rate: {stats['rework_rate']}
- items done: {stats['items_done']} of {stats['items_assigned']}
- checks: {stats['checks']}

Work that came back:
{chr(10).join(evidence) or "(none)"}

What they have recorded about their own failures:
{chr(10).join(hit.memory.title for hit in hits) or "(nothing)"}
""",
                    },
                ],
                name="propose_coaching",
                description="Propose one change to how this employee works.",
                parameters={
                    "type": "object",
                    "properties": {
                        "change_needed": {"type": "boolean"},
                        "kind": {"type": "string", "enum": ["persona", "procedure", "none"]},
                        "title": {"type": "string"},
                        "proposed_text": {
                            "type": "string",
                            "description": "The replacement persona, or the procedure's steps.",
                        },
                        "because": {
                            "type": "string",
                            "description": "One sentence, citing the numbers or an item key.",
                        },
                    },
                    "required": ["change_needed", "kind", "because"],
                },
                max_tokens=900,
            )
    except Exception as exc:
        return {"employee_id": employee.id, "proposal": None, "error": str(exc)[:200]}

    return {
        "employee_id": employee.id,
        "stats": stats,
        "proposal": proposal if proposal.get("change_needed") else None,
        "reason": proposal.get("because", ""),
        "apply_with": f"PATCH /agents/{employee.id}/config",
        "note": "This is a proposal. Nothing changes until you apply it.",
    }


def _ratio(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
