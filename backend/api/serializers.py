"""Model -> JSON shaping. One place so every route agrees on field names."""

from models import (
    Activity,
    Channel,
    Company,
    Document,
    Employee,
    Identity,
    Message,
    Project,
    Run,
    RunStep,
    Ticket,
    TicketComment,
)


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


def ticket(row: Ticket, comments: list[TicketComment] | None = None) -> dict:
    data = {
        "id": row.id,
        "project_id": row.project_id,
        "key": row.key,
        "title": row.title,
        "description": row.description,
        "type": row.type,
        "status": row.status,
        "priority": row.priority,
        "assignee_id": row.assignee_id,
        "reporter_id": row.reporter_id,
        "role_hint": row.role_hint,
        "acceptance_criteria": row.acceptance_criteria or [],
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
        "ticket_id": row.ticket_id,
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
