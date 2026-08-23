"""What an employee remembers.

Two shapes. Core blocks are short, always in context, and the agent edits them
itself — persona, company, current focus, and what it knows about you. Everything
else is a `Memory` row retrieved by similarity, because there will eventually be
thousands and only a handful belong in any given turn.

Kinds share one table because they share one retrieval path; separating them
would mean four vector indexes and four queries to assemble one prompt.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TimestampMixin, Vector

# Blocks every agent has. `human` is what this employee knows about you.
BLOCK_LABELS = ["persona", "company", "focus", "human"]
BLOCK_LIMITS = {"persona": 2000, "company": 2000, "focus": 1200, "human": 1200}

MEMORY_KINDS = ["episode", "fact", "procedure"]
MEMORY_SCOPES = ["private", "team", "company"]
# How a piece of work turned out. Failures are retrieved preferentially.
OUTCOMES = ["shipped", "rejected", "reopened", "abandoned", "neutral"]


class MemoryBlock(Base, IdMixin, TimestampMixin):
    __tablename__ = "memory_blocks"
    __table_args__ = (
        UniqueConstraint("employee_id", "label", name="uq_memory_block_employee_label"),
    )

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    char_limit: Mapped[int] = mapped_column(Integer, default=2000)
    # A pinned block cannot be rewritten by the agent, only by you.
    pinned: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[str] = mapped_column(String(120), default="System")


class Memory(Base, IdMixin, TimestampMixin):
    __tablename__ = "memories"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # NULL means it belongs to the company rather than to one person.
    employee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(20), default="private", index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list | None] = mapped_column(Vector())
    # Where this came from, so a memory can be traced back to the work that made it.
    source_kind: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(36), index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="neutral")
    confidence: Mapped[float] = mapped_column(Float, default=0.6)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    # Distinct agents whose passed work has used this, for promotion.
    used_by: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decay_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Set when a newer memory contradicts this one. Kept, not deleted.
    superseded_by: Mapped[str | None] = mapped_column(String(36))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(120), default="System")
