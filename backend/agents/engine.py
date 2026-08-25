"""The company runtime: plan a brief, work the items, verify, review, wrap up.

A run is one way work gets done — the one you start by hand. The org clock is
the other, and both funnel into the same turn loop in `runtime.py`. Every step
writes to the database as it happens, so the dashboard's live feed is a tail of
the activity table and a crash mid-run keeps whatever already finished.

The rule this file exists to enforce: nobody's word is taken for anything. An
employee can set their own item to done and the platform will still run the
checks and reopen it.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents import context as context_builder
from agents import prompts, reflect, runtime
from agents.llm import structured_call
from agents.tools.base import ToolContext
from config import get_settings
from db import session
from models import Company, Employee, Project, Run, RunStep, WorkItem, WorkItemComment
from models.work import OPEN_STATUSES
from services import artifacts as artifact_service
from services import autofix, events, ledger, packs, roles, workspace
from services import checks as check_service

log = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_lock = threading.Lock()


def get_executor() -> ThreadPoolExecutor:
    global _executor
    with _lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=get_settings().run_concurrency, thread_name_prefix="run"
            )
        return _executor


# Kept as the public name; the loop itself lives in runtime.py now.
def run_agent_turn(
    db: Session,
    ctx: ToolContext,
    task_prompt: str,
    kind: str = "work",
    max_steps: int | None = None,
) -> RunStep:
    return runtime.run_turn(db, ctx, task_prompt, kind=kind, max_steps=max_steps).step


def _set_status(db: Session, employee: Employee, status: str, note: str = "") -> None:
    employee.status = status
    employee.status_note = note[:240] or None
    db.add(employee)
    db.commit()


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------


def plan_run(db: Session, run: Run, project: Project, team: list[Employee]) -> list[WorkItem]:
    """The manager turns the brief into assigned, ordered work."""
    company = project.company
    manager = roles.manager_of(db, team, company) or team[0]
    _set_status(db, manager, "working", f"planning {project.key}")

    events.record(
        db,
        company_id=run.company_id,
        project_id=project.id,
        run_id=run.id,
        employee_id=manager.id,
        actor=f"{manager.name} ({manager.title})",
        kind="run.planning",
        summary=f"is breaking down the brief for {project.name}",
    )
    ledger.append(
        db,
        company_id=company.id,
        project_id=project.id,
        kind="brief.accepted",
        actor_label=f"{manager.name} ({manager.title})",
        subject_kind="project",
        subject_id=project.id,
        payload={"brief": project.brief[:2000], "run_id": run.id},
    )
    db.commit()

    company_roles = roles.list_roles(db, company)
    role_keys = sorted({person.role_key for person in team} | {role.key for role in company_roles})
    kinds = packs.kinds_for(company)
    capabilities = sorted(
        {capability for role in company_roles for capability in (role.capabilities or [])}
        | {c for person in team for c in (person.capabilities or [])}
    ) or ["write_document"]

    plan = structured_call(
        [
            {
                "role": "system",
                "content": prompts.employee_system_prompt(company, manager, team, project),
            },
            {"role": "user", "content": prompts.planner_prompt(project, team, kinds, capabilities)},
        ],
        name="submit_plan",
        description="Submit the breakdown of this project into work items.",
        parameters=prompts.plan_schema(role_keys, kinds, capabilities),
        model=None,
    )

    raw_items = (plan.get("items") or plan.get("tickets") or [])[
        : get_settings().max_tickets_per_run
    ]
    raw_items = _break_cycles(raw_items)

    created: list[WorkItem] = []
    for index, item in enumerate(raw_items):
        capability = item.get("capability") or None
        role_key = item.get("role") or roles.match_role(
            db, company, f"{item.get('title', '')} {item.get('description', '')}"
        )
        assignee = roles.pick_for(
            db, company, team, capability=capability, role_key=role_key
        )
        kind = item.get("kind") if item.get("kind") in kinds else (kinds[0] if kinds else "task")

        project.ticket_counter += 1
        work_item = WorkItem(
            project_id=project.id,
            key=f"{project.key}-{project.ticket_counter}",
            title=str(item.get("title", "Untitled"))[:240],
            description=str(item.get("description", "")),
            kind=kind,
            status="todo",
            priority=item.get("priority", "medium"),
            assignee_id=assignee.id if assignee else None,
            reporter_id=manager.id,
            role_hint=role_key,
            capability_hint=capability,
            acceptance_criteria=[str(c) for c in item.get("acceptance_criteria", [])][:8],
            deliverable_spec=(
                {"artifact_kind": item["deliverable"]} if item.get("deliverable") else {}
            ),
            order=index,
        )
        db.add(work_item)
        db.flush()
        created.append(work_item)

    # Dependencies come back as positions; turn them into keys now that the keys exist.
    for index, item in enumerate(raw_items):
        positions = [
            position
            for position in (item.get("depends_on") or [])
            if isinstance(position, int) and 0 <= position < len(created) and position != index
        ]
        if positions:
            created[index].depends_on = [created[position].key for position in positions]
            db.add(created[index])

    for work_item in created:
        assignee = db.get(Employee, work_item.assignee_id) if work_item.assignee_id else None
        events.record(
            db,
            company_id=run.company_id,
            project_id=project.id,
            run_id=run.id,
            employee_id=manager.id,
            actor=f"{manager.name} ({manager.title})",
            kind="work_item.created",
            summary=(
                f"created {work_item.key}: {work_item.title}"
                f" → {assignee.name if assignee else 'unassigned'}"
            ),
            payload={"work_item_id": work_item.id, "key": work_item.key},
        )
        ledger.append(
            db,
            company_id=company.id,
            project_id=project.id,
            kind="item.assigned",
            actor_label=f"{manager.name} ({manager.title})",
            subject_kind="work_item",
            subject_id=work_item.id,
            payload={
                "key": work_item.key,
                "title": work_item.title,
                "assignee": assignee.name if assignee else None,
                "capability": work_item.capability_hint,
                "depends_on": work_item.depends_on,
            },
        )

    ledger.append(
        db,
        company_id=company.id,
        project_id=project.id,
        kind="plan.produced",
        actor_label=f"{manager.name} ({manager.title})",
        subject_kind="project",
        subject_id=project.id,
        payload={"items": [w.key for w in created], "run_id": run.id},
    )
    check_service.ensure_project_checks(db, company, project)
    _apply_deliverable_checks(db, company, project, created)

    project.status = "in_progress"
    db.add(project)
    _set_status(db, manager, "idle")
    db.commit()
    return created


def _break_cycles(items: list[dict]) -> list[dict]:
    """Drop dependency edges that would deadlock the board.

    A planner occasionally produces a cycle. Rejecting the whole plan and asking
    again costs a large model call; dropping the offending edges and recording it
    costs nothing and leaves work that can actually start.
    """
    edges = {
        index: {
            position
            for position in (item.get("depends_on") or [])
            if isinstance(position, int) and 0 <= position < len(items) and position != index
        }
        for index, item in enumerate(items)
    }
    order: list[int] = []
    permanent: set[int] = set()
    temporary: set[int] = set()
    removed: list[tuple[int, int]] = []

    def visit(node: int) -> None:
        if node in permanent:
            return
        temporary.add(node)
        for dependency in sorted(edges[node]):
            if dependency in temporary:
                removed.append((node, dependency))
                continue
            visit(dependency)
        temporary.discard(node)
        permanent.add(node)
        order.append(node)

    for index in range(len(items)):
        visit(index)

    for node, dependency in removed:
        edges[node].discard(dependency)
        log.warning("dropped circular dependency %s → %s from the plan", node, dependency)

    for index, item in enumerate(items):
        item["depends_on"] = sorted(edges[index])
    return items


def _apply_deliverable_checks(
    db: Session, company: Company, project: Project, items: list[WorkItem]
) -> None:
    """Bind the pack's checks for a deliverable kind to the item that produces it."""
    from models import Check

    kinds = {row.key: row for row in packs.artifact_kinds_for(db, company)}
    templates = {
        row.key: row
        for row in db.scalars(
            select(Check).where(
                Check.company_id == company.id,
                Check.project_id.is_(None),
                Check.work_item_id.is_(None),
            )
        )
    }
    for work_item in items:
        wanted = (work_item.deliverable_spec or {}).get("artifact_kind")
        kind = kinds.get(wanted) if wanted else None
        if not kind:
            continue
        for position, key in enumerate(kind.default_checks or []):
            template = templates.get(key)
            if not template:
                continue
            db.add(
                Check(
                    company_id=company.id,
                    project_id=project.id,
                    work_item_id=work_item.id,
                    key=template.key,
                    name=template.name,
                    kind=template.kind,
                    spec=dict(template.spec or {}),
                    required=template.required,
                    position=position,
                    created_by="Plan",
                )
            )
    db.flush()


