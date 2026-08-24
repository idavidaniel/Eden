"""Append to and verify the hash-chained work ledger.

`append()` is the only writer. It takes a per-company lock so two workers cannot
fork the chain, computes `sha256(prev_hash || canonical_json(body))`, and stores
the height so a gap is detectable even if a row is deleted outright.
"""

import hashlib
import threading
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import LedgerEntry
from models.base import dumps
from models.ledger import GENESIS_HASH

_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(company_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks[company_id]


def entry_hash(prev_hash: str, body: dict) -> str:
    return hashlib.sha256((prev_hash + dumps(body)).encode()).hexdigest()


def _stamp(at: datetime | None) -> str | None:
    """A timestamp that hashes the same however the driver handed it back.

    `isoformat()` is not safe here: SQLite returns a naive datetime and Postgres
    an aware one, so the same entry would hash two different ways depending on
    the backend. Everything is normalised to UTC and formatted explicitly.
    """
    if at is None:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def body_of(entry: LedgerEntry) -> dict:
    """The exact bytes the hash commits to. Order matters; keep it stable."""
    return {
        "company_id": entry.company_id,
        "project_id": entry.project_id,
        "height": entry.height,
        "kind": entry.kind,
        "actor_id": entry.actor_id,
        "actor_label": entry.actor_label,
        "subject_kind": entry.subject_kind,
        "subject_id": entry.subject_id,
        "payload": entry.payload or {},
        "at": _stamp(entry.at),
    }


def append(
    db: Session,
    *,
    company_id: str,
    kind: str,
    payload: dict | None = None,
    project_id: str | None = None,
    actor_id: str | None = None,
    actor_label: str = "System",
    subject_kind: str | None = None,
    subject_id: str | None = None,
) -> LedgerEntry:
    with _lock_for(company_id):
        if db.bind and db.bind.dialect.name == "postgresql":
            # Survives more than one API process writing the same chain.
            db.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(company_id))),
            )
        tip = db.scalar(
            select(LedgerEntry)
            .where(LedgerEntry.company_id == company_id)
            .order_by(LedgerEntry.height.desc())
            .limit(1)
        )
        entry = LedgerEntry(
            company_id=company_id,
            project_id=project_id,
            height=(tip.height + 1) if tip else 0,
            prev_hash=tip.hash if tip else GENESIS_HASH,
            kind=kind,
            actor_id=actor_id,
            actor_label=actor_label[:160],
            subject_kind=subject_kind,
            subject_id=subject_id,
            payload=payload or {},
            at=datetime.now(UTC),
        )
        entry.hash = entry_hash(entry.prev_hash, body_of(entry))
        db.add(entry)
        db.flush()
        return entry


def chain(db: Session, company_id: str, project_id: str | None = None) -> list[LedgerEntry]:
    query = (
        select(LedgerEntry)
        .where(LedgerEntry.company_id == company_id)
        .order_by(LedgerEntry.height)
    )
    if project_id:
        query = query.where(LedgerEntry.project_id == project_id)
    return list(db.scalars(query))


def verify_chain(db: Session, company_id: str) -> dict:
    """Recompute every hash in a company's chain.

    Reports the first break rather than a boolean, because "which entry" is the
    only useful answer when a chain fails.
    """
    entries = chain(db, company_id)
    problems: list[dict] = []
    expected_prev = GENESIS_HASH

    for index, entry in enumerate(entries):
        if entry.height != index:
            problems.append(
                {
                    "height": entry.height,
                    "hash": entry.hash,
                    "problem": (
                        f"height {entry.height} sits at position {index} — a row is missing"
                    ),
                }
            )
        if entry.prev_hash != expected_prev:
            problems.append(
                {
                    "height": entry.height,
                    "hash": entry.hash,
                    "problem": "prev_hash does not match the entry before it",
                }
            )
        recomputed = entry_hash(entry.prev_hash, body_of(entry))
        if recomputed != entry.hash:
            problems.append(
                {
                    "height": entry.height,
                    "hash": entry.hash,
                    "problem": "contents were changed after the entry was written",
                    "recomputed": recomputed,
                }
            )
        expected_prev = entry.hash

    return {
        "company_id": company_id,
        "entries": len(entries),
        "intact": not problems,
        "problems": problems,
        "tip": entries[-1].hash if entries else GENESIS_HASH,
    }
