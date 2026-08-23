"""Agents addressing each other, and asking a human when they are stuck.

Chat is where humans read along. This is the protocol underneath: typed
messages, one thread, a hop counter. Two agents deferring to each other forever
is a real failure mode, so a thread that has bounced too many times escalates to
a manager and then to you rather than continuing politely.
"""

from sqlalchemy import select

from models import AgentMessage, Employee
from models.base import new_id
from models.collab import MAX_HOPS
from services import inbox

from .base import Tool, ToolContext, ToolResult, failed, obj, string


def _colleague(ctx: ToolContext, name: str) -> Employee | None:
    people = list(
        ctx.db.scalars(select(Employee).where(Employee.company_id == ctx.company.id))
    )
    lowered = (name or "").strip().lower()
    exact = next((p for p in people if p.name.lower() == lowered), None)
    if exact:
        return exact
    return next((p for p in people if lowered and lowered in p.name.lower()), None) or next(
        (p for p in people if lowered and lowered in p.title.lower()), None
    )


def send_to_colleague(
    ctx: ToolContext, to: str, kind: str, subject: str, body: str
) -> ToolResult:
    recipient = _colleague(ctx, to)
    if not recipient:
        names = ", ".join(
            person.name
            for person in ctx.db.scalars(
                select(Employee).where(Employee.company_id == ctx.company.id)
            )
        )
        return failed(f"Nobody here is called '{to}'.", f"The team is: {names}.")
    if recipient.id == ctx.employee.id:
        return failed("You cannot send yourself work.", "Do it, or say why you cannot.")
    if kind not in {"request", "question", "deliver", "escalate", "note"}:
        return failed(
            f"'{kind}' is not a message kind.",
            "Use request, question, deliver, escalate or note.",
        )

    thread = inbox.current_thread(
        ctx.db, ctx.employee.id, ctx.work_item.id if ctx.work_item else None
    )
    hops = thread["hops"] + 1 if thread else 0
    if hops >= MAX_HOPS:
        escalated = inbox.escalate(
            ctx.db,
            company=ctx.company,
            from_employee=ctx.employee,
            work_item=ctx.work_item,
            thread_id=thread["thread_id"] if thread else new_id(),
            reason=f"This request has been passed around {hops} times without being done.",
        )
        return ToolResult(
            text=(
                "This has bounced between people too many times, so it has gone to "
                f"{escalated}. Do not pass it on again — do the part you can."
            ),
            ok=False,
        )

    message = inbox.send(
        ctx.db,
        company=ctx.company,
        sender=ctx.employee,
        recipient=recipient,
        kind=kind,
        subject=subject,
        body=body,
        work_item=ctx.work_item,
        thread_id=thread["thread_id"] if thread else None,
        hops=hops,
    )
    return ToolResult(
        text=(
            f"Sent to {recipient.name} ({kind}). They will pick it up on their next turn. "
            f"Thread {message.thread_id[:8]}, hop {hops + 1} of {MAX_HOPS}."
        )
    )


def read_inbox(ctx: ToolContext, limit: int = 10) -> ToolResult:
    messages = inbox.unread(ctx.db, ctx.employee.id, limit=min(int(limit or 10), 25))
    if not messages:
        return ToolResult(text="Your inbox is empty.")
    inbox.mark_read(ctx.db, messages)
    lines = [
        f"[{message.kind}] from {message.from_label}: {message.subject}\n    {message.body[:500]}"
        for message in messages
    ]
    return ToolResult(text="\n\n".join(lines))


HANDOFF_FIELDS = ["what_i_did", "where_it_is", "what_you_need_to_know", "what_i_could_not_do"]


