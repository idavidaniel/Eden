"""One employee's turn.

This is the loop everything else calls: a run phase, an API request, the org
clock, an incoming message. It assembles context, lets the employee work with
their tools until they stop, and writes down everything that happened — the
context report, every tool call, what it cost.

Four things it enforces that the old loop did not:

- a daily spend ceiling, checked before the turn and between steps;
- cancellation, checked between steps, so "stop" means stop rather than
  "stop after the next four minutes of work";
- the injection rule — once a turn has pulled in text from outside, the same
  turn may only read, never act;
- a step budget with a warning before it runs out, so the turn lands.
"""

import json
import logging
import threading
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from agents import context as context_builder
from agents import prompts, tools
from agents.llm import chat
from config import get_settings
from models import Employee, RunStep
from services import pricing, routing, usage
from services.tools_policy import blocked_reason

log = logging.getLogger(__name__)

# Steps before the limit at which the employee is told to wrap up.
WARN_BEFORE_STEPS = 3
MAX_TOOL_RESULT_CHARS = 6000

_cancelled: set[str] = set()
_cancel_lock = threading.Lock()


def request_cancel(task_id: str) -> None:
    with _cancel_lock:
        _cancelled.add(task_id)


def clear_cancel(task_id: str) -> None:
    with _cancel_lock:
        _cancelled.discard(task_id)


def is_cancelled(task_id: str | None) -> bool:
    if not task_id:
        return False
    with _cancel_lock:
        return task_id in _cancelled


@dataclass
class TurnOutcome:
    step: RunStep
    text: str
    status: str
    tool_calls: list[dict] = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    context_report: dict = field(default_factory=dict)

    @property
    def hit_limit(self) -> bool:
        return self.status == "step_limit"


def over_budget(db: Session, employee: Employee) -> str | None:
    """Whether this employee has spent what they were allowed to today."""
    if not employee.budget_daily_micros:
        return None
    spent = usage.spend_today_micros(db, employee.id)
    if spent < employee.budget_daily_micros:
        return None
    return (
        f"{employee.name} has spent {pricing.format_cost(spent)} today, which is their "
        f"daily ceiling of {pricing.format_cost(employee.budget_daily_micros)}."
    )


