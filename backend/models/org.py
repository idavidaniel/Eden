"""Companies, their AI employees, and the credentials those employees hold."""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Company(Base, IdMixin, TimestampMixin):
    __tablename__ = "companies"

    # Who owns this. Every read of a company checks it against the caller's
    # tenant; without this column the sign-in screen would be decoration.
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    tagline: Mapped[str | None] = mapped_column(String(240))
    description: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(String(80))
    mission: Mapped[str | None] = mapped_column(Text)
    # Anything the whole company should know: policies, tone, domain facts.
    handbook: Mapped[str | None] = mapped_column(Text)
    # Which industry pack shaped this company's roles, artifacts and checks.
    pack_key: Mapped[str] = mapped_column(String(60), default="software_studio")
    departments: Mapped[list] = mapped_column(JSON, default=list)
    # Vocabulary for work: ["task","bug"] for software, ["matter","filing"] for law.
    work_item_kinds: Mapped[list] = mapped_column(JSON, default=list)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    # One switch that stops every agent in this company from acting.
    halted: Mapped[bool] = mapped_column(default=False)
    halt_reason: Mapped[str | None] = mapped_column(String(240))

    employees: Mapped[list["Employee"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(  # noqa: F821
        back_populates="company", cascade="all, delete-orphan"
    )
    roles: Mapped[list["Role"]] = relationship(
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

    # --- the employee as an addressable agent ---------------------------
    # What this person can be asked to do. The planner assigns on capability,
    # not on a role name, which is what lets a law firm exist at all.
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    # {"default": "...", "plan": "...", "review": "...", "embed": "..."}
    model_policy: Mapped[dict] = mapped_column(JSON, default=dict)
    # supervised: every destructive action needs you. autonomous: none do.
    autonomy_level: Mapped[str] = mapped_column(String(20), default="standard")
    # Millionths of a dollar. 0 means no ceiling.
    budget_daily_micros: Mapped[int] = mapped_column(Integer, default=0)
    api_enabled: Mapped[bool] = mapped_column(default=True)
    # Set while a task holds this employee; the clock reclaims a stale one.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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


class Role(Base, IdMixin, TimestampMixin):
    """A hireable role at one company, seeded from an industry pack.

    Roles used to be a hardcoded list of nine software jobs. They are rows now,
    because a law firm needs a Managing Partner and no amount of renaming makes
    "Backend Engineer" into one.
    """

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_role_company_key"),)

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    department: Mapped[str] = mapped_column(String(80), default="General")
    avatar: Mapped[str] = mapped_column(String(20), default="🤖")
    summary: Mapped[str] = mapped_column(String(300), default="")
    persona: Mapped[str] = mapped_column(Text, default="")
    skills: Mapped[list] = mapped_column(JSON, default=list)
    toolbelt: Mapped[list] = mapped_column(JSON, default=list)
    # What work this role can be assigned. The planner matches on these.
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    keywords: Mapped[list] = mapped_column(JSON, default=list)
    manages: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(Integer, default=100)

    company: Mapped[Company] = relationship(back_populates="roles")


class ArtifactKind(Base, IdMixin, TimestampMixin):
    """A shape of deliverable this company produces, and how it is checked."""

    __tablename__ = "artifact_kinds"
    __table_args__ = (UniqueConstraint("company_id", "key", name="uq_artifact_kind_company_key"),)

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    storage: Mapped[str] = mapped_column(String(20), default="blob")
    # How the interface shows it: code | document | table | chart | image | data
    renderer: Mapped[str] = mapped_column(String(30), default="document")
    default_checks: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(String(300), default="")
