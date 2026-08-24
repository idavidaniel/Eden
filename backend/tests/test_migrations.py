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
    } <= tables
    assert "tickets" not in tables, "the rename should have happened"
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
