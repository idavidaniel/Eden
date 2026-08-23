"""Alembic environment.

The URL comes from DATABASE_URL through the same helper the application uses, so
migrations and the running server can never disagree about which database or
which driver they mean.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: F401,E402  (registers every mapper)
from db import sqlalchemy_url  # noqa: E402
from models.base import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Set while generating the baseline so autogenerate sees only the pre-v2 tables.
_ONLY_TABLES = {t for t in os.getenv("ALEMBIC_ONLY_TABLES", "").split(",") if t}
_SKIP_TABLES = {t for t in os.getenv("ALEMBIC_SKIP_TABLES", "").split(",") if t}


# Indexes created by raw DDL because SQLAlchemy cannot express them. Without
# this, every autogenerate helpfully proposes dropping them again.
HAND_WRITTEN_INDEXES = {"ix_memories_embedding_hnsw"}


def _include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001
    if type_ == "index" and name in HAND_WRITTEN_INDEXES:
        return False
    if type_ == "table":
        if _ONLY_TABLES and name not in _ONLY_TABLES:
            return False
        if name in _SKIP_TABLES:
            return False
    return True


def _url() -> str:
    url = os.getenv("ALEMBIC_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set, so there is nothing to migrate.")
    return sqlalchemy_url(url)


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=_include_object,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection", None)
    if connectable is None:
        engine = create_engine(_url(), pool_pre_ping=True, future=True)
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
        user_module_prefix="models.base.",
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
