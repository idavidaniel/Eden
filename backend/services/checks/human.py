"""A gate that only a person can open.

Returns `pending`, not `pass`. Work waiting on a signature is not finished work,
and the difference has to survive into the record.
"""

from sqlalchemy import select

from models import Approval, Check

from .base import CheckContext, Verdict


def run(check: Check, ctx: CheckContext) -> Verdict:
    spec = check.spec or {}
    existing = ctx.db.scalar(
        select(Approval).where(
            Approval.company_id == ctx.company.id,
            Approval.subject_kind == "check",
            Approval.subject_id == check.id,
            Approval.work_item_id == (ctx.work_item.id if ctx.work_item else None),
        )
    )

    if existing and existing.status == "approved":
        return Verdict(
            status="pass",
            detail=f"{check.name}: approved by {existing.decided_by}.",
            evidence={"approval_id": existing.id, "decided_by": existing.decided_by},
        )
    if existing and existing.status == "rejected":
        return Verdict(
            status="fail",
            detail=f"{check.name}: rejected by {existing.decided_by}. {existing.note}".strip(),
            evidence={"approval_id": existing.id, "note": existing.note},
        )

    if not existing:
        existing = Approval(
            company_id=ctx.company.id,
            project_id=ctx.project.id if ctx.project else None,
            work_item_id=ctx.work_item.id if ctx.work_item else None,
            subject_kind="check",
            subject_id=check.id,
            requested_by=ctx.author.id if ctx.author else None,
            requested_label=(
                f"{ctx.author.name} ({ctx.author.title})" if ctx.author else "The platform"
            ),
            title=check.name,
            reason=spec.get("reason", "This check requires a person to decide."),
            capability=spec.get("capability"),
            payload={
                "check_key": check.key,
                "artifact_id": ctx.artifact.id if ctx.artifact else None,
                "work_item_key": ctx.work_item.key if ctx.work_item else None,
            },
        )
        ctx.db.add(existing)
        ctx.db.flush()

    return Verdict(
        status="pending",
        detail=f"{check.name}: waiting for a decision.",
        evidence={"approval_id": existing.id, "capability": existing.capability},
    )
