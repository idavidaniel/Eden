"""The migrations, run for real against Postgres.

The rest of the suite builds the schema straight from the models on SQLite,
which proves the models are coherent and proves nothing at all about the
migrations. This file runs them from empty to head on a scratch database and
then asks Alembic whether the result matches the models. It is skipped when
there is no Postgres to talk to, because that is the only place these run.
"""

import os
import uuid

import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.skipif(
    not os.environ.get("MIGRATION_TEST_URL"),
    reason="Set MIGRATION_TEST_URL to a Postgres server to exercise the migrations.",
)


def _admin_url() -> str:
    url = os.environ["MIGRATION_TEST_URL"]
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def scratch_database():
    """A real, empty Postgres database, dropped afterwards whatever happens."""
    name = f"eden_migration_{uuid.uuid4().hex[:12]}"
    admin = sa.create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = _admin_url().rsplit("/", 1)[0] + f"/{name}"
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(
                sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": name},
            )
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture(autouse=True)
def point_alembic_at(scratch_database, monkeypatch):
    """`env.py` reads the URL from the environment, which is how it runs in
    production too. Overriding the config option would test a path nobody uses."""
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", scratch_database)
    yield


def _config():
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = Config(os.path.join(here, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(here, "migrations"))
    return config


def test_an_empty_database_migrates_to_head(scratch_database):
    from alembic import command

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()

    command.upgrade(_config(), "head")

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    # A sample from every phase, so a migration silently dropped from the chain
    # shows up here rather than in production.
    assert {
        "companies",
        "employees",
        "projects",
        "work_items",
        "artifacts",
        "checks",
        "check_results",
        "sources",
        "roles",
        "artifact_kinds",
        "memories",
        "memory_blocks",
        "agent_tokens",
        "agent_tasks",
        "agent_messages",
        "usage_events",
        "ledger",
        "approvals",
        "meetings",
        "tool_grants",
        "tool_calls",
        "mcp_servers",
        "authored_tools",
        "tenants",
        "users",
        "refresh_tokens",
    } <= tables
    assert "tickets" not in tables, "the rename should have happened"

    # Tenancy is the column the whole authorisation model rests on.
    columns = {column["name"] for column in inspector.get_columns("companies")}
    assert "tenant_id" in columns
    engine.dispose()


def test_the_migrated_schema_matches_the_models(scratch_database):
    """Autogenerate finding work to do means the two have drifted apart."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import models  # noqa: F401
    from models.base import Base

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    command.upgrade(_config(), "head")

    from migrations.filters import include_object

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object, "compare_type": False},
        )
        differences = compare_metadata(context, Base.metadata)

    engine.dispose()
    assert differences == [], f"the migrations and the models disagree: {differences}"


def test_the_hand_written_vector_index_survives(scratch_database):
    """Autogenerate cannot see it, so a careless migration would drop it."""
    from alembic import command

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    command.upgrade(_config(), "head")

    inspector = sa.inspect(engine)
    names = {index["name"] for index in inspector.get_indexes("memories")}
    assert "ix_memories_embedding_hnsw" in names
    engine.dispose()


def test_every_migration_downgrades_and_upgrades_again(scratch_database):
    """A downgrade nobody has run is a downgrade that does not work."""
    from alembic import command

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    engine.dispose()

    config = _config()
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")

# --------------------------------------------------------------------------
# adopting a database that predates the migrations
# --------------------------------------------------------------------------

# What a database looks like when it ran an *earlier version* of migration 0002
# — the one that gave the ledger a UUID primary key and `seq` as an ordinary
# column, before the model changed. Migration 0007 exists to repair exactly
# this, and until 0010 its repair left the ledger unwritable: it dropped the old
# primary key without giving `seq` a sequence or making it the key.
#
# These tests only ever ran forward from empty, which is why nobody noticed.
LEGACY_LEDGER = """
CREATE TABLE ledger (
    id varchar(36) NOT NULL PRIMARY KEY,
    seq bigint NOT NULL,
    company_id varchar(36) NOT NULL,
    project_id varchar(36),
    height integer NOT NULL,
    prev_hash varchar(64) NOT NULL,
    hash varchar(64) NOT NULL,
    kind varchar(40) NOT NULL,
    actor_id varchar(36),
    actor_label varchar(160) NOT NULL,
    subject_kind varchar(40),
    subject_id varchar(36),
    payload json NOT NULL,
    at timestamptz NOT NULL,
    CONSTRAINT ledger_company_id_fkey FOREIGN KEY (company_id)
        REFERENCES companies(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX ix_ledger_seq ON ledger (seq);
CREATE INDEX ix_ledger_company_id ON ledger (company_id);
CREATE INDEX ix_ledger_project_id ON ledger (project_id);
CREATE INDEX ix_ledger_hash ON ledger (hash);
CREATE INDEX ix_ledger_kind ON ledger (kind);
CREATE INDEX ix_ledger_subject_id ON ledger (subject_id);
"""


def _adopt_legacy(url: str) -> None:
    """Migrate up to just before the repair, then put the old ledger back.

    The real database got here by running a version of 0002 that has since been
    edited. Rewriting the table at 0006 reproduces that state faithfully, which
    is the only way to exercise what 0007 actually has to fix.
    """
    from alembic import command

    engine = sa.create_engine(url)
    with engine.connect() as connection:
        connection.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    engine.dispose()

    command.upgrade(_config(), "0006")

    engine = sa.create_engine(url)
    with engine.connect() as connection:
        connection.execute(sa.text("DROP TABLE IF EXISTS ledger CASCADE"))
        for statement in LEGACY_LEDGER.strip().split(";"):
            if statement.strip():
                connection.execute(sa.text(statement))
        # `projects.preview` was nullable then too.
        connection.execute(sa.text("ALTER TABLE projects ALTER COLUMN preview DROP NOT NULL"))
        connection.commit()
    engine.dispose()


def test_a_database_that_predates_the_migrations_can_still_be_migrated(scratch_database):
    from alembic import command

    _adopt_legacy(scratch_database)
    command.upgrade(_config(), "head")

    engine = sa.create_engine(scratch_database)
    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("ledger")}
    assert "id" not in columns, "the old primary key should have been dropped"
    assert "seq" in columns
    engine.dispose()


def test_the_adopted_ledger_can_actually_be_written_to(scratch_database):
    """The bug this caught: `seq` with no sequence and no primary key.

    Every append failed on a not-null violation, so nothing could be recorded —
    in a system whose entire claim is that it records what happened.
    """
    from alembic import command

    _adopt_legacy(scratch_database)
    command.upgrade(_config(), "head")

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO tenants (id, name, slug, is_bootstrap, settings) "
                "VALUES ('t1', 'T', 't', false, '{}')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO companies (id, tenant_id, name, slug, pack_key, departments, "
                "work_item_kinds, settings, halted, created_at, updated_at) "
                "VALUES ('c1', 't1', 'C', 'c', 'blank', '[]', '[]', '{}', false, now(), now())"
            )
        )
        # No `seq` supplied, exactly as the application appends.
        for height in range(3):
            connection.execute(
                sa.text(
                    "INSERT INTO ledger (company_id, height, prev_hash, hash, kind, "
                    "actor_label, payload, at) "
                    "VALUES ('c1', :h, 'p', :hash, 'k', 'You', '{}', now())"
                ),
                {"h": height, "hash": f"hash-{height}"},
            )
        connection.commit()

        assigned = list(
            connection.execute(sa.text("SELECT seq FROM ledger ORDER BY seq")).scalars()
        )

    engine.dispose()
    assert len(assigned) == 3
    assert all(value is not None for value in assigned)
    assert assigned == sorted(assigned), "seq must increase, or the chain has no order"


def test_the_adopted_schema_matches_a_freshly_migrated_one(scratch_database):
    """Adopting an old database must land in the same place as starting clean."""
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    import models  # noqa: F401
    from migrations.filters import include_object
    from models.base import Base

    _adopt_legacy(scratch_database)
    command.upgrade(_config(), "head")

    engine = sa.create_engine(scratch_database)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_object": include_object, "compare_type": False},
        )
        differences = compare_metadata(context, Base.metadata)
    engine.dispose()
    assert differences == [], f"an adopted database drifted from the models: {differences}"