# --------------------------------------------------------------------------
# doing one item
# --------------------------------------------------------------------------


def work_item_turn(
    db: Session, run: Run | None, project: Project, work_item: WorkItem, company: Company
) -> None:
    employee = db.get(Employee, work_item.assignee_id) if work_item.assignee_id else None
    if not employee:
        work_item.status = "blocked"
        work_item.blocked_reason = "Nobody is assigned to this."
        db.add(work_item)
        db.commit()
        return

    _set_status(db, employee, "working", f"{work_item.key}: {work_item.title}")
    work_item.status = "in_progress"
    db.add(work_item)
    events.record(
        db,
        company_id=company.id,
        project_id=project.id,
        run_id=run.id if run else None,
        employee_id=employee.id,
        actor=f"{employee.name} ({employee.title})",
        kind="work_item.started",
        summary=f"started {work_item.key}: {work_item.title}",
        payload={"work_item_id": work_item.id, "key": work_item.key},
    )
    db.commit()

    ctx = ToolContext(
        db=db,
        company=company,
        employee=employee,
        project=project,
        work_item=work_item,
        run=run,
    )
    outcome = runtime.run_turn(
        db, ctx, prompts.work_item_prompt(work_item, project), kind="work", purpose="work"
    )

    if outcome.hit_limit:
        db.add(
            WorkItemComment(
                work_item_id=work_item.id,
                author_id=employee.id,
                author_label=f"{employee.name} ({employee.title})",
                body=outcome.text,
            )
        )
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            run_id=run.id if run else None,
            employee_id=employee.id,
            actor=f"{employee.name} ({employee.title})",
            kind="work_item.step_limit",
            summary=f"ran out of tool calls on {work_item.key}",
            payload={"work_item_id": work_item.id, "key": work_item.key},
        )
        db.commit()

    _autocommit(db, run, project, work_item, employee, company)

    db.refresh(work_item)
    if work_item.status == "in_progress":
        work_item.status = "in_review"
    if not work_item.result:
        work_item.result = outcome.text[:2000]
    db.add(work_item)
    db.commit()

    verdict = verify(db, run, project, work_item, company, author=employee)
    if verdict and not verdict["ok"]:
        db.refresh(work_item)
        _reopen(db, work_item, company, project, run, verdict["summary"])

    _set_status(db, employee, "idle")
    db.commit()


