"""Model -> JSON shaping. One place so every route agrees on field names."""

from models import (
    Activity,
    AgentMessage,
    AgentTask,
    AgentToken,
    Approval,
    Artifact,
    Channel,
    Check,
    CheckResult,
    Company,
    Document,
    Employee,
    Identity,
    LedgerEntry,
    Meeting,
    Memory,
    MemoryBlock,
    Message,
    Project,
    Role,
    Run,
    RunStep,
    Source,
    ToolCall,
    WorkItem,
    WorkItemComment,
)
from services import pricing


def iso(value) -> str | None:
    return value.isoformat() if value else None


def company(row: Company, stats: dict | None = None) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "slug": row.slug,
        "tagline": row.tagline,
        "description": row.description,
        "industry": row.industry,
        "mission": row.mission,
        "handbook": row.handbook,
        "pack_key": row.pack_key,
        "departments": row.departments or [],
        "work_item_kinds": row.work_item_kinds or [],
        "settings": row.settings or {},
        "halted": row.halted,
        "halt_reason": row.halt_reason,
        "created_at": iso(row.created_at),
        "stats": stats or {},
    }


def employee(row: Employee, identities: list[Identity] | None = None) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "name": row.name,
        "title": row.title,
        "department": row.department,
        "seniority": row.seniority,
        "role_key": row.role_key,
        "persona": row.persona,
        "skills": row.skills or [],
        "toolbelt": row.toolbelt or [],
        "manager_id": row.manager_id,
        "status": row.status,
        "status_note": row.status_note,
        "avatar": row.avatar,
        "capabilities": row.capabilities or [],
        "model_policy": row.model_policy or {},
        "model": row.model,
        "autonomy_level": row.autonomy_level,
        "budget_daily_micros": row.budget_daily_micros,
        "api_enabled": row.api_enabled,
        "created_at": iso(row.created_at),
        "accounts": [
            {"tool": i.tool, "username": i.username, "last_used_at": i.last_used_at}
            for i in (identities if identities is not None else row.identities)
        ],
    }


def project(row: Project, counts: dict | None = None) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "name": row.name,
        "key": row.key,
        "brief": row.brief,
        "status": row.status,
        "lead_id": row.lead_id,
        "verify_command": row.verify_command,
        "preview": row.preview or {},
        "created_at": iso(row.created_at),
        "counts": counts or {},
    }


def work_item(row: WorkItem, comments: list[WorkItemComment] | None = None) -> dict:
    data = {
        "id": row.id,
        "project_id": row.project_id,
        "key": row.key,
        "title": row.title,
        "description": row.description,
        "kind": row.kind,
        # Kept while the board still speaks in ticket types.
        "type": row.kind,
        "status": row.status,
        "priority": row.priority,
        "assignee_id": row.assignee_id,
        "reporter_id": row.reporter_id,
        "role_hint": row.role_hint,
        "acceptance_criteria": row.acceptance_criteria or [],
        "capability_hint": row.capability_hint,
        "depends_on": row.depends_on or [],
        "deliverable_spec": row.deliverable_spec or {},
        "approval_required": row.approval_required,
        "blocked_reason": row.blocked_reason,
        "rework_count": row.rework_count,
        "closed_at": iso(row.closed_at),
        "order": row.order,
        "result": row.result,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if comments is not None:
        data["comments"] = [
            {
                "id": c.id,
                "author_id": c.author_id,
                "author_label": c.author_label,
                "body": c.body,
                "created_at": iso(c.created_at),
            }
            for c in comments
        ]
    return data


def activity(row: Activity) -> dict:
    return {
        "seq": row.seq,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "run_id": row.run_id,
        "employee_id": row.employee_id,
        "actor": row.actor,
        "kind": row.kind,
        "summary": row.summary,
        "payload": row.payload or {},
        "created_at": iso(row.created_at),
    }


def run(row: Run) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "brief": row.brief,
        "status": row.status,
        "phase": row.phase,
        "error": row.error,
        "stats": row.stats or {},
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def run_step(row: RunStep) -> dict:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "employee_id": row.employee_id,
        "work_item_id": row.work_item_id,
        "kind": row.kind,
        "reasoning": row.reasoning,
        "output": row.output,
        "tool_calls": row.tool_calls or [],
        "status": row.status,
        "created_at": iso(row.created_at),
    }


