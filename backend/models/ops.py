"""Operational records: the activity feed and autonomous run history."""

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, BigSerial, IdMixin, TimestampMixin


class Activity(Base, TimestampMixin):
    """Append-only event log. `seq` gives the live feed a stable cursor."""

    __tablename__ = "activities"

    seq: Mapped[int] = mapped_column(BigSerial, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    actor: Mapped[str] = mapped_column(String(120), default="System")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class Run(Base, IdMixin, TimestampMixin):
    """One autonomous execution of a project brief by the company."""

    __tablename__ = "runs"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    brief: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(40), default="planning")
    error: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)

    steps: Mapped[list["RunStep"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunStep(Base, IdMixin, TimestampMixin):
    """One employee's turn inside a run, with its reasoning and tool calls."""

    __tablename__ = "run_steps"

    # Nullable because an employee is addressable on its own: a turn started
    # through `/agents/{id}/messages` belongs to nobody's run.
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL"), index=True
    )
    employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(40), default="work")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    output: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="done")

    run: Mapped[Run | None] = relationship(back_populates="steps")
