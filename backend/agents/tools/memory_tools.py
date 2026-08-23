"""An employee editing what it knows.

Core blocks are the four short things always in context; the agent rewrites them
itself as its situation changes. Facts and episodes go into the searchable store.
Procedures do not appear here at all: an agent may only distil one from work whose
checks passed, and that happens in the reflection pass, not by asking.
"""

from services import memory
from services.memory import MEMORY_KINDS

from .base import Tool, ToolContext, ToolResult, failed, obj, string

WRITEABLE_KINDS = ["fact", "episode"]


def update_memory_block(ctx: ToolContext, label: str, content: str) -> ToolResult:
    try:
        block = memory.set_block(
            ctx.db, ctx.employee, label, content, updated_by=ctx.employee.name
        )
    except ValueError as exc:
        return failed(str(exc), "")
    except PermissionError as exc:
        return failed(str(exc), "Say what you would change and why, and let the human decide.")
    return ToolResult(
        text=f"Updated your {label} block (v{block.version}, {len(block.content)} chars)."
    )


def remember(
    ctx: ToolContext, title: str, body: str = "", kind: str = "fact", confidence: float = 0.6
) -> ToolResult:
    if kind not in WRITEABLE_KINDS:
        allowed = ", ".join(WRITEABLE_KINDS)
        hint = (
            "Procedures are distilled automatically from work that passed its checks; "
            "you cannot write one directly."
            if kind == "procedure"
            else ""
        )
        return failed(f"You can only remember: {allowed}.", hint)
    if kind not in MEMORY_KINDS:
        return failed(f"Unknown memory kind '{kind}'.", "")

    row, what_happened = memory.remember(
        ctx.db,
        company_id=ctx.company.id,
        employee_id=ctx.employee.id,
        kind=kind,
        title=title,
        body=body,
        confidence=max(0.1, min(1.0, float(confidence or 0.6))),
        source_kind="work_item" if ctx.work_item else "turn",
        source_id=ctx.work_item.id if ctx.work_item else None,
        created_by=ctx.employee.name,
    )
    if what_happened == "merged":
        return ToolResult(text=f"You already knew that; strengthened it ({row.uses} uses).")
    if what_happened == "superseded":
        return ToolResult(text="Recorded, and marked the belief it contradicts as out of date.")
    return ToolResult(text=f"Remembered: {row.title}")


def recall(ctx: ToolContext, query: str, limit: int = 5) -> ToolResult:
    hits, mode = memory.search(
        ctx.db,
        ctx.company.id,
        query,
        employee_id=ctx.employee.id,
        limit=min(int(limit or 5), 12),
    )
    if not hits:
        return ToolResult(text=f"Nothing remembered about '{query}'.")
    memory.note_use(ctx.db, [hit.memory for hit in hits], ctx.employee.id)
    lines = [
        f"[{hit.memory.kind}, confidence {hit.memory.confidence:.1f}] {hit.memory.title}"
        + (f"\n    {hit.memory.body[:400]}" if hit.memory.body else "")
        for hit in hits
    ]
    header = "" if mode == "vector" else "(word-overlap search — no embedder available)\n"
    return ToolResult(text=header + "\n".join(lines))


def forget(ctx: ToolContext, query: str) -> ToolResult:
    hits, _ = memory.search(
        ctx.db, ctx.company.id, query, employee_id=ctx.employee.id, limit=1
    )
    if not hits:
        return failed(f"Nothing matching '{query}' to forget.", "")
    target = hits[0].memory
    if target.employee_id != ctx.employee.id:
        return failed(
            "That is company memory, not yours.",
            "Ask a human to retire it if you believe it is wrong.",
        )
    memory.forget(ctx.db, target, by=ctx.employee.name)
    return ToolResult(text=f"Archived: {target.title}")


TOOLS = [
    Tool(
        name="update_memory_block",
        group="memory",
        description=(
            "Rewrite one of your always-in-context memory blocks: persona, company, "
            "focus, or human (what you know about the person you work for). Send the "
            "whole block, not a diff."
        ),
        parameters=obj(
            {
                "label": string("persona, company, focus or human"),
                "content": string("The full new contents of the block"),
            }
        ),
        handler=update_memory_block,
    ),
    Tool(
        name="remember",
        group="memory",
        description=(
            "Record something worth knowing next time: a fact about this company, "
            "codebase, client or domain, or an episode of how a piece of work went. "
            "Keep it short and specific enough to be useful out of context."
        ),
        parameters=obj(
            {
                "title": string("One line, the memory itself"),
                "body": string("Detail, if the title is not enough"),
                "kind": string("fact or episode"),
                "confidence": {"type": "number", "description": "0 to 1"},
            },
            required=["title"],
        ),
        handler=remember,
    ),
    Tool(
        name="recall",
        group="memory",
        description="Search what you and the company remember.",
        parameters=obj(
            {"query": string("What you want to remember about"), "limit": {"type": "integer"}},
            required=["query"],
        ),
        read_only=True,
        handler=recall,
    ),
    Tool(
        name="forget",
        group="memory",
        description="Archive one of your own memories that turned out to be wrong.",
        parameters=obj({"query": string("Which memory")}),
        handler=forget,
    ),
]
