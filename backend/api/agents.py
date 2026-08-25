"""Every employee is an addressable agent with its own API.

`POST /agents/{id}/messages` with that employee's token gets work done by that
employee: their memory, their tools, their model policy, their budget, their
audit trail. The dashboard is one client of this API rather than a privileged
path through the middle of it.
"""

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents import worker
from db import get_db, session
from models import AgentTask, AgentToken, Employee, Memory, Project, RunStep, WorkItem
from models.memory import BLOCK_LABELS
from services import embeddings, packs, pricing, routing, tokens, usage
from services import memory as memory_service

from . import lookups, serializers
from .deps import AgentPrincipal, authorise_for, get_employee, optional_agent

router = APIRouter(prefix="/agents", tags=["agents"])

POLL_SECONDS = 0.6
STREAM_LIMIT_SECONDS = 300.0


class MessageIn(BaseModel):
    message: str = Field(..., min_length=1)
    project_id: str | None = None
    work_item_id: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=64)


class TaskIn(BaseModel):
    kind: str = "message"
    message: str | None = None
    project_id: str | None = None
    work_item_id: str | None = None
    max_steps: int | None = Field(default=None, ge=1, le=64)
    priority: int = 100


class BlockIn(BaseModel):
    content: str
    pinned: bool | None = None


class MemoryIn(BaseModel):
    title: str
    body: str = ""
    kind: str = "fact"
    scope: str = "private"
    confidence: float = 0.7


class TokenIn(BaseModel):
    name: str = "default"
    scopes: list[str] | None = None
    expires_in_days: int | None = None


class ConfigIn(BaseModel):
    persona: str | None = None
    capabilities: list[str] | None = None
    toolbelt: list[str] | None = None
    model_policy: dict | None = None
    autonomy_level: str | None = None
    budget_daily_micros: int | None = None
    api_enabled: bool | None = None


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