def _reopen(
    db: Session,
    work_item: WorkItem,
    company: Company,
    project: Project,
    run: Run | None,
    reason: str,
) -> None:
    """Send an item back with the reason attached, not silently."""
    work_item.status = "blocked" if "waiting for a decision" in reason.lower() else "todo"
    work_item.rework_count += 1
    work_item.blocked_reason = reason[:2000] if work_item.status == "blocked" else None
    db.add(work_item)
    db.add(
        WorkItemComment(
            work_item_id=work_item.id,
            author_label="Verification",
            body=reason[:4000],
        )
    )
    events.record(
        db,
        company_id=company.id,
        project_id=project.id,
        run_id=run.id if run else None,
        actor="Verification",
        kind="work_item.reopened",
        summary=f"reopened {work_item.key}: {reason[:200]}",
        payload={"work_item_id": work_item.id, "key": work_item.key},
    )
    db.commit()


def _autocommit(
    db: Session,
    run: Run | None,
    project: Project,
    work_item: WorkItem,
    employee: Employee,
    company: Company,
) -> None:
    """Commit whatever the employee left behind.

    They are told to commit, and often do not. Uncommitted work is invisible in
    the history, so the platform commits it for them rather than losing the trail.
    """
    if "workspace" not in (employee.toolbelt or []):
        return
    try:
        space = workspace.for_project(company.slug, project.key)
        handle = employee.name.lower().replace(" ", ".")
        result = space.commit(
            f"{work_item.key}: {work_item.title}",
            (employee.name, f"{handle}@{company.slug}.eden"),
        )
    except Exception as exc:
        log.warning("auto-commit failed for %s: %s", work_item.key, exc)
        return

    if result.get("committed"):
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            run_id=run.id if run else None,
            employee_id=employee.id,
            actor=f"{employee.name} ({employee.title})",
            kind="code.commit",
            summary=f"committed {result['sha']}: {work_item.key} {work_item.title}"[:400],
            payload=result,
        )
        db.commit()


