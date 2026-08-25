"""People, the organisations they belong to, and how they stay signed in.

This is deliberately separate from `models/org.py`. A `Company` there is a
workspace full of AI employees; a `Tenant` here is the customer account that
*owns* companies. Conflating them would mean one human organisation could never
run two companies, and that an employee's credentials and a person's password
would live in the same table — which they must not, because they are protected
very differently.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, IdMixin, TimestampMixin


class Tenant(Base, IdMixin, TimestampMixin):
    """One customer organisation. Everything else hangs off this."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    # Set on the tenant that existing data was adopted into, so it is obvious
    # in the database which one is the migration's doing rather than a signup.
    is_bootstrap: Mapped[bool] = mapped_column(default=False)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)

    users: Mapped[list["User"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan"
    )


class User(Base, IdMixin, TimestampMixin):
    """A person. Not an employee — employees are agents and have no password."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), default="")
    is_active: Mapped[bool] = mapped_column(default=True)
    # The first user of a tenant owns it. Kept simple on purpose: there is no
    # role hierarchy yet, and pretending there is one would be worse than not.
    is_owner: Mapped[bool] = mapped_column(default=False)

    # --- second factor ---------------------------------------------------
    # Sealed, never stored in the clear: anyone reading the database would
    # otherwise be able to generate this person's codes indefinitely.
    totp_secret_sealed: Mapped[str | None] = mapped_column(Text)
    two_factor_enabled: Mapped[bool] = mapped_column(default=False)
    two_factor_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Hashed, like passwords. A backup code is a password that happens to be
    # short, and is shown exactly once.
    backup_codes: Mapped[list] = mapped_column(JSON, default=list)

    # --- sign-in bookkeeping ---------------------------------------------
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="users")


class RefreshToken(Base, IdMixin, TimestampMixin):
    """One issued refresh token, so that signing out actually signs you out.

    A self-contained JWT refresh token cannot be revoked before it expires,
    which makes "log out" a suggestion. These are opaque random strings; only a
    keyed digest is stored, and using one rotates it.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    digest: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when this token was rotated, pointing at what replaced it. A presented
    # token that has already been rotated is a replay, and kills the whole family.
    replaced_by: Mapped[str | None] = mapped_column(String(36))
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
