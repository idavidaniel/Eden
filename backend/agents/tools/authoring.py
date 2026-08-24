"""An employee writing a tool for itself — and not being allowed to use it.

The proposal goes to a person. Until they approve it, the agent that wrote it
cannot call it, which is the only reason it is safe to let an agent write one at
all. The body is a single expression run by the same restricted evaluator that
assertion checks use, so even an approved tool cannot import, read a file, or
reach the network.
"""

from services import authored_tools as authored

from .base import Tool, ToolContext, ToolResult, failed, obj, string


def propose_tool(
    ctx: ToolContext,
    name: str,
    expression: str,
    description: str = "",
    rationale: str = "",
    parameters: dict | None = None,
    examples: list | None = None,
) -> ToolResult:
    try:
        row = authored.propose(
            ctx.db,
            company=ctx.company,
            author=ctx.employee,
            name=name,
            description=description,
            rationale=rationale,
            parameters=parameters or {},
            expression=expression,
            examples=examples or [],
        )
    except authored.AuthoredToolError as exc:
        return failed(
            str(exc),
            "Fix the proposal and try once more, or just do the calculation by hand.",
        )
    ctx.db.commit()
    return ToolResult(
        text=(
            f"Proposed '{row.name}'. Its examples all hold, and it is now waiting for a "
            "person to approve it. You cannot call it until they do, so carry on without "
            "it for now."
        ),
        ok=True,
        meta={"tool_id": row.id, "status": row.status},
    )


def list_my_tools(ctx: ToolContext) -> ToolResult:
    from sqlalchemy import select

    from models import AuthoredTool

    rows = list(
        ctx.db.scalars(
            select(AuthoredTool).where(AuthoredTool.company_id == ctx.company.id)
        )
    )
    if not rows:
        return ToolResult(text="Nobody here has written a tool yet.", ok=True)
    lines = [
        f"{row.name} — {row.status}"
        + (f" ({row.review_note})" if row.review_note else "")
        + f" · by {row.author_label}"
        for row in rows
    ]
    return ToolResult(text="\n".join(lines), ok=True)


TOOLS = [
    Tool(
        name="propose_tool",
        group="authoring",
        description=(
            "Write down a calculation you keep redoing, so it can become a tool. The "
            "body must be a single expression over your named parameters — arithmetic, "
            "comparisons, and abs/min/max/round/sum/len/sorted/any/all. No imports, no "
            "file or network access. Give at least two worked examples; they are run "
            "immediately and the proposal is refused if any of them does not hold. "
            "A person has to approve it before anyone, including you, can call it."
        ),
        parameters=obj(
            {
                "name": string("lowercase_with_underscores, 3-40 characters"),
                "expression": string(
                    "One expression over your parameters, e.g. "
                    "'round(subtotal * (1 + rate), 2)'"
                ),
                "description": string("One line: what it does, for whoever calls it"),
                "rationale": string("Why: what you keep having to do by hand"),
                "parameters": {
                    "type": "object",
                    "description": (
                        'Parameter name to type, e.g. {"subtotal": "number", '
                        '"rate": "number"}. Types: number, string, boolean, list.'
                    ),
                },
                "examples": {
                    "type": "array",
                    "description": (
                        'Worked examples: [{"given": {"subtotal": 100, "rate": 0.2}, '
                        '"expect": 120.0}]. At least two.'
                    ),
                    "items": {"type": "object"},
                },
            },
            required=["name", "expression"],
        ),
        handler=propose_tool,
        read_only=False,
        cost_hint="cheap",
    ),
    Tool(
        name="list_authored_tools",
        group="authoring",
        description=(
            "See the tools people here have written and where each one stands. "
            "Approved ones already appear in your toolbelt."
        ),
        parameters=obj({}),
        handler=list_my_tools,
        read_only=True,
    ),
]
