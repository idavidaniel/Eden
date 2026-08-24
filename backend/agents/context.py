"""Choosing what goes into a turn.

The working model takes at least 400,000 tokens of context, so this is not a
compression problem — we could put everything in. It is a curation problem.
400k tokens costs about eighteen seconds of prefill and real money on every
single turn, and context that is not relevant measurably degrades tool-calling.
So the target is roughly 24,000 tokens, and the engineering goes into choosing
*which* 24,000 and into being able to say afterwards why each piece was there.

Every tier reports what it contributed, and the report is stored on the step, so
"why did the agent think that?" is answerable after the fact.
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    Artifact,
    Channel,
    Check,
    CheckResult,
    Company,
    Document,
    Employee,
    Message,
    Project,
    WorkItem,
)
from services import artifacts as artifact_service
from services import inbox, memory, roles, workspace

log = logging.getLogger(__name__)

# Roughly four characters to a token. Budgets are in characters because that is
# what we can measure without paying for a tokeniser round trip.
CHARS_PER_TOKEN = 4
BUDGETS = {
    "blocks": 2_500 * CHARS_PER_TOKEN,
    "work": 2_000 * CHARS_PER_TOKEN,
    "facts": 4_000 * CHARS_PER_TOKEN,
    "procedures": 3_000 * CHARS_PER_TOKEN,
    "episodes": 3_000 * CHARS_PER_TOKEN,
    "situation": 9_000 * CHARS_PER_TOKEN,
}
COUNTS = {"facts": 8, "procedures": 3, "episodes": 5}


@dataclass
class Assembled:
    """The pieces of a turn's context, and an account of where they came from."""

    blocks: str = ""
    work: str = ""
    facts: str = ""
    procedures: str = ""
    episodes: str = ""
    situation: str = ""
    used_memories: list = field(default_factory=list)
    report: dict = field(default_factory=dict)

    def as_prompt(self) -> str:
        sections = [
            ("What you know about yourself and this company", self.blocks),
            ("The work", self.work),
            ("What you have learned that is relevant", self.facts),
            ("How you have done this before", self.procedures),
            ("How similar work turned out", self.episodes),
            ("Where things stand right now", self.situation),
        ]
        return "\n\n".join(
            f"## {title}\n{body.strip()}" for title, body in sections if body.strip()
        )


