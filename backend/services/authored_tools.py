"""Tools an agent wrote for itself, and the gate they do not get past on their own.

An agent that keeps redoing the same fiddly calculation should be able to write
it down once. The obvious version of that idea — let the model emit code and run
it — hands an agent the ability to do anything the rest of this system was built
to prevent, so this is the narrow version instead:

  * the body is a single expression, evaluated by the same AST-restricted
    evaluator that assertion checks use. No imports, no attribute access, no
    subscripting into callables, no I/O, no names but the declared parameters;
  * the author must supply worked examples, and every one is run before the
    proposal is even shown to you. A tool whose own examples do not hold is
    rejected without a person ever looking at it;
  * nothing is callable until a person approves it.

That last rule is the whole point. Everything else here is what makes the
approval a decision about usefulness rather than a decision about safety.
"""

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AuthoredTool, Company, Employee

from . import events, ledger
from .checks.expressions import ExpressionError, evaluate

log = logging.getLogger(__name__)

NAME = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_EXPRESSION = 500
MAX_PARAMETERS = 8
MIN_EXAMPLES = 2
TYPES = {"number": (int, float), "string": str, "boolean": bool, "list": list}


class AuthoredToolError(ValueError):
    pass


def propose(
    db: Session,
    *,
    company: Company,
    author: Employee | None,
    name: str,
    description: str,
    rationale: str,
    parameters: dict,
    expression: str,
    examples: list[dict],
) -> AuthoredTool:
    """Record a proposal, having first proved it does what it claims."""
    _validate(name, parameters, expression, examples)
    failures = check_examples(parameters, expression, examples)
    if failures:
        raise AuthoredToolError(
            "The tool does not do what its own examples say it does: "
            + "; ".join(failures[:3])
        )

    clash = db.scalar(
        select(AuthoredTool).where(
            AuthoredTool.company_id == company.id, AuthoredTool.name == name
        )
    )
    if clash and clash.status != "retired":
        raise AuthoredToolError(f"There is already a tool called '{name}' here.")

    row = clash or AuthoredTool(company_id=company.id, name=name)
    row.author_id = author.id if author else None
    row.author_label = f"{author.name} ({author.title})" if author else "You"
    row.description = description[:400]
    row.rationale = rationale
    row.parameters = parameters
    row.expression = expression
    row.examples = examples
    row.status = "proposed"
    row.review_note = ""
    row.reviewed_by = None
    row.reviewed_at = None
    db.add(row)
    db.flush()

    events.record(
        db,
        company_id=company.id,
        employee_id=author.id if author else None,
        actor=row.author_label,
        kind="tool.proposed",
        summary=f"proposed a tool: {name}",
        payload={"tool_id": row.id, "name": name},
    )
    return row


def _validate(name: str, parameters: dict, expression: str, examples: list[dict]) -> None:
    if not NAME.match(name or ""):
        raise AuthoredToolError(
            "A tool name must be lowercase letters, digits and underscores, 3–40 characters."
        )
    if not expression or len(expression) > MAX_EXPRESSION:
        raise AuthoredToolError(f"The expression must be 1–{MAX_EXPRESSION} characters.")
    if len(parameters) > MAX_PARAMETERS:
        raise AuthoredToolError(f"At most {MAX_PARAMETERS} parameters.")
    for key, kind in (parameters or {}).items():
        if not NAME.match(key):
            raise AuthoredToolError(f"'{key}' is not a usable parameter name.")
        if kind not in TYPES:
            raise AuthoredToolError(
                f"Parameter '{key}' has type '{kind}'. Use one of: {', '.join(TYPES)}."
            )
    if len(examples) < MIN_EXAMPLES:
        raise AuthoredToolError(
            f"Give at least {MIN_EXAMPLES} worked examples, so the tool can be checked "
            "before anybody reads it."
        )

    # Parse once here so a syntactically broken proposal fails now, with a
    # message the author can act on, rather than at approval time.
    try:
        evaluate(expression, {key: 1 for key in parameters})
    except ExpressionError as exc:
        raise AuthoredToolError(f"That expression is not allowed: {exc}") from exc
    except Exception:
        # A type error against placeholder values is fine; the examples decide.
        pass


def check_examples(parameters: dict, expression: str, examples: list[dict]) -> list[str]:
    """Run every claimed example. Returns the ones that did not hold."""
    failures: list[str] = []
    for index, example in enumerate(examples):
        given = example.get("given") or {}
        expected = example.get("expect")
        missing = [key for key in parameters if key not in given]
        if missing:
            failures.append(f"example {index + 1} does not supply {', '.join(missing)}")
            continue
        try:
            produced = evaluate(expression, given)
        except Exception as exc:
            failures.append(f"example {index + 1} raised {type(exc).__name__}: {exc}")
            continue
        if not _matches(produced, expected):
            failures.append(f"example {index + 1} expected {expected!r} but produced {produced!r}")
    return failures