def run_turn(
    db: Session,
    ctx: tools.ToolContext,
    task_prompt: str,
    *,
    kind: str = "work",
    max_steps: int | None = None,
    purpose: str | None = None,
    extra_context: str = "",
    persist: bool = True,
) -> TurnOutcome:
    """Let an employee work with their tools until they stop calling them."""
    settings = get_settings()
    max_steps = max_steps or settings.max_agent_steps
    employee = ctx.employee

    step = RunStep(
        run_id=ctx.run.id if ctx.run else None,
        employee_id=employee.id,
        work_item_id=ctx.work_item.id if ctx.work_item else None,
        kind=kind,
        status="running",
    )
    if persist:
        db.add(step)
        db.flush()
        ctx.step_id = step.id

    halted = _refuse_reason(db, ctx)
    if halted:
        return _finish(db, step, ctx, halted, "refused", [], {}, persist)

    assembled = context_builder.assemble(
        db,
        company=ctx.company,
        employee=employee,
        project=ctx.project,
        work_item=ctx.work_item,
        query=task_prompt[:2000],
    )
    colleagues = list(
        db.scalars(select(Employee).where(Employee.company_id == ctx.company.id))
    )
    system_prompt = prompts.employee_system_prompt(
        ctx.company, employee, colleagues, ctx.project, tools.for_employee(employee)
    )
    body = "\n\n".join(part for part in [assembled.as_prompt(), extra_context, task_prompt] if part)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": body},
    ]
    available = tools.for_employee(employee)
    schemas = tools.schemas(available)
    read_only_names = {tool.name for tool in available if tool.read_only}
    model = routing.model_for(employee, purpose or kind, ctx.company)

    reasoning_parts: list[str] = []
    calls_made: list[dict] = []
    produced: list = []
    final_text = ""
    status = "done"

    with usage.scope(
        company_id=ctx.company.id,
        employee_id=employee.id,
        task_id=ctx.task_id,
        run_id=ctx.run.id if ctx.run else None,
        purpose=purpose or kind,
    ):
        for index in range(max_steps):
            if is_cancelled(ctx.task_id):
                status = "cancelled"
                final_text = "Stopped: this task was cancelled."
                break

            ceiling = over_budget(db, employee)
            if ceiling:
                status = "over_budget"
                final_text = f"Stopped: {ceiling}"
                break

            if index == max_steps - WARN_BEFORE_STEPS:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"You have {WARN_BEFORE_STEPS} tool calls left. Finish now: save "
                            "your work, commit it if you changed files, update the work item, "
                            "then reply with what you did."
                        ),
                    }
                )

            reply = chat(messages, tools=schemas, model=model)
            if reply.reasoning:
                reasoning_parts.append(reply.reasoning)

            if not reply.tool_calls:
                final_text = reply.content
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"]),
                            },
                        }
                        for call in reply.tool_calls
                    ],
                }
            )

            for call in reply.tool_calls:
                result = _dispatch(db, ctx, call, read_only_names)
                db.commit()
                calls_made.append(
                    {
                        "name": call["name"],
                        "arguments": tools.redact(call["arguments"]),
                        "ok": result.ok,
                        "result": result.for_model()[:1200],
                    }
                )
                produced.extend(result.artifacts)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result.for_model()[:MAX_TOOL_RESULT_CHARS],
                    }
                )
                log.info("%s → %s", call["name"], result.for_model()[:120])
        else:
            status = "step_limit"
            final_text = (
                f"Ran out of tool calls ({max_steps}) before finishing this task. "
                "Raise MAX_AGENT_STEPS or split the work item into smaller pieces."
            )

    if ctx.work_item is not None:
        db.refresh(ctx.work_item)

    outcome = _finish(
        db, step, ctx, final_text, status, calls_made, assembled.report, persist, reasoning_parts
    )
    outcome.artifacts = produced
    _note_memory_use(db, ctx, assembled)
    return outcome


def _refuse_reason(db: Session, ctx: tools.ToolContext) -> str:
    if ctx.company.halted:
        return (
            "This company is halted, so nothing ran. "
            f"Reason: {ctx.company.halt_reason or 'stopped by the operator'}."
        )
    ceiling = over_budget(db, ctx.employee)
    return f"Nothing ran: {ceiling}" if ceiling else ""


def _dispatch(db: Session, ctx: tools.ToolContext, call: dict, read_only: set[str]):
    """Run one tool call, applying the policy that survives a poisoned page."""
    reason = blocked_reason(ctx, call["name"], read_only)
    if reason:
        return tools.ToolResult(text=reason, ok=False)
    return tools.execute(call["name"], ctx, call["arguments"])


def _finish(
    db: Session,
    step: RunStep,
    ctx: tools.ToolContext,
    text: str,
    status: str,
    calls: list[dict],
    report: dict,
    persist: bool,
    reasoning: list[str] | None = None,
) -> TurnOutcome:
    step.reasoning = "\n\n".join(reasoning or [])[:20000]
    step.output = (text or "")[:8000]
    step.tool_calls = calls
    step.status = status
    if persist:
        db.add(step)
        db.commit()
    return TurnOutcome(
        step=step, text=text or "", status=status, tool_calls=calls, context_report=report
    )


def _note_memory_use(db: Session, ctx: tools.ToolContext, assembled) -> None:
    """Mark retrieved memories as used, which is what keeps them alive."""
    from services import memory

    try:
        memory.note_use(db, assembled.used_memories, ctx.employee.id)
        db.commit()
    except Exception:
        db.rollback()
        log.debug("could not record memory use", exc_info=True)
