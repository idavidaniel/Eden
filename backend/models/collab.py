"""How the organisation coordinates: messages, meetings and the approvals you owe it.

A run used to be the only thing that could make an agent act. These tables are
the other ways: a colleague asks, a meeting produces an action item, or work
stops because it needs a human.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin

MESSAGE_KINDS = ["request", "accept", "decline", "deliver", "question", "escalate", "note"]
APPROVAL_STATUSES = ["pending", "approved", "rejected", "expired"]
MEETING_KINDS = ["standup", "planning", "design_review", "retro"]

# A request that has bounced this many times stops bouncing and asks a human.
MAX_HOPS = 6


class AgentMessage(Base, IdMixin, TimestampMixin):
    """One agent addressing another, with a bounded conversation.

    Chat is for humans to read. This is the protocol: typed, threaded, and hop-
    counted, because two agents politely deferring to each other forever is a
    real failure mode and not a funny one when it costs money.
    """

    __tablename__ = "agent_messages"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    from_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    from_label: Mapped[str] = mapped_column(String(160), default="You")
    to_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    replies_to: Mapped[str | None] = mapped_column(String(36))
    hops: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class Approval(Base, IdMixin, TimestampMixin):
    """Something waiting on a person. The lease stays blocked until it is decided."""

    __tablename__ = "approvals"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    work_item_id: Mapped[str | None] = mapped_column(String(36), index=True)
    # tool_call | check | budget | work_item | connection
    subject_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    requested_by: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL")
    )
    requested_label: Mapped[str] = mapped_column(String(160), default="System")
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")
    # When an employee with this capability may decide instead of you.
    capability: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    decided_by: Mapped[str] = mapped_column(String(160), default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Meeting(Base, IdMixin, TimestampMixin):
    """A meeting that has to produce something, or it did not happen."""

    __tablename__ = "meetings"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(240), default="")
    attendees: Mapped[list] = mapped_column(JSON, default=list)
    transcript: Mapped[str] = mapped_column(Text, default="")
    # {decisions: [], action_items: [{owner, what, due}], risks: []}
    outcome: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