def document(row: Document, include_body: bool = True) -> dict:
    data = {
        "id": row.id,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "space": row.space,
        "title": row.title,
        "slug": row.slug,
        "parent_id": row.parent_id,
        "author_id": row.author_id,
        "version": row.version,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if include_body:
        data["body"] = row.body
    return data


def channel(row: Channel, unread: int = 0) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "name": row.name,
        "purpose": row.purpose,
        "kind": row.kind,
        "messages": unread,
    }


def message(row: Message) -> dict:
    return {
        "id": row.id,
        "channel_id": row.channel_id,
        "author_id": row.author_id,
        "author_label": row.author_label,
        "body": row.body,
        "mentions": row.mentions or [],
        "created_at": iso(row.created_at),
    }


# --------------------------------------------------------------------------
# v2 records
# --------------------------------------------------------------------------


def agent_task(row: AgentTask, full: bool = False) -> dict:
    data = {
        "id": row.id,
        "company_id": row.company_id,
        "employee_id": row.employee_id,
        "source": row.source,
        "kind": row.kind,
        "status": row.status,
        "run_id": row.run_id,
        "work_item_id": row.work_item_id,
        "created_by": row.created_by,
        "priority": row.priority,
        "attempts": row.attempts,
        "lease_until": iso(row.lease_until),
        "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at),
        "error": row.error,
        "created_at": iso(row.created_at),
    }
    if full:
        data["request"] = row.request or {}
        data["result"] = row.result or {}
    return data


def agent_token(row: AgentToken) -> dict:
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "name": row.name,
        # Enough to recognise it, not enough to use it.
        "prefix": f"edn_{row.prefix}_…",
        "scopes": row.scopes or [],
        "created_by": row.created_by,
        "expires_at": iso(row.expires_at),
        "last_used_at": iso(row.last_used_at),
        "revoked_at": iso(row.revoked_at),
        "active": row.revoked_at is None,
        "created_at": iso(row.created_at),
    }


def memory_block(row: MemoryBlock) -> dict:
    return {
        "id": row.id,
        "label": row.label,
        "content": row.content,
        "char_limit": row.char_limit,
        "chars": len(row.content or ""),
        "pinned": row.pinned,
        "version": row.version,
        "updated_by": row.updated_by,
        "updated_at": iso(row.updated_at),
    }


def memory(row: Memory, score: float | None = None, similarity: float | None = None) -> dict:
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "kind": row.kind,
        "scope": row.scope,
        "title": row.title,
        "body": row.body,
        "outcome": row.outcome,
        "confidence": round(row.confidence, 3),
        "uses": row.uses,
        "used_by": row.used_by or [],
        "tags": row.tags or [],
        "source_kind": row.source_kind,
        "source_id": row.source_id,
        "superseded_by": row.superseded_by,
        "archived_at": iso(row.archived_at),
        "has_embedding": row.embedding is not None,
        "last_used_at": iso(row.last_used_at),
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
        "score": round(score, 4) if score is not None else None,
        "similarity": round(similarity, 4) if similarity is not None else None,
    }


def artifact(row: Artifact, content: str | None = None) -> dict:
    data = {
        "id": row.id,
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "kind": row.kind,
        "name": row.name,
        "title": row.title,
        "storage": row.storage,
        "locator": row.locator,
        "version": row.version,
        "content_hash": row.content_hash,
        "size_bytes": row.size_bytes,
        "produced_by": row.produced_by,
        "superseded_by": row.superseded_by,
        "meta": row.meta or {},
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if content is not None:
        data["content"] = content
    return data


def check(row: Check) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "artifact_kind": row.artifact_kind,
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "spec": row.spec or {},
        "required": row.required,
        "enabled": row.enabled,
        "position": row.position,
        "created_by": row.created_by,
    }


def check_result(row: CheckResult) -> dict:
    return {
        "id": row.id,
        "check_id": row.check_id,
        "check_key": row.check_key,
        "check_kind": row.check_kind,
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "artifact_id": row.artifact_id,
        "run_id": row.run_id,
        "status": row.status,
        "score": row.score,
        "detail": row.detail,
        "evidence": row.evidence or {},
        "duration_ms": row.duration_ms,
        "created_at": iso(row.created_at),
    }


