"""the ledger can be written to

Migration 0007 repaired databases that predate the migrations by dropping the
old `ledger.id` column — and took the primary key with it, leaving `seq` as a
plain `bigint NOT NULL` with nothing to generate a value. Every append then
failed on a not-null violation, which meant nothing could be recorded at all.

A database built from 0001 upwards was always correct, because `create_table`
gives a single-column integer primary key its own sequence. This brings the
adopted path to the same shape: the same sequence name, the same default, the
same primary key, so the two converge rather than drifting.

Written to be safe on a table that already has rows: the sequence starts above
whatever the highest `seq` is, so nothing collides.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import models.base  # noqa: F401  (vector and other project column types)

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEQUENCE = "ledger_seq_seq"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite gives an INTEGER PRIMARY KEY a rowid alias for free

    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("ledger")}
    if "seq" not in columns:
        return

    # --- something has to generate the value ------------------------------
    if not columns["seq"].get("default"):
        op.execute(sa.text(f"CREATE SEQUENCE IF NOT EXISTS {SEQUENCE} AS bigint"))
        op.execute(
            sa.text(f"ALTER TABLE ledger ALTER COLUMN seq SET DEFAULT nextval('{SEQUENCE}')")
        )
        # Owned by the column, so dropping the table takes the sequence with it.
        op.execute(sa.text(f"ALTER SEQUENCE {SEQUENCE} OWNED BY ledger.seq"))
        # Start above anything already written, or the first append collides.
        op.execute(
            sa.text(
                f"SELECT setval('{SEQUENCE}', COALESCE((SELECT MAX(seq) FROM ledger), 0) + 1, false)"
            )
        )

    # --- and it has to be the key -----------------------------------------
    has_primary_key = bool((inspector.get_pk_constraint("ledger") or {}).get(
        "constrained_columns"
    ))
    if not has_primary_key:
        op.create_primary_key("ledger_pkey", "ledger", ["seq"])


def downgrade() -> None:
    # Deliberately not reversed. Removing the default would put the ledger back
    # in a state where it cannot be written to, and no downgrade should do that.
    pass
