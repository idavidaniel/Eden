"""Producing deliverables that are not code.

A contract draft, a research memo, a campaign brief. Each one is registered as an
artifact with a content hash the moment it is written, which is what lets the
platform check it and the ledger commit to it.
"""

from sqlalchemy import select

from models import Artifact
from services import artifacts as artifact_service
from services import checks as check_service
from services import packs

from .base import Tool, ToolContext, ToolResult, failed, obj, string

PREVIEW_CHARS = 4000


def _kinds(ctx: ToolContext) -> list[str]:
    return [row.key for row in packs.artifact_kinds_for(ctx.db, ctx.company)]


def write_deliverable(
    ctx: ToolContext, name: str, kind: str, content: str, title: str = ""
) -> ToolResult:
    if not ctx.project:
        return failed(
            "No project is in scope, so there is nowhere to file this.",
            "Ask your manager which project this belongs to.",
        )
    available = _kinds(ctx)
    if kind not in available:
        return failed(
            f"'{kind}' is not a kind of deliverable this company produces.",
            f"Use one of: {', '.join(available)}.",
        )
    if not content.strip():
        return failed("Refusing to file an empty document.", "Write the content, then file it.")

    artifact = artifact_service.record(
        ctx.db,
        company=ctx.company,
        project=ctx.project,
        name=name,
        kind=kind,
        title=title or name,
        content=content,
        work_item_id=ctx.work_item.id if ctx.work_item else None,
        produced_by=ctx.employee,
    )
    return ToolResult(
        text=(
            f"Filed {artifact.name} as {kind} v{artifact.version} "
            f"({artifact.size_bytes} bytes, hash {artifact.content_hash[:12]}).\n"
            "Run check_my_work when you think it is ready."
        ),
        artifacts=[artifact],
    )


def read_deliverable(ctx: ToolContext, name: str) -> ToolResult:
    if not ctx.project:
        return failed("No project is in scope.", "")
    artifact = artifact_service.latest(ctx.db, ctx.project.id, name)
    if not artifact:
        return failed(
            f"No deliverable named '{name}'.",
            "Call list_deliverables to see what exists.",
        )
    body = artifact_service.read(ctx.db, artifact)
    return ToolResult(
        text=f"# {artifact.title} (v{artifact.version})\n\n{body[:20000]}",
        artifacts=[artifact],
    )


def list_deliverables(ctx: ToolContext) -> ToolResult:
    if not ctx.project:
        return failed("No project is in scope.", "")
    rows = artifact_service.for_project(ctx.db, ctx.project.id)
    if not rows:
        kinds = ", ".join(_kinds(ctx))
        return ToolResult(
            text=f"Nothing has been produced yet. Kinds this company files: {kinds}."
        )
    return ToolResult(
        text="\n".join(
            f"{row.name} [{row.kind} v{row.version}] {row.title or ''}".strip() for row in rows
        )
    )


def edit_deliverable(ctx: ToolContext, name: str, old_text: str, new_text: str) -> ToolResult:
    """Replace one exact span, so a small change does not mean re-sending the file."""
    if not ctx.project:
        return failed("No project is in scope.", "")
    artifact = artifact_service.latest(ctx.db, ctx.project.id, name)
    if not artifact:
        return failed(f"No deliverable named '{name}'.", "Call list_deliverables first.")

    body = artifact_service.read(ctx.db, artifact)
    occurrences = body.count(old_text)
    if occurrences == 0:
        return failed(
            f"That text does not appear in {name}.",
            "Read it again and copy the span exactly, including punctuation.",
        )
    if occurrences > 1:
        return failed(
            f"That text appears {occurrences} times in {name}.",
            "Include a sentence either side so the span is unique.",
        )

    updated = artifact_service.record(
        ctx.db,
        company=ctx.company,
        project=ctx.project,
        name=name,
        kind=artifact.kind,
        title=artifact.title,
        content=body.replace(old_text, new_text, 1),
        work_item_id=ctx.work_item.id if ctx.work_item else None,
        produced_by=ctx.employee,
    )
    return ToolResult(text=f"Edited {name} → v{updated.version}.", artifacts=[updated])


