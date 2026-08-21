"""Projects and the ticket tracker the AI employees work through."""

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin

TICKET_STATUSES = ["backlog", "todo", "in_progress", "in_review", "done", "blocked"]
TICKET_TYPES = ["epic", "story", "task", "bug", "chore"]


class Project(Base, IdMixin, TimestampMixin):
    __tablename__ = "projects"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    brief: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="planning")
    lead_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    repo_path: Mapped[str | None] = mapped_column(String(255))
    ticket_counter: Mapped[int] = mapped_column(Integer, default=0)

    company: Mapped["Company"] = relationship(back_populates="projects")  # noqa: F821
    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Ticket(Base, IdMixin, TimestampMixin):
    __tablename__ = "tickets"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(20), default="task")
    status: Mapped[str] = mapped_column(String(20), default="backlog", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    reporter_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"))
    # Role this work needs, so the planner can assign without knowing names.
    role_hint: Mapped[str | None] = mapped_column(String(60))
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    order: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="tickets")
    comments: Mapped[list["TicketComment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )


class TicketComment(Base, IdMixin, TimestampMixin):
    __tablename__ = "ticket_comments"

    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    author_label: Mapped[str] = mapped_column(String(120), default="You")
    body: Mapped[str] = mapped_column(Text, nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")
