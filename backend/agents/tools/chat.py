"""Chat tools — how employees coordinate with each other and with the human."""

from sqlalchemy import select

from models import Channel, Message
from services import events

from .base import Tool, ToolContext, obj, string


def _channel(ctx: ToolContext, name: str) -> Channel | None:
    return ctx.db.scalar(
        select(Channel).where(
            Channel.company_id == ctx.company.id, Channel.name == name.lstrip("#")
        )
    )


def read_channel(ctx: ToolContext, channel: str = "general", limit: int = 20) -> str:
    target = _channel(ctx, channel)
    if not target:
        return f"No channel named #{channel}."
    messages = list(
        ctx.db.scalars(
            select(Message)
            .where(Message.channel_id == target.id)
            .order_by(Message.created_at.desc())
            .limit(min(limit, 50))
        )
    )
    if not messages:
        return f"#{target.name} is empty."
    return "\n".join(f"{m.author_label}: {m.body}" for m in reversed(messages))


def post_message(ctx: ToolContext, body: str, channel: str = "general", mentions: str = "") -> str:
    target = _channel(ctx, channel)
    if not target:
        target = Channel(company_id=ctx.company.id, name=channel.lstrip("#"), purpose="")
        ctx.db.add(target)
        ctx.db.flush()
    mention_list = [m.strip() for m in mentions.split(",") if m.strip()]
    ctx.db.add(
        Message(
            channel_id=target.id,
            author_id=ctx.employee.id,
            author_label=ctx.actor,
            body=body,
            mentions=mention_list,
        )
    )
    events.record(
        ctx.db,
        company_id=ctx.company.id,
        project_id=ctx.project.id if ctx.project else None,
        run_id=ctx.run.id if ctx.run else None,
        employee_id=ctx.employee.id,
        actor=ctx.actor,
        kind="chat.message",
        summary=f"#{target.name}: {body[:160]}",
        payload={"channel": target.name, "channel_id": target.id, "body": body[:500]},
    )
    return f"Posted to #{target.name}."


TOOLS = [
    Tool(
        name="read_channel",
        group="chat",
        description="Read recent messages in a team channel.",
        parameters=obj(
            {"channel": string("Channel name, e.g. general"), "limit": {"type": "integer"}},
            required=[],
        ),
        handler=read_channel,
    ),
    Tool(
        name="post_message",
        group="chat",
        description="Post a message to a team channel so colleagues (and the human) can see it.",
        parameters=obj(
            {
                "body": string("Message text"),
                "channel": string("Channel name, default 'general'"),
                "mentions": string("Comma-separated colleague names to notify"),
            },
            required=["body"],
        ),
        handler=post_message,
    ),
]
