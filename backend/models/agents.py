"""What makes an employee an addressable agent: tokens, tasks and usage."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin

# What a token is allowed to do. `tools:<group>` grants one tool group.
SCOPES = [
    "agent:message",
    "agent:task",
    "agent:read",
    "memory:read",
    "memory:write",
    "tools:*",
]

TASK_STATUSES = ["queued", "leased", "running", "done", "failed", "cancelled", "blocked"]


class AgentToken(Base, IdMixin, TimestampMixin):
    """An API key for one employee. Presented as `edn_<prefix>_<secret>`.

    Only the digest is stored: the full token is shown once, at mint time.
    """

    __tablename__ = "agent_tokens"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), default="default")
    # Indexed lookup handle. Not a secret.
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    digest: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(120), default="You")

    employee: Mapped["Employee"] = relationship()  # noqa: F821


class AgentTask(Base, IdMixin, TimestampMixin):
    """A unit of work addressed to one agent, from any source.

    A run is one source among several; the API and the org clock are others.
    """

    __tablename__ = "agent_tasks"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # api | run | clock | message | meeting | autofix
    source: Mapped[str] = mapped_column(String(30), default="api")
    kind: Mapped[str] = mapped_column(String(40), default="work")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    work_item_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(120), default="You")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # Set while a worker holds the task; a stale lease is reclaimed by the clock.
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)


class UsageEvent(Base, IdMixin):
    """One model call, with what it cost.

    Tokens are measured; the cost figure is derived from a configurable rate
    table, so the UI labels it an estimate rather than a bill.
    """

    __tablename__ = "usage_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    # chat | structured | embed | stream
    kind: Mapped[str] = mapped_column(String(20), default="chat")
    purpose: Mapped[str | None] = mapped_column(String(40))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(default=True)