def verify(
    db: Session,
    run: Run | None,
    project: Project,
    work_item: WorkItem,
    company: Company,
    author: Employee | None = None,
) -> dict | None:
    """Run every check that applies, and attach the verdict to the item.

    This is the platform checking, not an employee reporting. Agents mark their
    own work done far too readily — a mobile app in one run was closed while
    `flutter pub get` could not even resolve its dependencies.
    """
    check_service.ensure_project_checks(db, company, project)
    results = check_service.run_for_work_item(
        db,
        company=company,
        project=project,
        work_item=work_item,
        author=author,
        run_id=run.id if run else None,
    )
    if not results:
        db.commit()
        return None

    verdict = check_service.verdict_for(results)
    body = "\n".join(f"[{result.status}] {result.detail}" for result in results)
    db.add(
        WorkItemComment(
            work_item_id=work_item.id, author_label="Verification", body=body[:8000]
        )
    )
    db.commit()
    return verdict


# --------------------------------------------------------------------------
# review
# --------------------------------------------------------------------------


def review_work_item(
    db: Session,
    run: Run | None,
    project: Project,
    work_item: WorkItem,
    company: Company,
    reviewer: Employee,
) -> None:
    _set_status(db, reviewer, "working", f"reviewing {work_item.key}")
    ctx = ToolContext(
        db=db,
        company=company,
        employee=reviewer,
        project=project,
        work_item=work_item,
        run=run,
    )
    criteria = (
        "\n".join(f"- {item}" for item in work_item.acceptance_criteria or [])
        or "- (none stated)"
    )
    item_block = (
        f"{work_item.key}: {work_item.title}\n"
        f"Description: {work_item.description}\n"
        f"Acceptance criteria:\n{criteria}"
    )
    latest = check_service.latest_for_work_item(db, work_item.id)
    check_block = (
        "\n".join(f"[{result.status}] {result.detail}" for result in latest)
        or "(no checks apply to this)"
    )
    prompt = prompts.REVIEW_PROMPT.format(
        item_block=item_block,
        result=work_item.result or "(nothing recorded)",
        check_block=check_block,
        artifact_block=context_builder.artifact_excerpts(db, work_item) or "(nothing produced)",
    )
    runtime.run_turn(db, ctx, prompt, kind="review", purpose="review")
    # Reviewers write too — a failing test they added is part of the record.
    _autocommit(db, run, project, work_item, reviewer, company)

    db.refresh(work_item)
    if work_item.status == "in_review":  # reviewer did not decide — accept it
        work_item.status = "done"
        db.add(work_item)
    db.commit()

    if work_item.status == "done":
        verdict = verify(db, run, project, work_item, company, author=reviewer)
        if verdict and not verdict["ok"]:
            db.refresh(work_item)
            _reopen(db, work_item, company, project, run, verdict["summary"])

    db.refresh(work_item)
    if work_item.status == "done":
        close_out(db, company, project, work_item, run)

    _set_status(db, reviewer, "idle")
    db.commit()


