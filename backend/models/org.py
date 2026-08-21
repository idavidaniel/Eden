"""Companies, their AI employees, and the credentials those employees hold."""

from typing import Optional

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Company(Base, IdMixin, TimestampMixin):
    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    tagline: Mapped[str | None] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(80))
    mission: Mapped[str | None] = mapped_column(Text)
    # Anything the whole company should know: policies, tone, domain facts.
    handbook: Mapped[str | None] = mapped_column(Text)

    employees: Mapped[list["Employee"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        back_populates="company", cascade="all, delete-orphan"
    )


class Employee(Base, IdMixin, TimestampMixin):
    """An AI employee: a persona, a role, a reporting line and a set of tools."""

    __tablename__ = "employees"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="General")
    seniority: Mapped[str] = mapped_column(String(40), default="Mid")
    role_key: Mapped[str] = mapped_column(String(60), default="generalist")
    persona: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    # Tool keys this employee is allowed to use (workspace, tracker, wiki, chat...).
    toolbelt: Mapped[list] = mapped_column(JSON, default=list)
    manager_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="idle")
    status_note: Mapped[str | None] = mapped_column(String(240))
    model: Mapped[str | None] = mapped_column(String(120))
    avatar: Mapped[str] = mapped_column(String(20), default="🤖")

    company: Mapped[Company] = relationship(back_populates="employees")
    reports: Mapped[list["Employee"]] = relationship(
        back_populates="manager", remote_side="Employee.manager_id"
    )
    manager: Mapped[Optional["Employee"]] = relationship(
        back_populates="reports", remote_side="Employee.id"
    )
    identities: Mapped[list["Identity"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )


class Identity(Base, IdMixin, TimestampMixin):
    """A per-employee service account: username, password and API token per tool."""

    __tablename__ = "identities"

    employee_id: Mapped[str] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool: Mapped[str] = mapped_column(String(40), nullable=False)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    # scrypt hash for verification; the sealed copy backs the reveal-in-UI flow.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_sealed: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_sealed: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(String(40))

    employee: Mapped[Employee] = relationship(back_populates="identities")


class Connection(Base, IdMixin, TimestampMixin):
    """How a tool is backed for a company: the built-in module, or an external SaaS."""

    __tablename__ = "connections"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tool: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="builtin")
    base_url: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_sealed: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="connected")