@router.get("/{employee_id}/card")
def agent_card(
    employee_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """Who this agent is, what it can do, and how to reach it."""
    employee = authorise_for(employee_id, "agent:read", principal, db)
    from agents import tools as tool_registry

    available = tool_registry.for_employee(employee)
    return {
        "id": employee.id,
        "name": employee.name,
        "title": employee.title,
        "company": {
            "id": employee.company.id,
            "name": employee.company.name,
            "slug": employee.company.slug,
            "industry": employee.company.industry,
            "pack": employee.company.pack_key,
        },
        "department": employee.department,
        "role_key": employee.role_key,
        "persona": employee.persona,
        "skills": employee.skills or [],
        "capabilities": employee.capabilities or [],
        "tools": [
            {
                "name": tool.name,
                "group": tool.group,
                "description": tool.description,
                "read_only": tool.read_only,
            }
            for tool in available
        ],
        "models": routing.describe(employee, employee.company),
        "autonomy_level": employee.autonomy_level,
        "api_enabled": employee.api_enabled,
        "state": employee.status,
        "endpoints": {
            "message": f"/agents/{employee.id}/messages",
            "task": f"/agents/{employee.id}/tasks",
            "memory": f"/agents/{employee.id}/memory",
            "usage": f"/agents/{employee.id}/usage",
        },
    }


@router.get("/{employee_id}/prompt")
def agent_prompt(
    employee_id: str,
    project_id: str | None = None,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """The exact system prompt this agent runs with. Nothing hidden."""
    employee = authorise_for(employee_id, "agent:read", principal, db)
    project = db.get(Project, project_id) if project_id else None
    return {"system_prompt": worker.system_prompt_for(db, employee, project)}


# --------------------------------------------------------------------------
# talking to an agent
# --------------------------------------------------------------------------


@router.post("/{employee_id}/messages")
def send_message(
    employee_id: str,
    payload: MessageIn,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """One turn, synchronously. Returns the reply and every tool call it made."""
    employee = authorise_for(employee_id, "agent:message", principal, db)
    project = db.get(Project, payload.project_id) if payload.project_id else None
    work_item = db.get(WorkItem, payload.work_item_id) if payload.work_item_id else None
    if project and project.company_id != employee.company_id:
        raise HTTPException(status_code=400, detail="That project belongs to another company.")

    return worker.ask_now(
        db,
        company=employee.company,
        employee=employee,
        message=payload.message,
        project=project,
        work_item=work_item,
        max_steps=payload.max_steps,
        created_by=principal.token.name if principal else "You",
    )


@router.post("/{employee_id}/tasks", status_code=202)
def create_task(
    employee_id: str,
    payload: TaskIn,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """Queue work and get an id back. The clock picks it up."""
    employee = authorise_for(employee_id, "agent:task", principal, db)
    if payload.kind not in worker.TASK_KINDS:
        raise HTTPException(
            status_code=400, detail=f"kind must be one of: {', '.join(worker.TASK_KINDS)}"
        )
    if payload.kind in {"message"} and not payload.message:
        raise HTTPException(status_code=400, detail="A message task needs a message.")

    task = worker.enqueue(
        db,
        company=employee.company,
        employee=employee,
        kind=payload.kind,
        request={
            "message": payload.message,
            "project_id": payload.project_id,
            "max_steps": payload.max_steps,
        },
        source="api",
        created_by=principal.token.name if principal else "You",
        work_item_id=payload.work_item_id,
        priority=payload.priority,
    )
    db.commit()
    return serializers.agent_task(task)


@router.get("/{employee_id}/tasks")
def list_tasks(
    employee_id: str,
    limit: int = Query(30, le=100),
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    employee = authorise_for(employee_id, "agent:read", principal, db)
    rows = list(
        db.scalars(
            select(AgentTask)
            .where(AgentTask.employee_id == employee.id)
            .order_by(AgentTask.created_at.desc())
            .limit(limit)
        )
    )
    return [serializers.agent_task(row) for row in rows]


@router.get("/{employee_id}/tasks/{task_id}")
def read_task(
    employee_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    employee = authorise_for(employee_id, "agent:read", principal, db)
    task = _task_of(db, employee, task_id)
    return serializers.agent_task(task, full=True)


@router.post("/{employee_id}/tasks/{task_id}/cancel")
def cancel_task(
    employee_id: str,
    task_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """Stop a task. A running turn notices between tool calls, not at the end."""
    from agents import runtime

    employee = authorise_for(employee_id, "agent:task", principal, db)
    task = _task_of(db, employee, task_id)
    if task.status in {"done", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"That task is already {task.status}.")
    task.cancel_requested = True
    if task.status == "queued":
        task.status = "cancelled"
    db.add(task)
    db.commit()
    runtime.request_cancel(task.id)
    return serializers.agent_task(task)


@router.get("/{employee_id}/tasks/{task_id}/stream")
async def stream_task(
    employee_id: str, task_id: str, request: Request, cursor: int = 0
):
    """Server-sent events for one task: its steps as they land, then the result."""
    db = session()
    try:
        employee = get_employee(db, employee_id)
        task = _task_of(db, employee, task_id)
        task_id = task.id
    finally:
        db.close()

    async def publisher():
        seen: set[str] = set()
        elapsed = 0.0
        while elapsed < STREAM_LIMIT_SECONDS:
            if await request.is_disconnected():
                return
            inner = session()
            try:
                task = inner.get(AgentTask, task_id)
                if not task:
                    return
                steps = list(
                    inner.scalars(
                        select(RunStep)
                        .where(RunStep.task_id == task_id)
                        .order_by(RunStep.created_at)
                    )
                )
                fresh = [
                    serializers.run_step(step) for step in steps if step.id not in seen
                ]
                for step in steps:
                    seen.add(step.id)
                state = serializers.agent_task(task, full=True)
                finished = task.status in {"done", "failed", "cancelled"}
            finally:
                inner.close()

            for step in fresh:
                yield f"event: step\ndata: {json.dumps(step)}\n\n"
            yield f"event: task\ndata: {json.dumps(state)}\n\n"
            if finished:
                return

            await asyncio.sleep(POLL_SECONDS)
            elapsed += POLL_SECONDS

    return StreamingResponse(
        publisher(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _task_of(db: Session, employee: Employee, task_id: str) -> AgentTask:
    task = lookups.agent_task(db, task_id)
    if not task or task.employee_id != employee.id:
        raise HTTPException(status_code=404, detail="No such task for this agent.")
    return task


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------


@router.get("/{employee_id}/memory")
def read_memory(
    employee_id: str,
    query: str = "",
    limit: int = Query(40, le=200),
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """The four core blocks, and either the whole store or what a query retrieves.

    The search here runs the *actual* retrieval, so you can see what this agent
    would pull in for a prompt before it runs.
    """
    employee = authorise_for(employee_id, "memory:read", principal, db)
    blocks = memory_service.blocks_for(db, employee)
    db.commit()

    if query:
        hits, mode = memory_service.search(
            db, employee.company_id, query, employee_id=employee.id, limit=limit
        )
        rows = [serializers.memory(hit.memory, hit.score, hit.similarity) for hit in hits]
    else:
        mode = "all"
        rows = [
            serializers.memory(row)
            for row in db.scalars(
                select(Memory)
                .where(
                    Memory.company_id == employee.company_id,
                    (Memory.employee_id == employee.id) | (Memory.employee_id.is_(None)),
                )
                .order_by(Memory.updated_at.desc())
                .limit(limit)
            )
        ]

    return {
        "blocks": [serializers.memory_block(block) for block in blocks],
        "memories": rows,
        "retrieval_mode": mode,
        "embeddings": embeddings.status(),
    }


@router.put("/{employee_id}/memory/blocks/{label}")
def write_block(
    employee_id: str,
    label: str,
    payload: BlockIn,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    employee = authorise_for(employee_id, "memory:write", principal, db)
    if label not in BLOCK_LABELS:
        raise HTTPException(status_code=400, detail=f"Blocks are: {', '.join(BLOCK_LABELS)}")
    who = principal.employee.name if principal else "You"
    try:
        block = memory_service.set_block(db, employee, label, payload.content, updated_by=who)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if payload.pinned is not None and principal is None:
        block.pinned = payload.pinned
        db.add(block)
    db.commit()
    return serializers.memory_block(block)


@router.post("/{employee_id}/memory", status_code=201)
def teach(
    employee_id: str,
    payload: MemoryIn,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    """Tell an agent something directly. Procedures are not writeable here.

    A procedure has to be earned by work that passed its checks — that is the
    learning gate, and letting the API post one straight in would be a hole in it.
    """
    employee = authorise_for(employee_id, "memory:write", principal, db)
    if payload.kind == "procedure":
        raise HTTPException(
            status_code=400,
            detail=(
                "Procedures are distilled from work whose checks passed, not written "
                "directly. Teach a fact instead, or let the agent earn the procedure."
            ),
        )
    try:
        row, what_happened = memory_service.remember(
            db,
            company_id=employee.company_id,
            employee_id=None if payload.scope == "company" else employee.id,
            kind=payload.kind,
            scope=payload.scope,
            title=payload.title,
            body=payload.body,
            confidence=payload.confidence,
            source_kind="taught",
            created_by=principal.employee.name if principal else "You",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {**serializers.memory(row), "outcome": what_happened}


@router.delete("/{employee_id}/memory/{memory_id}", status_code=204)
def forget(
    employee_id: str,
    memory_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    employee = authorise_for(employee_id, "memory:write", principal, db)
    row = db.get(Memory, memory_id)
    if not row or row.company_id != employee.company_id:
        raise HTTPException(status_code=404, detail="No such memory.")
    memory_service.forget(db, row, by=principal.employee.name if principal else "You")
    db.commit()


@router.post("/{employee_id}/memory/{memory_id}/promote")
def promote(
    employee_id: str,
    memory_id: str,
    scope: str = "company",
    db: Session = Depends(get_db),
):
    employee = get_employee(db, employee_id)
    row = db.get(Memory, memory_id)
    if not row or row.company_id != employee.company_id:
        raise HTTPException(status_code=404, detail="No such memory.")
    try:
        memory_service.promote(db, row, to=scope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serializers.memory(row)


# --------------------------------------------------------------------------
# tokens, usage, configuration
# --------------------------------------------------------------------------


@router.get("/{employee_id}/tokens")
def list_tokens(employee_id: str, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    rows = list(
        db.scalars(
            select(AgentToken)
            .where(AgentToken.employee_id == employee.id)
            .order_by(AgentToken.created_at.desc())
        )
    )
    return [serializers.agent_token(row) for row in rows]


@router.post("/{employee_id}/tokens", status_code=201)
def mint_token(employee_id: str, payload: TokenIn, db: Session = Depends(get_db)):
    """Mint a token. The secret is in this response and nowhere else, ever."""
    from services import ledger

    employee = get_employee(db, employee_id)
    try:
        row, plaintext = tokens.mint(
            db,
            employee,
            name=payload.name,
            scopes=payload.scopes,
            expires_in_days=payload.expires_in_days,
        )
    except tokens.TokenError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ledger.append(
        db,
        company_id=employee.company_id,
        kind="token.minted",
        actor_label="You",
        subject_kind="agent_token",
        subject_id=row.id,
        payload={"employee": employee.name, "name": row.name, "scopes": row.scopes},
    )
    db.commit()
    return {
        **serializers.agent_token(row),
        "token": plaintext,
        "note": "Copy it now. It is not stored and cannot be shown again.",
        "example": (
            f"curl -X POST http://localhost:8000/agents/{employee.id}/messages "
            f'-H "Authorization: Bearer {plaintext}" '
            f'-H "Content-Type: application/json" '
            f"-d '{{\"message\": \"What are you working on?\"}}'"
        ),
    }


@router.delete("/{employee_id}/tokens/{token_id}", status_code=204)
def revoke_token(employee_id: str, token_id: str, db: Session = Depends(get_db)):
    from services import ledger

    employee = get_employee(db, employee_id)
    row = db.get(AgentToken, token_id)
    if not row or row.employee_id != employee.id:
        raise HTTPException(status_code=404, detail="No such token.")
    tokens.revoke(db, row)
    ledger.append(
        db,
        company_id=employee.company_id,
        kind="token.revoked",
        actor_label="You",
        subject_kind="agent_token",
        subject_id=row.id,
        payload={"employee": employee.name, "name": row.name},
    )
    db.commit()


@router.get("/{employee_id}/usage")
def agent_usage(
    employee_id: str,
    db: Session = Depends(get_db),
    principal: AgentPrincipal | None = Depends(optional_agent),
):
    employee = authorise_for(employee_id, "agent:read", principal, db)
    totals = usage.for_employee(db, employee.id)
    return {
        "employee_id": employee.id,
        **totals,
        "budget_daily_micros": employee.budget_daily_micros,
        "over_budget": bool(
            employee.budget_daily_micros
            and totals["today"]["cost_micros"] >= employee.budget_daily_micros
        ),
        "formatted": {
            window: pricing.format_cost(values["cost_micros"])
            for window, values in totals.items()
        },
        "note": "Cost is an estimate from a configurable rate table; tokens are measured.",
    }


@router.patch("/{employee_id}/config")
def configure(employee_id: str, payload: ConfigIn, db: Session = Depends(get_db)):
    employee = get_employee(db, employee_id)
    changes = payload.model_dump(exclude_unset=True)

    if "capabilities" in changes:
        unknown = [
            capability
            for capability in changes["capabilities"]
            if capability not in packs.CAPABILITY_LABELS
        ]
        if unknown:
            # Packs may define their own, so this is a note rather than a refusal.
            changes.setdefault("_notes", []).append(
                f"Capabilities not in the standard catalogue: {', '.join(unknown)}"
            )
    notes = changes.pop("_notes", [])

    for key, value in changes.items():
        setattr(employee, key, value)
    db.add(employee)
    db.commit()
    return {**serializers.employee(employee), "notes": notes}
