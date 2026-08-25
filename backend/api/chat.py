"""Team chat. Messages the human sends can be answered by an employee."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from agents import engine
from agents.tools.base import ToolContext
from db import get_db, session
from models import Channel, Employee, Message, Project
from services import events

from . import lookups, serializers
from .companies import get_company

log = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChannelIn(BaseModel):
    name: str
    purpose: str = ""


class MessageIn(BaseModel):
    body: str
    # Ask a specific employee to answer; otherwise an @mention decides.
    reply_from: str | None = None


def _mentioned_employee(db: Session, company_id: str, body: str) -> Employee | None:
    if "@" not in body:
        return None
    people = list(db.scalars(select(Employee).where(Employee.company_id == company_id)))
    lowered = body.lower()
    for person in people:
        first = person.name.split()[0].lower()
        if f"@{person.name.lower()}" in lowered or f"@{first}" in lowered:
            return person
    return None


def _reply_in_background(company_id: str, channel_id: str, employee_id: str, question: str) -> None:
    db = session()
    try:
        employee = db.get(Employee, employee_id)
        channel = lookups.channel(db, channel_id)
        if not employee or not channel:
            return
        project = db.get(Project, channel.project_id) if channel.project_id else None
        employee.status = "working"
        employee.status_note = f"replying in #{channel.name}"
        db.add(employee)
        db.commit()

        ctx = ToolContext(db=db, company=employee.company, employee=employee, project=project)
        history = "\n".join(
            f"{m.author_label}: {m.body}"
            for m in reversed(
                list(
                    db.scalars(
                        select(Message)
                        .where(Message.channel_id == channel.id)
                        .order_by(Message.created_at.desc())
                        .limit(15)
                    )
                )
            )
        )
        engine.run_agent_turn(
            db,
            ctx,
            f"""You were asked something in #{channel.name}.

Recent conversation:
{history}

The latest message is for you: "{question}"

Answer it. Use post_message to reply in #{channel.name} (that is how the person
sees your answer). If it implies work, create or update work_items too. Keep it short.""",
            kind="chat",
            max_steps=6,
        )
        employee.status = "idle"
        employee.status_note = None
        db.add(employee)
        db.commit()
    except Exception:
        log.exception("chat reply failed")
        db.rollback()
    finally:
        db.close()


@router.get("/companies/{company_id}/channels")
def list_channels(company_id: str, db: Session = Depends(get_db)):
    get_company(db, company_id)
    rows = list(
        db.scalars(select(Channel).where(Channel.company_id == company_id).order_by(Channel.name))
    )
    return [serializers.channel(row) for row in rows]


@router.post("/companies/{company_id}/channels", status_code=201)
def create_channel(company_id: str, payload: ChannelIn, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    channel = Channel(company_id=company.id, name=payload.name.lstrip("#"), purpose=payload.purpose)
    db.add(channel)
    db.commit()
    return serializers.channel(channel)


@router.get("/channels/{channel_id}/messages")
def list_messages(channel_id: str, limit: int = Query(100, le=300), db: Session = Depends(get_db)):
    channel = lookups.channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found.")
    rows = list(
        db.scalars(
            select(Message)
            .where(Message.channel_id == channel.id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    )
    return [serializers.message(row) for row in reversed(rows)]


@router.post("/channels/{channel_id}/messages", status_code=201)
def post_message(channel_id: str, payload: MessageIn, db: Session = Depends(get_db)):
    channel = lookups.channel(db, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found.")

    message = Message(channel_id=channel.id, author_label="You", body=payload.body)
    db.add(message)
    events.record(
        db,
        company_id=channel.company_id,
        project_id=channel.project_id,
        actor="You",
        kind="chat.message",
        summary=f"#{channel.name}: {payload.body[:160]}",
        payload={"channel": channel.name, "channel_id": channel.id, "body": payload.body[:500]},
    )

    responder = (
        db.get(Employee, payload.reply_from)
        if payload.reply_from
        else _mentioned_employee(db, channel.company_id, payload.body)
    )
    db.commit()

    if responder:
        engine.get_executor().submit(
            _reply_in_background, channel.company_id, channel.id, responder.id, payload.body
        )

    return {
        **serializers.message(message),
        "replying": serializers.employee(responder) if responder else None,
    }
