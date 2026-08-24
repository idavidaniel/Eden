"""a step can belong to an agent rather than a run

An employee is now addressable on its own, so a turn started through
`/agents/{id}/messages` has no run to hang off. `run_steps.run_id` becomes
nullable and the step records the company and the task instead.

This also repairs two shapes that only exist in databases predating the
migrations: a `ledger.id` column and a nullable `projects.preview`. Both are
guarded by inspection, so on a database built from 0001 upwards they no-op.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import models.base  # noqa: F401  (vector and other project column types)

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table)}


def _constraints(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        constraint["name"] for constraint in inspector.get_unique_constraints(table)
    }


def upgrade() -> None:
    op.add_column("run_steps", sa.Column("company_id", sa.String(length=36), nullable=True))
    op.add_column("run_steps", sa.Column("task_id", sa.String(length=36), nullable=True))
    op.alter_column("run_steps", "run_id", existing_type=sa.VARCHAR(length=36), nullable=True)
    op.create_index("ix_run_steps_company_id", "run_steps", ["company_id"])
    op.create_index("ix_run_steps_task_id", "run_steps", ["task_id"])
    op.create_foreign_key(
        "run_steps_company_id_fkey",
        "run_steps",
        "companies",
        ["company_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "run_steps_task_id_fkey",
        "run_steps",
        "agent_tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Steps written before this migration all belonged to a run, so their
    # company can be recovered from it rather than left blank.
    op.execute(
        """
        UPDATE run_steps
           SET company_id = runs.company_id
          FROM runs
         WHERE run_steps.run_id = runs.id
           AND run_steps.company_id IS NULL
        """
    )

    # --- repairs for databases that predate the migrations -----------------
    if "id" in _columns("ledger"):
        if "ix_ledger_seq" in _indexes("ledger"):
            op.drop_index("ix_ledger_seq", table_name="ledger")
        op.drop_column("ledger", "id")
    if "uq_ledger_company_height" not in _constraints("ledger"):
        op.create_unique_constraint(
            "uq_ledger_company_height", "ledger", ["company_id", "height"]
        )
    op.execute("UPDATE projects SET preview = '{}'::jsonb WHERE preview IS NULL")
    op.alter_column("projects", "preview", nullable=False)


def downgrade() -> None:
    op.drop_constraint("run_steps_task_id_fkey", "run_steps", type_="foreignkey")
    op.drop_constraint("run_steps_company_id_fkey", "run_steps", type_="foreignkey")
    op.drop_index("ix_run_steps_task_id", table_name="run_steps")
    op.drop_index("ix_run_steps_company_id", table_name="run_steps")
    op.execute("DELETE FROM run_steps WHERE run_id IS NULL")
    op.alter_column("run_steps", "run_id", existing_type=sa.VARCHAR(length=36), nullable=False)
    op.drop_column("run_steps", "task_id")
    op.drop_column("run_steps", "company_id")