def close_out(
    db: Session, company: Company, project: Project, work_item: WorkItem, run: Run | None
) -> None:
    """Close an item: record it in the ledger and let its owner learn from it."""
    from datetime import UTC, datetime

    results = check_service.latest_for_work_item(db, work_item.id)
    verdict = check_service.verdict_for(results) if results else {"ok": True, "summary": ""}
    passed = bool(verdict["ok"])

    work_item.closed_at = datetime.now(UTC)
    db.add(work_item)
    ledger.append(
        db,
        company_id=company.id,
        project_id=project.id,
        kind="item.closed",
        actor_label="Platform",
        subject_kind="work_item",
        subject_id=work_item.id,
        payload={
            "key": work_item.key,
            "status": work_item.status,
            "checks_passed": passed,
            "rework_count": work_item.rework_count,
            "artifacts": [
                {"name": a.name, "hash": a.content_hash, "version": a.version}
                for a in artifact_service.for_project(db, project.id)
                if a.work_item_id == work_item.id
            ],
        },
    )
    db.commit()

    employee = db.get(Employee, work_item.assignee_id) if work_item.assignee_id else None
    if not employee:
        return

    outcome = "shipped" if passed else "rejected"
    if work_item.rework_count and passed:
        outcome = "reopened"
    try:
        report = reflect.reflect_on_work_item(
            db,
            company=company,
            employee=employee,
            work_item=work_item,
            project=project,
            passed=passed,
            outcome=outcome,
            check_summary=verdict.get("summary", ""),
            turn_summary=work_item.result or "",
        )
        reflect.consider_promotions(db, company)
        db.commit()
        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            employee_id=employee.id,
            actor=f"{employee.name} ({employee.title})",
            kind="memory.learned",
            summary=(
                f"recorded {report['stored']} memory item(s) from {work_item.key}"
                + (
                    " — the learning gate refused a procedure because the checks failed"
                    if report.get("gate") == "refused"
                    else ""
                )
            ),
            payload=report,
        )
        db.commit()
    except Exception:
        db.rollback()
        log.exception("reflection failed for %s", work_item.key)


# --------------------------------------------------------------------------
# wrap-up
# --------------------------------------------------------------------------


def wrap_up(
    db: Session, run: Run, project: Project, team: list[Employee], company: Company
) -> None:
    """Manager posts the outcome; the platform records what actually landed."""
    manager = roles.manager_of(db, team, company) or team[0]
    items = list(db.scalars(select(WorkItem).where(WorkItem.project_id == project.id)))
    done = [item for item in items if item.status == "done"]
    summary_lines = "\n".join(f"- {item.key} [{item.status}] {item.title}" for item in items)

    ctx = ToolContext(db=db, company=company, employee=manager, project=project, run=run)
    runtime.run_turn(
        db,
        ctx,
        f"""The team has finished working on {project.name}.

Outcomes:
{summary_lines}

Post one short wrap-up message to #general covering what shipped and anything
still open. Then stop.""",
        kind="wrap_up",
        purpose="chat",
        max_steps=4,
    )

    project.status = "delivered" if items and len(done) == len(items) else "in_progress"
    db.add(project)
    db.commit()


# --------------------------------------------------------------------------
# the work graph
# --------------------------------------------------------------------------


def ready_items(db: Session, project_id: str) -> list[WorkItem]:
    """Items nothing is blocking, in board order.

    `in_progress` counts as pending: a run interrupted mid-flight leaves items
    there, and the next pass has to pick them back up.
    """
    everything = list(
        db.scalars(
            select(WorkItem)
            .where(WorkItem.project_id == project_id)
            .order_by(WorkItem.order, WorkItem.key)
        )
    )
    by_key = {item.key: item for item in everything}
    ready = []
    for item in everything:
        if item.status not in OPEN_STATUSES:
            continue
        unmet = [
            key
            for key in (item.depends_on or [])
            if key in by_key and by_key[key].status != "done"
        ]
        if unmet:
            continue
        ready.append(item)
    return ready


