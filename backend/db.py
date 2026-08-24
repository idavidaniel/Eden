"""Database engine, session factory and schema management."""

import logging
import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings

log = logging.getLogger(__name__)

# The revision that describes the schema as it was before this project had
# migrations. A database created before then is stamped here and migrated on.
BASELINE_REVISION = "0001"


def sqlalchemy_url(url: str) -> str:
    """Pin SQLAlchemy to psycopg 3, which is what this project installs."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def get_engine():
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set.")
    url = sqlalchemy_url(settings.database_url)
    if url.startswith("sqlite"):
        # The test path. SQLite serialises writers, and this application opens a
        # second session for bookkeeping while a turn is in flight, so it needs
        # write-ahead logging and the patience to wait its turn.
        engine = create_engine(
            url,
            pool_pre_ping=True,
            future=True,
            connect_args={"timeout": 30},
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(connection, _record):  # pragma: no cover - setup
            cursor = connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


def session() -> Session:
    return get_sessionmaker()()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _alembic_config():
    from alembic.config import Config

    here = os.path.dirname(os.path.abspath(__file__))
    config = Config(os.path.join(here, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(here, "migrations"))
    return config


# Any constant works; it only has to be the same in every process.
MIGRATION_LOCK_ID = 8_112_004


def init_db() -> None:
    """Bring the database up to the current revision. Safe to call repeatedly.

    Two workers booting at once must not both try to migrate: the loser used to
    re-stamp the baseline over the winner's work. A session-level advisory lock
    serialises them, and the schema state is only read once the lock is held.
    """
    from alembic import command

    import models  # noqa: F401  (registers every mapper)

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        _migrate(command)
        return

    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        conn.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_ID})
        conn.commit()
        try:
            _migrate(command)
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_ID})
            conn.commit()


def _migrate(command) -> None:
    tables = set(inspect(get_engine()).get_table_names())
    config = _alembic_config()
    if tables and "alembic_version" not in tables:
        log.warning("Adopting an existing database at revision %s", BASELINE_REVISION)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")