def approval(row: Approval) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "subject_kind": row.subject_kind,
        "subject_id": row.subject_id,
        "requested_by": row.requested_by,
        "requested_label": row.requested_label,
        "title": row.title,
        "reason": row.reason,
        "capability": row.capability,
        "status": row.status,
        "decided_by": row.decided_by,
        "decided_at": iso(row.decided_at),
        "note": row.note,
        "payload": row.payload or {},
        "created_at": iso(row.created_at),
    }


def agent_message(row: AgentMessage) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "from_id": row.from_id,
        "from_label": row.from_label,
        "to_id": row.to_id,
        "work_item_id": row.work_item_id,
        "thread_id": row.thread_id,
        "hops": row.hops,
        "subject": row.subject,
        "body": row.body,
        "payload": row.payload or {},
        "read_at": iso(row.read_at),
        "handled_at": iso(row.handled_at),
        "created_at": iso(row.created_at),
    }


def meeting(row: Meeting) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "kind": row.kind,
        "title": row.title,
        "attendees": row.attendees or [],
        "outcome": row.outcome or {},
        "status": row.status,
        "transcript": row.transcript,
        "started_at": iso(row.started_at),
        "ended_at": iso(row.ended_at),
        "created_at": iso(row.created_at),
    }


def ledger_entry(row: LedgerEntry) -> dict:
    return {
        "seq": row.seq,
        "height": row.height,
        "company_id": row.company_id,
        "project_id": row.project_id,
        "prev_hash": row.prev_hash,
        "hash": row.hash,
        "kind": row.kind,
        "actor_id": row.actor_id,
        "actor_label": row.actor_label,
        "subject_kind": row.subject_kind,
        "subject_id": row.subject_id,
        "payload": row.payload or {},
        "at": iso(row.at),
    }


def role(row: Role) -> dict:
    return {
        "id": row.id,
        "key": row.key,
        "title": row.title,
        "department": row.department,
        "avatar": row.avatar,
        "summary": row.summary,
        "persona": row.persona,
        "skills": row.skills or [],
        "toolbelt": row.toolbelt or [],
        "capabilities": row.capabilities or [],
        "manages": row.manages,
        "position": row.position,
    }


def tool_call(row: ToolCall, employee_label: str = "") -> dict:
    # `group` and `blocked_reason` are derived rather than stored. The audit
    # table records what happened; which group a tool belongs to is a property
    # of the registry, and "was this refused by policy" is a reading of the
    # error. Both are what the ops page shows, so they are computed once here
    # instead of in the browser.
    from agents.tools import BY_NAME

    tool = BY_NAME.get(row.tool)
    refused = bool(
        not row.ok
        and row.error
        and any(
            phrase in row.error
            for phrase in (
                "not on this company's allow-list",
                "is not available for the rest of this turn",
                "does not have access to",
                "is halted",
                "never fetchable",
            )
        )
    )
    return {
        "id": row.id,
        "employee_id": row.employee_id,
        "employee_label": employee_label or "Someone",
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "run_id": row.run_id,
        "task_id": row.task_id,
        "tool": row.tool,
        "group": tool.group if tool else "",
        "arguments": row.arguments or {},
        "ok": row.ok,
        "error": row.error,
        # Refused by a rule, as opposed to attempted and failed. The difference
        # matters: one is the platform working, the other is something broken.
        "blocked_reason": row.error if refused else None,
        "result_preview": row.result_preview,
        "duration_ms": row.duration_ms,
        "created_at": iso(row.created_at),
    }


def source(row: Source) -> dict:
    return {
        "id": row.id,
        "short_id": row.id[:8],
        "url": row.url,
        "title": row.title,
        "content_hash": row.content_hash,
        "chars": row.chars,
        "project_id": row.project_id,
        "work_item_id": row.work_item_id,
        "meta": row.meta or {},
        "created_at": iso(row.created_at),
    }


def cost(micros: float) -> dict:
    """Money is always shown with the fact that it is an estimate attached."""
    return {"micros": round(micros, 3), "display": pricing.format_cost(micros), "estimated": True}


def authored_tool(row) -> dict:
    return {
        "id": row.id,
        "company_id": row.company_id,
        "author_id": row.author_id,
        "author_label": row.author_label,
        "name": row.name,
        "description": row.description,
        "rationale": row.rationale,
        "parameters": row.parameters or {},
        "expression": row.expression,
        "examples": row.examples or [],
        "status": row.status,
        "review_note": row.review_note,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": iso(row.reviewed_at),
        "uses": row.uses,
        "last_used_at": iso(row.last_used_at),
        "created_at": iso(row.created_at),
    }