def blocked_by_dependencies(db: Session, project_id: str) -> list[dict]:
    """Which items are waiting, and on what. Silence here used to be the bug."""
    everything = list(
        db.scalars(select(WorkItem).where(WorkItem.project_id == project_id))
    )
    by_key = {item.key: item for item in everything}
    waiting = []
    for item in everything:
        if item.status not in OPEN_STATUSES:
            continue
        unmet = [
            key
            for key in (item.depends_on or [])
            if key in by_key and by_key[key].status != "done"
        ]
        if unmet:
            waiting.append({"key": item.key, "title": item.title, "waiting_on": unmet})
    return waiting


def _count_done(db: Session, project_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(WorkItem)
            .where(WorkItem.project_id == project_id, WorkItem.status == "done")
        )
        or 0
    )


def _outcome_note(done: int, unfinished: list, blocked: list, truncated: int) -> str:
    """One sentence the dashboard can show about how the run ended."""
    parts = [f"{done} item{'s' if done != 1 else ''} finished"]
    if unfinished:
        keys = ", ".join(item.key for item in unfinished[:4])
        parts.append(f"{len(unfinished)} still open ({keys}) - run again to continue them")
    if blocked:
        parts.append(f"{len(blocked)} blocked, needs you")
    if truncated:
        parts.append(
            f"{truncated} turn{'s' if truncated != 1 else ''} ran out of tool calls "
            "(raise MAX_AGENT_STEPS or use smaller items)"
        )
    return "; ".join(parts) + "."


def _cancelled(db: Session, run_id: str) -> bool:
    db.expire_all()
    return db.scalar(select(Run.status).where(Run.id == run_id)) in {"cancelling", "cancelled"}


def _await_resume(db: Session, run_id: str) -> bool:
    """Block while a run is paused. Returns False if it was cancelled instead."""
    while True:
        db.expire_all()
        status = db.scalar(select(Run.status).where(Run.id == run_id))
        if status in {"cancelling", "cancelled"}:
            return False
        if status != "paused":
            return True
        time.sleep(1.5)


# --------------------------------------------------------------------------
# automated debugging
# --------------------------------------------------------------------------