def _trim(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n… [trimmed]", True


def assemble(
    db: Session,
    *,
    company: Company,
    employee: Employee,
    project: Project | None = None,
    work_item: WorkItem | None = None,
    query: str = "",
    include_situation: bool = True,
) -> Assembled:
    result = Assembled()
    report: dict = {}
    lookup = query or _query_from(work_item, project)

    # Tier 0 — always present. The agent's own idea of who it is.
    blocks, trimmed = _trim(memory.blocks_text(db, employee), BUDGETS["blocks"])
    result.blocks = blocks
    report["blocks"] = {"chars": len(blocks), "trimmed": trimmed}

    # Tier 1 — the work, and the last verdict on it, verbatim. A summary of a
    # failing check is the one thing that must never be paraphrased.
    if work_item:
        work, trimmed = _trim(_work_block(db, work_item, project), BUDGETS["work"])
        result.work = work
        report["work"] = {"chars": len(work), "trimmed": trimmed, "key": work_item.key}

    # Tiers 2–4 — retrieved memory.
    #
    # Switchable per company, because "memory helps" is a claim rather than an
    # assumption. The eval harness runs the same briefs with this off and
    # reports whether the numbers actually move; the switch has to be real for
    # that comparison to mean anything.
    remembers = (company.settings or {}).get("memory_enabled", True)
    for tier, kinds in (
        ("facts", ["fact"]),
        ("procedures", ["procedure"]),
        ("episodes", ["episode"]),
    ):
        if not remembers:
            report[tier] = {"count": 0, "mode": "off", "chars": 0, "trimmed": False, "titles": []}
            continue
        hits, mode = memory.search(
            db,
            company.id,
            lookup,
            employee_id=employee.id,
            kinds=kinds,
            limit=COUNTS[tier],
        )
        rendered, trimmed = _trim(_render_memories(hits), BUDGETS[tier])
        setattr(result, tier, rendered)
        result.used_memories.extend(hit.memory for hit in hits)
        report[tier] = {
            "count": len(hits),
            "mode": mode,
            "chars": len(rendered),
            "trimmed": trimmed,
            "titles": [hit.memory.title for hit in hits],
        }

    # Tier 5 — the world as it is now.
    if include_situation:
        situation, trimmed = _trim(
            _situation(db, company, employee, project, work_item), BUDGETS["situation"]
        )
        result.situation = situation
        report["situation"] = {"chars": len(situation), "trimmed": trimmed}

    total = sum(section.get("chars", 0) for section in report.values())
    report["total_chars"] = total
    report["estimated_tokens"] = total // CHARS_PER_TOKEN
    result.report = report
    return result


def _query_from(work_item: WorkItem | None, project: Project | None) -> str:
    parts = []
    if work_item:
        parts += [work_item.title, work_item.description or "", work_item.kind]
    if project:
        parts += [project.name, project.brief or ""]
    return " ".join(part for part in parts if part)[:2000]


def _work_block(db: Session, work_item: WorkItem, project: Project | None) -> str:
    criteria = (
        "\n".join(f"- {item}" for item in work_item.acceptance_criteria or [])
        or "- (none stated)"
    )
    lines = [
        f"{work_item.key} [{work_item.kind}, priority {work_item.priority}]",
        f"Title: {work_item.title}",
        f"Description: {work_item.description or '(none)'}",
        f"Acceptance criteria:\n{criteria}",
    ]
    if work_item.depends_on:
        lines.append(f"Depends on: {', '.join(work_item.depends_on)}")
    if work_item.deliverable_spec:
        wanted = work_item.deliverable_spec.get("artifact_kind")
        if wanted:
            lines.append(f"Expected deliverable: one artifact of kind '{wanted}'.")
    if work_item.blocked_reason:
        lines.append(f"Blocked because: {work_item.blocked_reason}")
    if work_item.rework_count:
        lines.append(
            f"This has come back {work_item.rework_count} time(s). "
            "Read the last verdict before doing anything else."
        )

    checks = _checks_block(db, work_item, project)
    if checks:
        lines.append(checks)
    verdicts = _last_verdicts(db, work_item)
    if verdicts:
        lines.append(verdicts)
    return "\n".join(lines)


def _checks_block(db: Session, work_item: WorkItem, project: Project | None) -> str:
    rows = list(
        db.scalars(
            select(Check).where(
                Check.company_id == work_item.project.company_id,
                Check.enabled.is_(True),
            )
        )
    )
    relevant = [
        check
        for check in rows
        if check.work_item_id == work_item.id
        or (project and check.project_id == project.id)
        or check.artifact_kind
    ]
    if not relevant:
        return ""
    lines = [
        f"- {check.name} ({check.kind}{', required' if check.required else ''})"
        for check in relevant[:12]
    ]
    return (
        "Checks the platform will run on this, whatever you or a reviewer say:\n"
        + "\n".join(lines)
    )


def _last_verdicts(db: Session, work_item: WorkItem) -> str:
    rows = list(
        db.scalars(
            select(CheckResult)
            .where(CheckResult.work_item_id == work_item.id)
            .order_by(CheckResult.created_at.desc())
            .limit(4)
        )
    )
    if not rows:
        return ""
    lines = []
    for row in rows:
        detail = row.detail
        output = (row.evidence or {}).get("output")
        if output:
            detail = f"{detail}\n{output[-1200:]}"
        lines.append(f"[{row.status}] {detail}")
    return "Last verdicts, in full:\n" + "\n".join(lines)


def _render_memories(hits) -> str:
    if not hits:
        return ""
    lines = []
    for hit in hits:
        item = hit.memory
        marker = f"{item.kind}"
        if item.outcome and item.outcome != "neutral":
            marker += f", {item.outcome}"
        if item.superseded_by:
            marker += ", SUPERSEDED — treat with suspicion"
        line = f"- [{marker}] {item.title}"
        if item.body:
            line += f"\n    {item.body[:600]}"
        lines.append(line)
    return "\n".join(lines)


def _situation(
    db: Session,
    company: Company,
    employee: Employee,
    project: Project | None,
    work_item: WorkItem | None,
) -> str:
    parts = []

    messages = inbox.unread(db, employee.id, limit=5)
    if messages:
        parts.append(
            "Waiting in your inbox:\n"
            + "\n".join(
                f"- [{m.kind}] {m.from_label}: {m.subject} — {m.body[:200]}" for m in messages
            )
        )

    if project:
        artifacts = artifact_service.for_project(db, project.id)[:20]
        if artifacts:
            parts.append(
                "Deliverables filed on this project:\n"
                + "\n".join(f"- {a.name} [{a.kind} v{a.version}]" for a in artifacts)
            )
        files = _file_list(company.slug, project)
        if files:
            parts.append(f"Workspace files:\n{files}")

    wiki = _wiki_index(db, company.id)
    if wiki:
        parts.append(f"Wiki pages that exist:\n{wiki}")

    chat = _chat_log(db, company.id)
    if chat:
        parts.append(f"Recent team chat:\n{chat}")

    if work_item and work_item.assignee_id:
        colleagues = _who_else(db, company, employee)
        if colleagues:
            parts.append(f"Who else is here:\n{colleagues}")

    return "\n\n".join(parts)


def _file_list(company_slug: str, project: Project, limit: int = 80) -> str:
    try:
        space = workspace.for_project(company_slug, project.key)
        space.init(project.name)
        entries = space.tree()
    except Exception as exc:
        log.debug("could not list workspace: %s", exc)
        return ""
    files = [entry["path"] for entry in entries if entry["type"] == "file"]
    listing = "\n".join(f"- {path}" for path in files[:limit])
    if len(files) > limit:
        listing += f"\n… and {len(files) - limit} more"
    return listing


def _wiki_index(db: Session, company_id: str, limit: int = 30) -> str:
    rows = list(
        db.scalars(select(Document).where(Document.company_id == company_id).limit(limit))
    )
    return "\n".join(f"- {row.title} (slug: {row.slug})" for row in rows)


def _chat_log(db: Session, company_id: str, limit: int = 12) -> str:
    rows = list(
        db.scalars(
            select(Message)
            .join(Channel, Message.channel_id == Channel.id)
            .where(Channel.company_id == company_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    )
    return "\n".join(f"{row.author_label}: {row.body}" for row in reversed(rows))


def _who_else(db: Session, company: Company, employee: Employee) -> str:
    people = list(
        db.scalars(
            select(Employee).where(
                Employee.company_id == company.id, Employee.id != employee.id
            )
        )
    )
    lines = []
    for person in people[:15]:
        capabilities = ", ".join(roles.capabilities_of(db, person, company)[:6]) or "—"
        lines.append(f"- {person.name} ({person.title}) — can: {capabilities}")
    return "\n".join(lines)


def artifact_excerpts(db: Session, work_item: WorkItem, limit: int = 3) -> str:
    """The current text of what this item produced, for a reviewer to read."""
    rows = list(
        db.scalars(
            select(Artifact)
            .where(Artifact.work_item_id == work_item.id, Artifact.superseded_by.is_(None))
            .limit(limit)
        )
    )
    if not rows:
        return ""
    return "\n\n".join(
        f"--- {row.name} (v{row.version}, hash {row.content_hash[:12]}) ---\n"
        + artifact_service.excerpt(db, row, 6000)
        for row in rows
    )
