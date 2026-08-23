"""The work spine: projects, work items, the artifacts they produce, and the
checks the platform runs against them.

This is the generalisation that lets a company be something other than a
software team. A work item is not a ticket, an artifact is not a file, and
verification is not one shell command — but for a software studio they still are,
which is why nothing about the existing behaviour changes.
"""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin

WORK_ITEM_STATUSES = ["backlog", "todo", "in_progress", "in_review", "done", "blocked"]
# Kept under the old names because the tracker tool and the board still use them.
TICKET_STATUSES = WORK_ITEM_STATUSES
TICKET_TYPES = ["epic", "story", "task", "bug", "chore"]

OPEN_STATUSES = ["backlog", "todo", "in_progress"]

ARTIFACT_STORAGE = ["git", "blob", "rows", "external"]
CHECK_KINDS = ["command", "schema", "assertion", "citation", "rubric", "human"]
CHECK_STATUSES = ["pass", "fail", "error", "skipped", "pending"]


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
    # Kept so an upgrade changes nothing: on first use it becomes a `command`
    # check like any other, and the check framework takes over from there.
    verify_command: Mapped[str | None] = mapped_column(String(255))
    # Last web preview: {status, package, url, built_at, error}.
    preview: Mapped[dict] = mapped_column(JSON, default=dict)
    ticket_counter: Mapped[int] = mapped_column(Integer, default=0)

    company: Mapped["Company"] = relationship(back_populates="projects")  # noqa: F821
    work_items: Mapped[list["WorkItem"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class WorkItem(Base, IdMixin, TimestampMixin):
    """One piece of work someone can finish alone, in any industry."""

    __tablename__ = "work_items"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    key: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # Vocabulary comes from the industry pack: task/bug for software, matter or
    # drafting_task for a law firm.
    kind: Mapped[str] = mapped_column(String(40), default="task")
    status: Mapped[str] = mapped_column(String(20), default="backlog", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    assignee_id: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    reporter_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"))
    role_hint: Mapped[str | None] = mapped_column(String(60))
    # What the doer needs to be able to do. Assignment matches on this first.
    capability_hint: Mapped[str | None] = mapped_column(String(60))
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    # Keys of work items that must finish first. A graph, not a list.
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    # What finishing looks like: {"artifact_kind": "contract_draft", "count": 1}
    deliverable_spec: Mapped[dict] = mapped_column(JSON, default=dict)
    budget_tokens: Mapped[int] = mapped_column(Integer, default=0)
    approval_required: Mapped[bool] = mapped_column(default=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text)
    # Why it is blocked, when it is. Silence here was a real failure mode.
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped every time the item is reopened, so rework is measurable.
    rework_count: Mapped[int] = mapped_column(Integer, default=0)

    project: Mapped[Project] = relationship(back_populates="work_items")
    comments: Mapped[list["WorkItemComment"]] = relationship(
        back_populates="work_item", cascade="all, delete-orphan"
    )


class WorkItemComment(Base, IdMixin, TimestampMixin):
    __tablename__ = "work_item_comments"

    work_item_id: Mapped[str] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[str | None] = mapped_column(ForeignKey("employees.id", ondelete="SET NULL"))
    author_label: Mapped[str] = mapped_column(String(120), default="You")
    body: Mapped[str] = mapped_column(Text, nullable=False)

    work_item: Mapped[WorkItem] = relationship(back_populates="comments")


class Artifact(Base, IdMixin, TimestampMixin):
    """A deliverable, whatever form it takes.

    `content_hash` is the identity that matters: the ledger commits to it, and a
    finished project can be re-verified later against exactly these bytes.
    """

    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version", name="uq_artifact_name_version"),
    )

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="SET NULL"), index=True
    )
    # From the industry pack: source_file, contract_draft, research_memo, model…
    kind: Mapped[str] = mapped_column(String(60), default="file", index=True)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300))
    storage: Mapped[str] = mapped_column(String(20), default="blob")
    # Path in the workspace, blob key, table name or external URL.
    locator: Mapped[str] = mapped_column(String(500), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    produced_by: Mapped[str | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    superseded_by: Mapped[str | None] = mapped_column(String(36))
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


class Check(Base, IdMixin, TimestampMixin):
    """A rule the platform can apply without believing anybody.

    Scope widens as the fields go null: a check bound to one work item, to every
    artifact of a kind, to a project, or to the whole company.
    """

    __tablename__ = "checks"

    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    artifact_kind: Mapped[str | None] = mapped_column(String(60), index=True)
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    spec: Mapped[dict] = mapped_column(JSON, default=dict)
    required: Mapped[bool] = mapped_column(default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(default=True)
    created_by: Mapped[str] = mapped_column(String(120), default="System")


class CheckResult(Base, IdMixin):
    """What happened when the platform ran a check. Never self-reported."""

    __tablename__ = "check_results"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    check_id: Mapped[str | None] = mapped_column(
        ForeignKey("checks.id", ondelete="SET NULL"), index=True
    )
    check_key: Mapped[str] = mapped_column(String(60), default="")
    check_kind: Mapped[str] = mapped_column(String(20), default="command")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    work_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    artifact_id: Mapped[str | None] = mapped_column(
        ForeignKey("artifacts.id", ondelete="SET NULL"), index=True
    )
    run_id: Mapped[str | None] = mapped_column(String(36))
    task_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text, default="")
    # Everything needed to re-run this check and compare: command, exit code,
    # artifact hash, per-criterion verdicts, evaluator agreement.
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class Source(Base, IdMixin):
    """Something fetched from outside, kept so a citation can be resolved.

    A citation check does not trust that a quote is real: it looks the quote up
    in the stored text of the page it claims to come from.
    """

    __tablename__ = "sources"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[str | None] = mapped_column(String(36), index=True)
    work_item_id: Mapped[str | None] = mapped_column(String(36), index=True)
    fetched_by: Mapped[str | None] = mapped_column(String(36))
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str] = mapped_column(String(400), default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Blob key for the extracted text. The text itself is not in the row.
    text_key: Mapped[str] = mapped_column(String(200), default="")
    chars: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