def debug_until_green(
    project_id: str,
    command: str,
    cwd: str = "",
    max_attempts: int | None = None,
    label: str = "check",
) -> dict:
    """Run a check, hand the failure to an engineer, repeat until it passes.

    Stops early when an attempt leaves exactly the same errors behind: another
    identical attempt is not debugging, it is spending tokens.
    """
    attempts = max_attempts or autofix.MAX_ATTEMPTS
    db = session()
    history: list[dict] = []
    try:
        project = db.get(Project, project_id)
        if not project:
            return {"status": "failed", "error": "Project not found."}
        company = project.company

        check = autofix.run_check(project, company, command, cwd)
        if check.passed:
            events.record(
                db,
                company_id=company.id,
                project_id=project.id,
                actor="Auto-debug",
                kind="autofix.passed",
                summary=f"`{command}` already passes",
            )
            db.commit()
            return {"status": "passed", "attempts": 0, "history": history}

        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            actor="Auto-debug",
            kind="autofix.started",
            summary=f"{label} failed - starting automated debugging",
            payload={"command": command},
        )
        db.commit()

        previous_signature = check.signature()
        for attempt in range(1, attempts + 1):
            fixer = autofix.pick_fixer(db, company.id, check.output)
            if not fixer:
                return {"status": "failed", "error": "Nobody available to fix it."}

            work_item = autofix.ensure_bug_ticket(db, project, fixer, check)
            _set_status(db, fixer, "working", f"auto-debug {attempt}: {command}")
            events.record(
                db,
                company_id=company.id,
                project_id=project.id,
                employee_id=fixer.id,
                actor="Auto-debug",
                kind="autofix.attempt",
                summary=f"attempt {attempt}/{attempts}: {fixer.name} on `{command}`",
                payload={"attempt": attempt, "item": work_item.key},
            )
            db.commit()

            where = f" (run it with cwd={cwd})" if cwd else ""
            problems = "\n".join(check.errors())
            space = workspace.for_project(company.slug, project.key)
            snippets = check.snippets(space, cwd)
            ctx = ToolContext(
                db=db, company=company, employee=fixer, project=project, work_item=work_item
            )
            runtime.run_turn(
                db,
                ctx,
                f"""`{command}` is failing and you are fixing it.{where}

Reported problems:
{problems}

The code at those lines (> marks the reported line):
{snippets or "(could not read the source)"}

Fix the cause. Use edit_file with a snippet copied exactly from the code above —
you already have what you need, so do not spend calls grepping for it. After each
change run `{command}` yourself and keep going until it exits 0. Do not weaken the
check, delete tests, or stop while it still fails.""",
                kind="autofix",
                purpose="work",
            )
            _autocommit(db, None, project, work_item, fixer, company)
            _set_status(db, fixer, "idle")

            check = autofix.run_check(project, company, command, cwd)
            history.append({"attempt": attempt, "passed": check.passed, "by": fixer.name})

            if check.passed:
                work_item.status = "done"
                work_item.result = f"`{command}` passes."
                db.add(work_item)
                events.record(
                    db,
                    company_id=company.id,
                    project_id=project.id,
                    employee_id=fixer.id,
                    actor="Auto-debug",
                    kind="autofix.passed",
                    summary=f"`{command}` passes after {attempt} attempt(s)",
                    payload={"attempts": attempt},
                )
                db.commit()
                close_out(db, company, project, work_item, None)
                return {"status": "passed", "attempts": attempt, "history": history}

            signature = check.signature()
            if signature == previous_signature and attempt > 1:
                events.record(
                    db,
                    company_id=company.id,
                    project_id=project.id,
                    actor="Auto-debug",
                    kind="autofix.stalled",
                    summary=f"attempt {attempt} changed nothing - stopping",
                    payload={"command": command},
                )
                db.commit()
                return {"status": "stalled", "attempts": attempt, "history": history}
            previous_signature = signature

        events.record(
            db,
            company_id=company.id,
            project_id=project.id,
            actor="Auto-debug",
            kind="autofix.exhausted",
            summary=f"`{command}` still failing after {attempts} attempts",
        )
        db.commit()
        return {"status": "exhausted", "attempts": attempts, "history": history}
    except Exception as exc:
        log.exception("auto-debug failed")
        db.rollback()
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


# --------------------------------------------------------------------------
# run orchestration
# --------------------------------------------------------------------------


