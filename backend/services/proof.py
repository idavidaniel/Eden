"""Re-proving finished work.

The ledger says a check passed against an artifact with a particular hash. This
module goes back and tests that claim: it recomputes the chain, re-hashes every
artifact the chain committed to, and re-runs the checks that can be re-run —
`command`, `schema`, `assertion` and `citation` are all deterministic, so a
result that was true then should be true now.

What makes this more than an audit log is the re-running. An audit log records
that somebody said a test passed. This runs the test again.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Artifact, Check, CheckResult, Employee, LedgerEntry, Project, WorkItem
from models.base import dumps
from models.work import CHECK_KINDS

from . import artifacts as artifact_service
from . import blobs, ledger
from . import checks as check_service

log = logging.getLogger(__name__)

# Kinds whose verdict depends only on the artifact and the spec.
DETERMINISTIC = {"command", "schema", "assertion", "citation"}
# Kinds that need a model or a person, and so cannot be replayed for free.
NOT_REPLAYABLE = set(CHECK_KINDS) - DETERMINISTIC


def reverify(db: Session, project: Project, rerun_checks: bool = True) -> dict:
    """Re-prove a project: chain, artifact hashes, and the checks themselves."""
    company = project.company
    chain = ledger.verify_chain(db, company.id)

    artifacts = list(
        db.scalars(select(Artifact).where(Artifact.project_id == project.id))
    )
    integrity = [artifact_service.verify_content_hash(db, row) for row in artifacts]
    committed = _committed_hashes(db, company.id, project.id)
    unrecorded = [
        row.id
        for row in artifacts
        if row.content_hash not in committed and row.superseded_by is None
    ]

    replayed: list[dict] = []
    skipped: list[dict] = []
    if rerun_checks:
        replayed, skipped = _replay(db, project)

    disagreements = [row for row in replayed if row["then"] != row["now"]]
    changed = [row for row in integrity if row["state"] != "intact"]

    return {
        "project": {"id": project.id, "key": project.key, "name": project.name},
        "checked_at": datetime.now(UTC).isoformat(),
        "chain": chain,
        "artifacts": {
            "total": len(artifacts),
            "intact": len([row for row in integrity if row["state"] == "intact"]),
            "changed": [row for row in integrity if row["state"] == "changed"],
            "missing": [row for row in integrity if row["state"] == "missing"],
            "not_in_ledger": unrecorded,
        },
        "checks": {
            "replayed": replayed,
            "skipped": skipped,
            "disagreements": disagreements,
        },
        "proved": bool(
            chain["intact"] and not disagreements and not unrecorded and not changed
        ),
        "note": _verdict_note(chain, disagreements, changed, unrecorded, skipped),
    }


def _verdict_note(
    chain: dict, disagreements: list, changed: list, unrecorded: list, skipped: list
) -> str:
    if not chain["intact"]:
        return "The record itself has been altered — see chain.problems."
    parts = []
    if changed:
        parts.append(
            f"{len(changed)} artifact(s) no longer match the version the ledger recorded"
        )
    if unrecorded:
        parts.append(f"{len(unrecorded)} artifact(s) were never committed to the chain")
    if disagreements:
        parts.append(f"{len(disagreements)} check(s) no longer agree with their recorded verdict")
    if not parts:
        note = "Everything the record claims still holds."
        if skipped:
            note += (
                f" {len(skipped)} check(s) could not be replayed automatically "
                "(a rubric or a human decision) and are reported as recorded."
            )
        return note
    return "; ".join(parts) + "."


def _committed_hashes(db: Session, company_id: str, project_id: str) -> set[str]:
    hashes: set[str] = set()
    for entry in db.scalars(
        select(LedgerEntry).where(
            LedgerEntry.company_id == company_id,
            LedgerEntry.project_id == project_id,
            LedgerEntry.kind == "artifact.version",
        )
    ):
        content_hash = (entry.payload or {}).get("content_hash")
        if content_hash:
            hashes.add(content_hash)
    return hashes


def _replay(db: Session, project: Project) -> tuple[list[dict], list[dict]]:
    """Run every deterministic check again and compare with what was recorded."""
    company = project.company
    recorded = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.project_id == project.id)
            .order_by(CheckResult.created_at.desc())
        )
    )
    seen: set[str] = set()
    replayed: list[dict] = []
    skipped: list[dict] = []

    for result in recorded:
        marker = f"{result.check_id}:{result.work_item_id}:{result.artifact_id}"
        if marker in seen or not result.check_id:
            continue
        seen.add(marker)

        check = db.get(Check, result.check_id)
        if not check:
            skipped.append(
                {
                    "check_key": result.check_key,
                    "then": result.status,
                    "reason": "the check itself has been deleted",
                }
            )
            continue
        if check.kind not in DETERMINISTIC:
            skipped.append(
                {
                    "check_key": check.key,
                    "kind": check.kind,
                    "then": result.status,
                    "reason": (
                        "a rubric needs a model and a human check needs a person; neither "
                        "can be replayed without spending something"
                    ),
                }
            )
            continue

        work_item = db.get(WorkItem, result.work_item_id) if result.work_item_id else None
        artifact = db.get(Artifact, result.artifact_id) if result.artifact_id else None
        author = (
            db.get(Employee, work_item.assignee_id)
            if work_item and work_item.assignee_id
            else None
        )
        fresh = check_service.run_one(
            db,
            check,
            company=company,
            project=project,
            work_item=work_item,
            artifact=artifact,
            author=author,
        )
        replayed.append(
            {
                "check_key": check.key,
                "kind": check.kind,
                "work_item": work_item.key if work_item else None,
                "artifact": artifact.name if artifact else None,
                "artifact_hash": artifact.content_hash if artifact else None,
                "then": result.status,
                "now": fresh.status,
                "recorded_at": result.created_at.isoformat() if result.created_at else None,
                "detail": fresh.detail[:400],
            }
        )
    return replayed, skipped


def work_record(db: Session, project: Project) -> dict:
    """An exportable account of a project: brief, work, deliverables, proof.

    Self-contained on purpose. Hand it to a client or an auditor and they can
    check the chain themselves without access to this database.
    """
    company = project.company
    entries = ledger.chain(db, company.id, project.id)
    items = list(
        db.scalars(
            select(WorkItem)
            .where(WorkItem.project_id == project.id)
            .order_by(WorkItem.order, WorkItem.key)
        )
    )
    artifacts = list(
        db.scalars(
            select(Artifact).where(
                Artifact.project_id == project.id, Artifact.superseded_by.is_(None)
            )
        )
    )
    people = {
        person.id: {"name": person.name, "title": person.title}
        for person in db.scalars(select(Employee).where(Employee.company_id == company.id))
    }

    record = {
        "format": "eden.work-record/1",
        "generated_at": datetime.now(UTC).isoformat(),
        "company": {"id": company.id, "name": company.name, "industry": company.industry},
        "project": {
            "id": project.id,
            "key": project.key,
            "name": project.name,
            "brief": project.brief,
            "status": project.status,
        },
        "people": people,
        "work_items": [
            {
                "key": item.key,
                "title": item.title,
                "kind": item.kind,
                "status": item.status,
                "assignee": people.get(item.assignee_id, {}).get("name"),
                "acceptance_criteria": item.acceptance_criteria or [],
                "rework_count": item.rework_count,
                "closed_at": item.closed_at.isoformat() if item.closed_at else None,
                "checks": [
                    {
                        "key": result.check_key,
                        "kind": result.check_kind,
                        "status": result.status,
                        "score": result.score,
                        "detail": result.detail[:600],
                        "at": result.created_at.isoformat() if result.created_at else None,
                    }
                    for result in check_service.latest_for_work_item(db, item.id)
                ],
            }
            for item in items
        ],
        "artifacts": [
            {
                "name": row.name,
                "kind": row.kind,
                "version": row.version,
                "content_hash": row.content_hash,
                "size_bytes": row.size_bytes,
                "produced_by": people.get(row.produced_by, {}).get("name"),
            }
            for row in artifacts
        ],
        "ledger": [
            {
                "height": entry.height,
                "prev_hash": entry.prev_hash,
                "hash": entry.hash,
                "kind": entry.kind,
                "actor": entry.actor_label,
                "subject": {"kind": entry.subject_kind, "id": entry.subject_id},
                "payload": entry.payload or {},
                "at": entry.at.isoformat() if entry.at else None,
            }
            for entry in entries
        ],
        "how_to_verify": (
            "Each ledger entry's hash is sha256(prev_hash + canonical_json(body)), where "
            "body is {company_id, project_id, height, kind, actor_id, actor_label, "
            "subject_kind, subject_id, payload, at} with sorted keys and no whitespace. "
            "Recompute from height 0; every hash must match and every prev_hash must equal "
            "the previous entry's hash. Artifact bytes hash to content_hash with plain sha256."
        ),
    }
    record["record_hash"] = blobs.hash_text(dumps(record))
    return record
