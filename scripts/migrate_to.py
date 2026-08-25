#!/usr/bin/env python3
"""Move Eden to another Postgres.

    python scripts/migrate_to.py 'postgresql://user:pass@host:5432/eden'
    python scripts/migrate_to.py "$TARGET" --copy-data

Two separate jobs, because they fail for different reasons:

  * **schema** runs the Alembic chain against the target. This is the one that
    matters, and it is the same chain the tests run from empty to head on every
    build. It needs the `vector` extension, which the script creates first;
  * **data** copies the rows across, in dependency order, and is optional. A new
    deployment usually wants an empty database.

What this does *not* move is `DATA_DIR` — the git workspaces and the
content-addressed blob store. Those are files, and the deliverables in them are
what check results are pinned to. Leave them behind and every artifact reads as
"the content is gone" on re-verification, which is correct and unhelpful. Copy
that directory too, or accept that the history does not come with you.
"""

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(os.path.dirname(HERE), "backend")
sys.path.insert(0, BACKEND)

# Parents before children, so a foreign key never points at a row that is not
# there yet. Derived by hand from the models; `alembic upgrade` does not care
# about order but a bulk copy does.
COPY_ORDER = [
    "tenants",
    "users",
    "refresh_tokens",
    "companies",
    "roles",
    "artifact_kinds",
    "employees",
    "identities",
    "projects",
    "work_items",
    "work_item_comments",
    "runs",
    "run_steps",
    "documents",
    "channels",
    "messages",
    "activities",
    "artifacts",
    "checks",
    "check_results",
    "sources",
    "ledger",
    "memories",
    "memory_blocks",
    "agent_tokens",
    "agent_tasks",
    "agent_messages",
    "approvals",
    "meetings",
    "usage_events",
    "tool_grants",
    "tool_calls",
    "mcp_servers",
    "authored_tools",
    "connections",
]


def _sqlalchemy(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def prepare(url: str) -> None:
    """pgvector, before anything that needs a vector column."""
    import sqlalchemy as sa

    engine = sa.create_engine(_sqlalchemy(url))
    with engine.connect() as connection:
        try:
            connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
            print("  vector extension ready")
        except Exception as exc:
            print(f"  ! could not create the vector extension: {exc}")
            print("    Memory retrieval needs it. On Cloud SQL, enable it under Flags;")
            print("    on Neon and Supabase it is available by default.")
            raise
    engine.dispose()


def migrate(url: str) -> None:
    print("running migrations")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "ALEMBIC_DATABASE_URL": url},
        capture_output=True,
        text=True,
    )
    print(result.stdout[-2000:] or result.stderr[-2000:])
    if result.returncode:
        raise SystemExit("migration failed")
    print("  schema is at head")


def copy_data(source: str, target: str) -> None:
    """Bulk copy, table by table, inside one transaction per table."""
    import sqlalchemy as sa

    src = sa.create_engine(_sqlalchemy(source))
    dst = sa.create_engine(_sqlalchemy(target))
    existing = set(sa.inspect(src).get_table_names())

    print("copying rows")
    for table in COPY_ORDER:
        if table not in existing:
            continue
        with src.connect() as read:
            rows = [dict(row) for row in read.execute(sa.text(f"SELECT * FROM {table}")).mappings()]
        if not rows:
            continue
        columns = ", ".join(f'"{name}"' for name in rows[0])
        markers = ", ".join(f":{name}" for name in rows[0])
        with dst.connect() as write:
            write.execute(
                sa.text(f"INSERT INTO {table} ({columns}) VALUES ({markers})"), rows
            )
            write.commit()
        print(f"  {table}: {len(rows)}")

    # Sequences do not follow the rows, so the next insert would collide.
    with dst.connect() as write:
        write.execute(
            sa.text(
                "SELECT setval('ledger_seq_seq', "
                "COALESCE((SELECT MAX(seq) FROM ledger), 0) + 1, false)"
            )
        )
        write.commit()
    print("  sequences reset")
    src.dispose()
    dst.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="postgresql://… of the database to migrate into")
    parser.add_argument("--copy-data", action="store_true", help="Also copy the rows across.")
    parser.add_argument(
        "--from",
        dest="source",
        default=os.getenv("DATABASE_URL", ""),
        help="Where to copy from. Defaults to DATABASE_URL.",
    )
    args = parser.parse_args()

    prepare(args.target)
    migrate(args.target)

    if args.copy_data:
        if not args.source:
            print("error: --copy-data needs --from or DATABASE_URL", file=sys.stderr)
            return 2
        copy_data(args.source, args.target)

    print("\nDone. Point DATABASE_URL at the target and restart the backend.")
    print("Remember DATA_DIR: the workspaces and blobs are files, and the")
    print("deliverables in them are what check results are pinned to.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