def check_my_work(ctx: ToolContext) -> ToolResult:
    """Run the platform's checks now, rather than finding out after the turn."""
    if not (ctx.project and ctx.work_item):
        return failed(
            "There is no work item in scope to check.",
            "This tool checks the item you were assigned.",
        )
    results = check_service.run_for_work_item(
        ctx.db,
        company=ctx.company,
        project=ctx.project,
        work_item=ctx.work_item,
        author=ctx.employee,
        run_id=ctx.run.id if ctx.run else None,
        task_id=ctx.task_id,
    )
    if not results:
        return ToolResult(
            text="No checks apply to this work item yet, so there is nothing to verify."
        )
    verdict = check_service.verdict_for(results)
    lines = [f"[{result.status}] {result.detail}" for result in results]
    hint = ""
    if not verdict["ok"]:
        hint = (
            "Fix what failed and run check_my_work again. Do not set the item to review "
            "while a required check is failing — the platform will reopen it."
        )
    return ToolResult(text="\n".join(lines), ok=verdict["ok"], error_hint=hint)


def list_artifacts_for_item(ctx: ToolContext) -> ToolResult:
    if not ctx.work_item:
        return failed("No work item is in scope.", "")
    rows = list(
        ctx.db.scalars(
            select(Artifact).where(
                Artifact.work_item_id == ctx.work_item.id, Artifact.superseded_by.is_(None)
            )
        )
    )
    if not rows:
        return ToolResult(text="This work item has produced nothing yet.")
    return ToolResult(
        text="\n".join(f"{row.name} [{row.kind} v{row.version}]" for row in rows)
    )


TOOLS = [
    Tool(
        name="write_deliverable",
        group="documents",
        description=(
            "File a finished document as a deliverable — a draft, memo, brief or report. "
            "It is stored with a content hash and becomes the thing the platform checks. "
            "Send the complete text, not a summary of it."
        ),
        parameters=obj(
            {
                "name": string("Short file-like name, e.g. 'nda-acme-v1.md'"),
                "kind": string("Kind of deliverable, e.g. contract_draft or research_memo"),
                "content": string("The full document, in Markdown"),
                "title": string("Human-readable title"),
            },
            required=["name", "kind", "content"],
        ),
        handler=write_deliverable,
    ),
    Tool(
        name="edit_deliverable",
        group="documents",
        description=(
            "Change part of a filed document by replacing one exact span. Prefer this "
            "over re-filing the whole document. The span must appear exactly once."
        ),
        parameters=obj(
            {
                "name": string("The deliverable's name"),
                "old_text": string("Exact text to replace, copied verbatim"),
                "new_text": string("Replacement text"),
            }
        ),
        handler=edit_deliverable,
    ),
    Tool(
        name="read_deliverable",
        group="documents",
        description="Read the current version of a filed deliverable.",
        parameters=obj({"name": string("The deliverable's name")}),
        read_only=True,
        handler=read_deliverable,
    ),
    Tool(
        name="list_deliverables",
        group="documents",
        description="List everything this project has produced.",
        parameters=obj({}, required=[]),
        read_only=True,
        handler=list_deliverables,
    ),
    Tool(
        name="list_my_artifacts",
        group="documents",
        description="List what your current work item has produced so far.",
        parameters=obj({}, required=[]),
        read_only=True,
        handler=list_artifacts_for_item,
    ),
    Tool(
        name="check_my_work",
        group="documents",
        description=(
            "Run the platform's checks against your work item right now and see the "
            "verdicts. This is the same verification that decides whether your work is "
            "accepted, so run it before you finish."
        ),
        parameters=obj({}, required=[]),
        handler=check_my_work,
        cost_hint="slow",
    ),
]
