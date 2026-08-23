"""tickets become work items

A rename, in place, with the data. Autogenerate cannot see a rename — it would
have dropped the table and created a new one, taking nine real tickets with it —
so this revision is written by hand.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# old name -> new name. Indexes and constraints survive a table rename under
# their original names, so they are renamed too rather than left misleading.
INDEXES = [
    ("ix_tickets_assignee_id", "ix_work_items_assignee_id"),
    ("ix_tickets_key", "ix_work_items_key"),
    ("ix_tickets_project_id", "ix_work_items_project_id"),
    ("ix_tickets_status", "ix_work_items_status"),
    ("ix_ticket_comments_ticket_id", "ix_work_item_comments_work_item_id"),
]
CONSTRAINTS = [
    ("work_items", "tickets_pkey", "work_items_pkey"),
    ("work_items", "tickets_project_id_fkey", "work_items_project_id_fkey"),
    ("work_items", "tickets_assignee_id_fkey", "work_items_assignee_id_fkey"),
    ("work_items", "tickets_reporter_id_fkey", "work_items_reporter_id_fkey"),
    ("work_items", "tickets_parent_id_fkey", "work_items_parent_id_fkey"),
    ("work_item_comments", "ticket_comments_pkey", "work_item_comments_pkey"),
    (
        "work_item_comments",
        "ticket_comments_ticket_id_fkey",
        "work_item_comments_work_item_id_fkey",
    ),
    (
        "work_item_comments",
        "ticket_comments_author_id_fkey",
        "work_item_comments_author_id_fkey",
    ),
    ("run_steps", "run_steps_ticket_id_fkey", "run_steps_work_item_id_fkey"),
]


def _rename_support(reverse: bool = False) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for old, new in INDEXES:
        a, b = (new, old) if reverse else (old, new)
        op.execute(f"ALTER INDEX IF EXISTS {a} RENAME TO {b}")
    for table, old, new in CONSTRAINTS:
        a, b = (new, old) if reverse else (old, new)
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {a} TO {b}")


def upgrade() -> None:
    op.rename_table("tickets", "work_items")
    op.rename_table("ticket_comments", "work_item_comments")
    op.alter_column("work_items", "type", new_column_name="kind")
    op.alter_column("work_item_comments", "ticket_id", new_column_name="work_item_id")
    op.alter_column("run_steps", "ticket_id", new_column_name="work_item_id")
    _rename_support()


def downgrade() -> None:
    _rename_support(reverse=True)
    op.alter_column("run_steps", "work_item_id", new_column_name="ticket_id")
    op.alter_column("work_item_comments", "work_item_id", new_column_name="ticket_id")
    op.alter_column("work_items", "kind", new_column_name="type")
    op.rename_table("work_item_comments", "ticket_comments")
    op.rename_table("work_items", "tickets")
