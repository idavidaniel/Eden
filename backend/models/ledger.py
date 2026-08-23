"""The work ledger: a hash chain over everything that decides whether work is real.

One chain per company. Each entry commits to the entry before it, so a check
result cannot be back-dated or a failing verdict quietly rewritten. The chain
covers artifact content hashes rather than artifact bodies, which keeps entries
small while still pinning exactly what was delivered.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, BigSerial

GENESIS_HASH = "0" * 64

# Kinds worth committing to the chain. Anything not here is ordinary activity.
LEDGER_KINDS = [
    "brief.accepted",
    "plan.produced",
    "item.assigned",
    "item.closed",
    "tool.called",
    "artifact.version",
    "check.result",
    "approval.decided",
    "memory.promoted",
    "token.minted",
    "token.revoked",
]


class LedgerEntry(Base):
    __tablename__ = "ledger"
    # One chain per company: two entries can never claim the same position.
    __table_args__ = (UniqueConstraint("company_id", "height", name="uq_ledger_company_height"),)

    seq: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    # Position in this company's chain, 0-based. Unique with company_id.
    height: Mapped[int] = mapped_column(nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    actor_label: Mapped[str] = mapped_column(String(160), default="System")
    subject_kind: Mapped[str | None] = mapped_column(String(40))
    subject_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
