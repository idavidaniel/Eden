"""What an employee takes away from a piece of work.

Runs when a work item closes, not on a timer, because the interesting moment is
the one where the outcome is known.

**The learning gate.** An agent may only distil a reusable procedure — "this is
how I do X here" — from work whose checks *passed*. Facts and episodes are
recorded either way, and a failure is recorded emphatically, because that is
where the information is. But the thing that changes how future work is done has
to be earned by work that was proven to work. This project has already been
burned once by an agent confidently recording a lesson from something that never
ran; the verification gate is also the learning gate.
"""

import logging

from sqlalchemy.orm import Session

from agents.llm import structured_call
from models import Company, Employee, Project, WorkItem
from services import ledger, memory, routing, usage

log = logging.getLogger(__name__)

LEARNING_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "description": (
                "Up to three things you now know about this company, codebase, client or "
                "domain that you did not know before. Specific and reusable, not a diary."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["title"],
            },
        },
        "procedure": {
            "type": "object",
            "description": (
                "How you would do this kind of work here next time, as steps. Only "
                "offer one if the work actually passed its checks."
            ),
            "properties": {
                "title": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "applies_to": {"type": "string"},
            },
        },
        "episode": {
            "type": "object",
            "description": "One paragraph on how this went and why.",
            "properties": {
                "summary": {"type": "string"},
                "what_i_would_do_differently": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
    "required": ["episode"],
}


def reflect_on_work_item(
    db: Session,
    *,
    company: Company,
    employee: Employee,
    work_item: WorkItem,
    project: Project | None,
    passed: bool,
    outcome: str,
    check_summary: str = "",
    turn_summary: str = "",
) -> dict:
    """Ask the employee what it learned, and store only what it is allowed to."""
    prompt = _prompt(work_item, project, passed, outcome, check_summary, turn_summary)
    model = routing.model_for(employee, "reflect", company)

    try:
        with usage.scope(
            company_id=company.id, employee_id=employee.id, purpose="reflect"
        ):
            answer = structured_call(
                prompt,
                name="record_learning",
                description="Record what you learned from this piece of work.",
                parameters=LEARNING_SCHEMA,
                model=model,
                max_tokens=1500,
            )
    except Exception as exc:
        log.warning("reflection failed for %s: %s", work_item.key, exc)
        return {"stored": 0, "error": str(exc)[:200], "gate": "not reached"}

    stored: list[str] = []
    tags = [work_item.kind, outcome]

    for fact in (answer.get("facts") or [])[:3]:
        title = (fact.get("title") or "").strip()
        if not title:
            continue
        row, _ = memory.remember(
            db,
            company_id=company.id,
            employee_id=employee.id,
            kind="fact",
            title=title,
            body=(fact.get("detail") or "").strip(),
            confidence=_confidence(fact.get("confidence"), passed),
            source_kind="work_item",
            source_id=work_item.id,
            outcome=outcome,
            tags=tags,
            created_by=employee.name,
        )
        stored.append(f"fact:{row.id}")

    episode = answer.get("episode") or {}
    summary = (episode.get("summary") or "").strip()
    if summary:
        differently = (episode.get("what_i_would_do_differently") or "").strip()
        body = summary if not differently else f"{summary}\n\nNext time: {differently}"
        row, _ = memory.remember(
            db,
            company_id=company.id,
            employee_id=employee.id,
            kind="episode",
            title=f"{work_item.key}: {work_item.title}"[:240],
            body=body,
            confidence=0.9,
            source_kind="work_item",
            source_id=work_item.id,
            outcome=outcome,
            tags=tags,
            created_by=employee.name,
        )
        stored.append(f"episode:{row.id}")

    procedure = answer.get("procedure") or {}
    gate = "closed"
    if procedure.get("title") and procedure.get("steps"):
        if passed:
            steps = "\n".join(
                f"{index + 1}. {step}" for index, step in enumerate(procedure["steps"][:12])
            )
            applies = (procedure.get("applies_to") or work_item.kind).strip()
            row, _ = memory.remember(
                db,
                company_id=company.id,
                employee_id=employee.id,
                kind="procedure",
                title=procedure["title"][:240],
                body=f"Applies to: {applies}\n\n{steps}",
                confidence=0.7,
                source_kind="work_item",
                source_id=work_item.id,
                outcome="shipped",
                tags=[*tags, applies],
                created_by=employee.name,
            )
            stored.append(f"procedure:{row.id}")
            gate = "open"
        else:
            gate = "refused"
            log.info(
                "learning gate refused a procedure from %s: its checks did not pass",
                work_item.key,
            )

    db.flush()
    return {
        "stored": len(stored),
        "items": stored,
        "gate": gate,
        "outcome": outcome,
    }


def _confidence(value, passed: bool) -> float:
    try:
        base = float(value)
    except (TypeError, ValueError):
        base = 0.6
    # A fact learned during work that failed its checks is worth less.
    return max(0.1, min(1.0, base if passed else base * 0.7))


def _prompt(
    work_item: WorkItem,
    project: Project | None,
    passed: bool,
    outcome: str,
    check_summary: str,
    turn_summary: str,
) -> list[dict]:
    gate_note = (
        "This work passed its checks, so you may also record a procedure — how you "
        "would do this kind of work here next time."
        if passed
        else "This work did NOT pass its checks. Do not offer a procedure: the platform "
        "will refuse it. Record what actually happened and what you would do "
        "differently, plainly. A failure written down honestly is worth more than a "
        "lesson drawn from something that did not work."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are recording what you learned from a piece of work you just "
                "finished, for your own use later. Be specific and short. Do not record "
                "things that were already obvious, and do not congratulate yourself.\n\n"
                + gate_note
            ),
        },
        {
            "role": "user",
            "content": f"""Work item: {work_item.key} — {work_item.title}
Kind: {work_item.kind}
Project: {project.name if project else "(none)"}
Outcome: {outcome}

What you did:
{turn_summary or work_item.result or "(nothing recorded)"}

What the platform's checks said:
{check_summary or "(no checks ran)"}
""",
        },
    ]


def consider_promotions(db: Session, company: Company) -> list[str]:
    """Move well-used private memories up to company level.

    Threshold is corroboration, not popularity: three uses across at least two
    different agents. One agent's wrong belief does not get to become policy.
    """
    promoted = []
    for candidate in memory.promotable(db, company.id):
        memory.promote(db, candidate, to="company", by="the platform")
        ledger.append(
            db,
            company_id=company.id,
            kind="memory.promoted",
            actor_label="Platform",
            subject_kind="memory",
            subject_id=candidate.id,
            payload={
                "title": candidate.title,
                "kind": candidate.kind,
                "uses": candidate.uses,
                "distinct_agents": len(candidate.used_by or []),
            },
        )
        promoted.append(candidate.id)
    if promoted:
        db.flush()
    return promoted
