"""Registering deliverables, whatever shape they take.

An artifact is the thing a check runs against and the thing the ledger commits
to. Files in a git workspace are artifacts stored as `git`; a contract draft or a
research memo is stored as `blob`. Either way the row carries a content hash, so
"was this really the version that passed?" has an answer.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import Artifact, ArtifactKind, Company, Employee, Project

from . import blobs, events, ledger, workspace

log = logging.getLogger(__name__)

MAX_INLINE_PREVIEW = 4000


def kind_for(db: Session, company: Company, key: str) -> ArtifactKind | None:
    return db.scalar(
        select(ArtifactKind).where(ArtifactKind.company_id == company.id, ArtifactKind.key == key)
    )


def latest(db: Session, project_id: str, name: str) -> Artifact | None:
    return db.scalar(
        select(Artifact)
        .where(Artifact.project_id == project_id, Artifact.name == name)
        .order_by(Artifact.version.desc())
        .limit(1)
    )


def record(
    db: Session,
    *,
    company: Company,
    project: Project,
    name: str,
    kind: str = "file",
    content: str | None = None,
    storage: str | None = None,
    locator: str | None = None,
    title: str | None = None,
    work_item_id: str | None = None,
    produced_by: Employee | None = None,
    meta: dict | None = None,
    content_hash: str | None = None,
) -> Artifact:
    """Register a new version of a deliverable.

    Re-recording identical content is a no-op that returns the existing row:
    agents rewrite the same file often, and a version history full of
    no-change versions makes the real changes hard to find.
    """
    declared = dict(meta or {})
    kind_row = kind_for(db, company, kind)
    storage = storage or (kind_row.storage if kind_row else "blob")

    if content is not None:
        content_hash = blobs.hash_text(content)
        if storage == "blob":
            locator = blobs.put_text(content)
        size_bytes = len(content.encode())
    else:
        size_bytes = declared.pop("size_bytes", 0)
    if not content_hash:
        raise ValueError("An artifact needs either content or a content hash.")

    previous = latest(db, project.id, name)
    if previous and previous.content_hash == content_hash:
        return previous

    version = (previous.version + 1) if previous else 1
    artifact = Artifact(
        company_id=company.id,
        project_id=project.id,
        work_item_id=work_item_id,
        kind=kind,
        name=name[:300],
        title=(title or name)[:300],
        storage=storage,
        locator=(locator or name)[:500],
        version=version,
        content_hash=content_hash,
        size_bytes=size_bytes,
        produced_by=produced_by.id if produced_by else None,
        meta=declared,
    )
    db.add(artifact)
    db.flush()

    if previous:
        previous.superseded_by = artifact.id
        db.add(previous)

    ledger.append(
        db,
        company_id=company.id,
        project_id=project.id,
        kind="artifact.version",
        actor_id=produced_by.id if produced_by else None,
        actor_label=f"{produced_by.name} ({produced_by.title})" if produced_by else "System",
        subject_kind="artifact",
        subject_id=artifact.id,
        payload={
            "name": artifact.name,
            "kind": artifact.kind,
            "version": version,
            "content_hash": content_hash,
            "storage": storage,
            "work_item_id": work_item_id,
        },
    )
    events.record(
        db,
        company_id=company.id,
        project_id=project.id,
        employee_id=produced_by.id if produced_by else None,
        actor=f"{produced_by.name} ({produced_by.title})" if produced_by else "System",
        kind="artifact.recorded",
        summary=f"{'updated' if previous else 'produced'} {artifact.name} (v{version})",
        payload={"artifact_id": artifact.id, "kind": kind, "version": version},
    )
    return artifact


def read(db: Session, artifact: Artifact) -> str:
    """The artifact's current bytes, from wherever they live."""
    if artifact.storage == "blob":
        try:
            return blobs.get_text(artifact.locator)
        except FileNotFoundError:
            return ""
    if artifact.storage == "git":
        project = db.get(Project, artifact.project_id)
        company = db.get(Company, artifact.company_id)
        if not project or not company:
            return ""
        try:
            return workspace.for_project(company.slug, project.key).read(artifact.locator)
        except Exception:
            return ""
    return ""


def verify_content_hash(db: Session, artifact: Artifact) -> dict:
    """Do the stored bytes still hash to what the ledger recorded?

    For a git artifact this can legitimately differ: the file has moved on since
    that version. The answer distinguishes "changed" from "gone".
    """
    body = read(db, artifact)
    if not body:
        return {"artifact_id": artifact.id, "state": "missing", "expected": artifact.content_hash}
    actual = blobs.hash_text(body)
    return {
        "artifact_id": artifact.id,
        "state": "intact" if actual == artifact.content_hash else "changed",
        "expected": artifact.content_hash,
        "actual": actual,
    }


def record_workspace_file(
    db: Session,
    *,
    company: Company,
    project: Project,
    path: str,
    work_item_id: str | None = None,
    produced_by: Employee | None = None,
    kind: str = "source_file",
) -> Artifact | None:
    """Register a file an employee wrote into the git workspace."""
    space = workspace.for_project(company.slug, project.key)
    try:
        body = space.read(path)
    except Exception as exc:
        log.debug("could not register %s as an artifact: %s", path, exc)
        return None
    return record(
        db,
        company=company,
        project=project,
        name=path,
        kind=kind,
        content=body,
        storage="git",
        locator=path,
        work_item_id=work_item_id,
        produced_by=produced_by,
    )


def for_project(db: Session, project_id: str, current_only: bool = True) -> list[Artifact]:
    query = select(Artifact).where(Artifact.project_id == project_id)
    if current_only:
        query = query.where(Artifact.superseded_by.is_(None))
    return list(db.scalars(query.order_by(Artifact.updated_at.desc())))


def counts_by_kind(db: Session, project_id: str) -> dict[str, int]:
    rows = db.execute(
        select(Artifact.kind, func.count())
        .where(Artifact.project_id == project_id, Artifact.superseded_by.is_(None))
        .group_by(Artifact.kind)
    ).all()
    return {kind: count for kind, count in rows}


def excerpt(db: Session, artifact: Artifact, limit: int = MAX_INLINE_PREVIEW) -> str:
    body = read(db, artifact)
    if len(body) <= limit:
        return body
    return body[:limit] + f"\n… [{len(body) - limit} more characters]"


def touch(artifact: Artifact) -> None:
    artifact.updated_at = datetime.now(UTC)
