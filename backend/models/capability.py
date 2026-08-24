"""What an employee is allowed to reach, and a record of every time they did."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin


class ToolGrant(Base, IdMixin, TimestampMixin):
    """Permission to use one tool or tool group, held by an identity.

    Grants used to be implied by an employee's role. Making them rows means a
    grant can expire, be revoked, and be audited — and that a token can carry a
    narrower set than the person it belongs to.
    """

    __tablename__ = "tool_grants"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # A group ("workspace") or one tool ("run_command").
    target: Mapped[str] = mapped_column(String(60), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    granted_by: Mapped[str] = mapped_column(String(120), default="You")
    reason: Mapped[str] = mapped_column(String(240), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolCall(Base, IdMixin):
    """Every tool call an employee made. Arguments are redacted before storage."""

    __tablename__ = "tool_calls"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    work_item_id: Mapped[str | None] = mapped_column(String(36), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36))
    task_id: Mapped[str | None] = mapped_column(String(36), index=True)
    step_id: Mapped[str | None] = mapped_column(String(36))
    tool: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    arguments: Mapped[dict] = mapped_column(JSON, default=dict)
    ok: Mapped[bool] = mapped_column(default=True)
    error: Mapped[str | None] = mapped_column(Text)
    result_preview: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_micros: Mapped[float] = mapped_column(Float, default=0.0)


class McpServer(Base, IdMixin, TimestampMixin):
    """An external MCP server this company's agents may call.

    We were already an MCP server. This is the other half: a dead server
    degrades to "that tool is unavailable" rather than breaking a turn.
    """

    __tablename__ = "mcp_servers"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    protocol_version: Mapped[str] = mapped_column(String(30), default="")
    auth_sealed: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cached tool definitions from tools/list, so a turn does not pay for discovery.
    tools: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)


AUTHORED_TOOL_STATUSES = ["proposed", "approved", "rejected", "retired"]


class AuthoredTool(Base, IdMixin, TimestampMixin):
    """A tool an agent wrote for itself, which nobody may use until you say so.

    An agent that hits the same fiddly calculation on every third work item
    should be able to write it down once. But a tool is code that runs, so this
    is deliberately the narrowest possible version of that idea: the body is a
    single expression evaluated by the same AST-restricted evaluator that
    assertion checks use — no imports, no attribute access, no I/O — and it
    stays unusable until a person approves it.

    The gate is not ceremony. An agent that could write and immediately run its
    own tools could do anything the process was designed to stop.
    """

    __tablename__ = "authored_tools"
    __table_args__ = (UniqueConstraint("company_id", "name", name="uq_authored_tool_name"),)

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    author_label: Mapped[str] = mapped_column(String(160), default="")
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(400), default="")
    # Why it exists — what the agent kept having to do by hand.
    rationale: Mapped[str] = mapped_column(Text, default="")
    # Named inputs, each with a type the caller must satisfy.
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    # One expression, evaluated by services.checks.expressions.
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    # Worked examples the author claims. Every one is run before approval.
    examples: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
    reviewed_by: Mapped[str | None] = mapped_column(String(160))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uses: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