def execute_run(run_id: str) -> None:
    """Entry point for the background worker."""
    db = session()
    try:
        run = db.get(Run, run_id)
        if not run:
            return
        project = db.get(Project, run.project_id)
        company = project.company
        team = list(db.scalars(select(Employee).where(Employee.company_id == run.company_id)))
        if not team:
            run.status, run.error = "failed", "This company has no employees yet."
            db.add(run)
            db.commit()
            return
        if company.halted:
            run.status, run.error = "failed", f"{company.name} is halted."
            db.add(run)
            db.commit()
            return

        roles.ensure_roles(db, company)
        run.status, run.phase = "running", "planning"
        db.add(run)
        events.record(
            db,
            company_id=run.company_id,
            project_id=project.id,
            run_id=run.id,
            kind="run.started",
            summary=f"Run started for {project.name}",
        )
        db.commit()

        if not ready_items(db, project.id) and not blocked_by_dependencies(db, project.id):
            plan_run(db, run, project, team)

        run.phase = "execution"
        db.add(run)
        db.commit()

        reviewer = _pick_reviewer(db, company, team)
        stopped = False
        done_before = 0

        # Several passes: work the checks rejected comes back as `todo`, and the
        # person who owns it deserves the comments before the run ends. A pass
        # that finishes nothing ends the run — another identical pass would only
        # burn tokens.
        for cycle in range(get_settings().max_run_passes):
            pending = ready_items(db, project.id)
            if not pending or stopped:
                break
            done_before = _count_done(db, project.id)

            for work_item in pending:
                if not _await_resume(db, run_id) or _cancelled(db, run_id):
                    stopped = True
                    break
                db.refresh(work_item)
                if work_item.status in {"done", "in_review", "blocked"}:
                    continue
                work_item_turn(db, run, project, work_item, company)

                if reviewer and reviewer.id != work_item.assignee_id:
                    db.refresh(work_item)
                    if work_item.status == "in_review":
                        if not _await_resume(db, run_id) or _cancelled(db, run_id):
                            stopped = True
                            break
                        review_work_item(db, run, project, work_item, company, reviewer)

            if cycle and _count_done(db, project.id) == done_before:
                log.info("pass %s finished nothing new - ending the run", cycle)
                break

        if _cancelled(db, run_id):
            run.status, run.phase = "cancelled", "cancelled"
        else:
            run.phase = "wrap_up"
            db.add(run)
            db.commit()
            wrap_up(db, run, project, team, company)
            # "Completed" has to mean something finished. A run that planned six
            # items, finished none of them and produced no deliverable is not a
            # completed run — reporting it as one is the exact failure this
            # product exists to prevent, committed by the product itself.
            run.status, run.phase = _closing_status(db, project), "done"

        _record_stats(db, run, project)
    except Exception as exc:  # keep the failure visible in the UI
        log.exception("run %s failed", run_id)
        db.rollback()
        run = db.get(Run, run_id)
        if run:
            run.status, run.error = "failed", str(exc)[:2000]
            db.add(run)
            events.record(
                db,
                company_id=run.company_id,
                project_id=run.project_id,
                run_id=run.id,
                kind="run.failed",
                summary=f"Run failed: {exc}"[:400],
            )
            db.commit()
    finally:
        db.close()


def _pick_reviewer(db: Session, company: Company, team: list[Employee]) -> Employee | None:
    """Whoever reviews here. Not always a QA engineer — a law firm has a partner."""
    return roles.pick_for(db, company, team, capability="review")


def _closing_status(db: Session, project: Project) -> str:
    """`completed` only when the run actually finished something.

    `stalled` is not a failure — nothing broke, and running again may well make
    progress. It is the honest word for "it stopped without getting anywhere",
    and it is what stops the dashboard showing a green tick over an empty
    project.
    """
    items = list(db.scalars(select(WorkItem).where(WorkItem.project_id == project.id)))
    if not items:
        return "stalled"
    if any(item.status == "done" for item in items):
        return "completed"
    return "stalled"


def _record_stats(db: Session, run: Run, project: Project) -> None:
    finished = list(db.scalars(select(WorkItem).where(WorkItem.project_id == project.id)))
    done = [item for item in finished if item.status == "done"]
    unfinished = [item for item in finished if item.status in OPEN_STATUSES]
    blocked = [item for item in finished if item.status == "blocked"]
    truncated = db.scalar(
        select(func.count())
        .select_from(RunStep)
        .where(RunStep.run_id == run.id, RunStep.status == "step_limit")
    )
    run.stats = {
        "items": len(finished),
        "tickets": len(finished),
        "done": len(done),
        "blocked": len(blocked),
        "unfinished": len(unfinished),
        "step_limited": truncated or 0,
        "waiting_on_dependencies": blocked_by_dependencies(db, project.id),
        "note": _outcome_note(len(done), unfinished, blocked, truncated or 0),
    }
    db.add(run)
    events.record(
        db,
        company_id=run.company_id,
        project_id=project.id,
        run_id=run.id,
        kind=f"run.{run.status}",
        summary=f"Run {run.status}: {run.stats['done']}/{run.stats['items']} items done",
        payload=run.stats,
    )
    db.commit()


def start(run_id: str) -> None:
    get_executor().submit(execute_run, run_id)