def _matches(produced, expected) -> bool:
    if isinstance(produced, (int, float)) and isinstance(expected, (int, float)):
        return abs(float(produced) - float(expected)) < 1e-9
    return produced == expected


def review(
    db: Session,
    tool: AuthoredTool,
    *,
    approved: bool,
    by: str = "You",
    note: str = "",
) -> AuthoredTool:
    """Approve or refuse. Either way it goes in the chain."""
    if approved:
        failures = check_examples(tool.parameters or {}, tool.expression, tool.examples or [])
        if failures:
            raise AuthoredToolError(
                "It no longer passes its own examples, so it cannot be approved: "
                + "; ".join(failures[:3])
            )

    tool.status = "approved" if approved else "rejected"
    tool.reviewed_by = by[:160]
    tool.reviewed_at = datetime.now(UTC)
    tool.review_note = note
    db.add(tool)

    ledger.append(
        db,
        company_id=tool.company_id,
        kind="tool.reviewed",
        actor_label=by,
        subject_kind="authored_tool",
        subject_id=tool.id,
        payload={
            "name": tool.name,
            "status": tool.status,
            "expression": tool.expression,
            "author": tool.author_label,
            "note": note[:500],
        },
    )
    events.record(
        db,
        company_id=tool.company_id,
        actor=by,
        kind="tool.reviewed",
        summary=f"{tool.status} the tool {tool.name}",
        payload={"tool_id": tool.id, "status": tool.status},
    )
    db.flush()
    return tool


def retire(db: Session, tool: AuthoredTool, *, by: str = "You") -> AuthoredTool:
    tool.status = "retired"
    tool.reviewed_by = by[:160]
    tool.reviewed_at = datetime.now(UTC)
    db.add(tool)
    db.flush()
    return tool


def approved_for(db: Session, company: Company) -> list[AuthoredTool]:
    return list(
        db.scalars(
            select(AuthoredTool).where(
                AuthoredTool.company_id == company.id, AuthoredTool.status == "approved"
            )
        )
    )


def call(db: Session, tool: AuthoredTool, arguments: dict):
    """Run an approved tool. Refuses anything that is not approved, every time."""
    if tool.status != "approved":
        raise AuthoredToolError(
            f"'{tool.name}' is {tool.status}, not approved, so it cannot be called."
        )
    values = _coerce(tool.parameters or {}, arguments)
    result = evaluate(tool.expression, values)
    tool.uses += 1
    tool.last_used_at = datetime.now(UTC)
    db.add(tool)
    return result


def _coerce(parameters: dict, arguments: dict) -> dict:
    values = {}
    for key, kind in parameters.items():
        if key not in arguments:
            raise AuthoredToolError(f"'{key}' is required.")
        value = arguments[key]
        expected = TYPES[kind]
        if kind == "number" and isinstance(value, bool):
            raise AuthoredToolError(f"'{key}' must be a number.")
        if not isinstance(value, expected):
            raise AuthoredToolError(f"'{key}' must be a {kind}.")
        values[key] = value
    return values


def as_tools(db: Session, company: Company) -> list:
    """Approved tools, as `Tool` objects the registry can hand to a model."""
    from agents.tools.base import Tool, ToolResult, failed

    built: list = []
    for row in approved_for(db, company):
        built.append(_wrap(row, Tool, ToolResult, failed))
    return built


def _wrap(row: AuthoredTool, Tool, ToolResult, failed):  # noqa: N803
    tool_id = row.id

    def handler(ctx, **arguments):
        current = ctx.db.get(AuthoredTool, tool_id)
        if not current or current.status != "approved":
            return failed(
                f"{row.name} is no longer approved.",
                "Do the calculation yourself and say that you did.",
            )
        try:
            result = call(ctx.db, current, arguments)
        except AuthoredToolError as exc:
            return failed(str(exc), "Check the arguments, or do it by hand.")
        except Exception as exc:
            return failed(
                f"{row.name} failed: {exc}",
                "Do it by hand and mention that the tool is broken.",
            )
        return ToolResult(text=str(result), ok=True)

    return Tool(
        name=row.name,
        group="authored",
        description=f"{row.description} (written by {row.author_label}, approved)",
        parameters={
            "type": "object",
            "properties": {
                key: {"type": "number" if kind == "number" else kind}
                for key, kind in (row.parameters or {}).items()
            },
            "required": list((row.parameters or {}).keys()),
        },
        handler=handler,
        read_only=True,
        cost_hint="cheap",
    )
