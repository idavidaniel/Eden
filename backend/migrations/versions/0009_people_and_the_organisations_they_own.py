"""people, the organisations they belong to, and sessions

Introduces tenancy. Until now anyone who could reach the API was an admin of
every company; this is the column that makes scoping possible.

Existing companies predate the idea of an owner, so they are adopted into one
bootstrap tenant rather than deleted or left dangling. `is_bootstrap` marks it,
so it is obvious in the database which tenant is the migration's doing. Whoever
signs up first can be moved into it by hand; guessing would be worse.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import models.base  # noqa: F401  (vector and other project column types)

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOOTSTRAP_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("settings", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("totp_secret_sealed", sa.Text(), nullable=True),
        sa.Column(
            "two_factor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("two_factor_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backup_codes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=False)
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("digest", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by", sa.String(length=36), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("ip", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_refresh_tokens_digest"), "refresh_tokens", ["digest"], unique=True)
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"])

    # --- adopt what is already here --------------------------------------
    # Nullable first, backfilled, then made NOT NULL. Adding a NOT NULL column
    # straight onto a populated table fails, and a server_default would leave a
    # default that outlives the migration.
    op.add_column("companies", sa.Column("tenant_id", sa.String(length=36), nullable=True))

    companies = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM companies")).scalar()
    if companies:
        op.execute(
            sa.text(
                "INSERT INTO tenants (id, name, slug, is_bootstrap, settings) "
                "VALUES (:id, :name, :slug, true, '{}')"
            ).bindparams(
                id=BOOTSTRAP_ID,
                name="Existing workspace",
                slug="existing-workspace",
            )
        )
        op.execute(
            sa.text("UPDATE companies SET tenant_id = :id WHERE tenant_id IS NULL").bindparams(
                id=BOOTSTRAP_ID
            )
        )

    op.alter_column("companies", "tenant_id", existing_type=sa.String(length=36), nullable=False)
    op.create_index(op.f("ix_companies_tenant_id"), "companies", ["tenant_id"])
    op.create_foreign_key(
        "companies_tenant_id_fkey", "companies", "tenants", ["tenant_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint("companies_tenant_id_fkey", "companies", type_="foreignkey")
    op.drop_index(op.f("ix_companies_tenant_id"), table_name="companies")
    op.drop_column("companies", "tenant_id")

    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_digest"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(op.f("ix_users_tenant_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_tenants_slug"), table_name="tenants")
    op.drop_table("tenants")