def hand_off(
    ctx: ToolContext,
    to: str,
    what_i_did: str,
    where_it_is: str,
    what_you_need_to_know: str,
    what_i_could_not_do: str = "",
) -> ToolResult:
    """Pass work on with everything the next person needs, in one message.

    Without this the receiver re-reads the whole world to work out what changed,
    which is slow, expensive, and often wrong.
    """
    recipient = _colleague(ctx, to)
    if not recipient:
        return failed(f"Nobody here is called '{to}'.", "Call list_colleagues.")

    packet = {
        "what_i_did": what_i_did,
        "where_it_is": where_it_is,
        "what_you_need_to_know": what_you_need_to_know,
        "what_i_could_not_do": what_i_could_not_do or "(nothing outstanding)",
    }
    body = "\n".join(
        f"{field.replace('_', ' ').capitalize()}: {packet[field]}" for field in HANDOFF_FIELDS
    )
    message = inbox.send(
        ctx.db,
        company=ctx.company,
        sender=ctx.employee,
        recipient=recipient,
        kind="deliver",
        subject=f"Handoff: {ctx.work_item.key if ctx.work_item else 'work'}",
        body=body,
        work_item=ctx.work_item,
        payload={"handoff": packet},
    )
    if ctx.work_item:
        ctx.work_item.assignee_id = recipient.id
        ctx.db.add(ctx.work_item)
    return ToolResult(
        text=f"Handed {ctx.work_item.key if ctx.work_item else 'the work'} to {recipient.name}.",
        meta={"message_id": message.id},
    )


def ask_human(ctx: ToolContext, question: str, why_it_is_blocking: str = "") -> ToolResult:
    approval = inbox.ask_human(
        ctx.db,
        company=ctx.company,
        employee=ctx.employee,
        work_item=ctx.work_item,
        question=question,
        reason=why_it_is_blocking,
    )
    return ToolResult(
        text=(
            "Asked the human. This is now in their queue and your work item is blocked "
            "until they answer. Do the parts that do not depend on the answer."
        ),
        meta={"approval_id": approval.id},
    )


TOOLS = [
    Tool(
        name="send_to_colleague",
        group="protocol",
        description=(
            "Send a typed message to one colleague: request (asking them to do "
            "something), question, deliver, escalate, or note. It reaches their inbox "
            "and wakes them up; it is not chat."
        ),
        parameters=obj(
            {
                "to": string("Colleague's name"),
                "kind": string("request, question, deliver, escalate or note"),
                "subject": string("One line"),
                "body": string("What you need, specifically"),
            }
        ),
        handler=send_to_colleague,
    ),
    Tool(
        name="read_inbox",
        group="protocol",
        description="Read messages colleagues have sent you.",
        parameters=obj({"limit": {"type": "integer"}}, required=[]),
        read_only=True,
        handler=read_inbox,
    ),
    Tool(
        name="hand_off",
        group="protocol",
        description=(
            "Hand your work item to a colleague with everything they need: what you "
            "did, where it is, what they need to know, and what you could not do. "
            "This reassigns the item."
        ),
        parameters=obj(
            {
                "to": string("Colleague's name"),
                "what_i_did": string("Concretely, what you completed"),
                "where_it_is": string("File names, deliverable names, branch"),
                "what_you_need_to_know": string("Decisions, gotchas, assumptions"),
                "what_i_could_not_do": string("What is still outstanding, and why"),
            },
            required=["to", "what_i_did", "where_it_is", "what_you_need_to_know"],
        ),
        handler=hand_off,
    ),
    Tool(
        name="ask_human",
        group="protocol",
        description=(
            "Ask the person who runs this company something only they can answer. Use "
            "it when you are genuinely blocked, not to check in — it stops your work item."
        ),
        parameters=obj(
            {
                "question": string("The question, in one or two sentences"),
                "why_it_is_blocking": string("What you cannot do until it is answered"),
            },
            required=["question"],
        ),
        handler=ask_human,
    ),
]


def unread_count(ctx: ToolContext) -> int:
    return len(inbox.unread(ctx.db, ctx.employee.id, limit=50))


def thread_of(db, message_id: str) -> list[AgentMessage]:
    message = db.get(AgentMessage, message_id)
    if not message:
        return []
    return list(
        db.scalars(
            select(AgentMessage)
            .where(AgentMessage.thread_id == message.thread_id)
            .order_by(AgentMessage.created_at)
        )
    )
