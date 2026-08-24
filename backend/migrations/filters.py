"""What autogenerate is allowed to see.

Kept out of `env.py` so it can be imported without an Alembic context — the
migration tests compare the migrated schema against the models directly, and
they have to apply exactly the same filter or they compare different things.
"""

import os

# Set to narrow an autogenerate run to a few tables while developing.
ONLY_TABLES = {name for name in os.getenv("ALEMBIC_ONLY_TABLES", "").split(",") if name}
SKIP_TABLES = {name for name in os.getenv("ALEMBIC_SKIP_TABLES", "").split(",") if name}

# Indexes created by raw DDL because SQLAlchemy cannot express them. Without
# this, every autogenerate helpfully proposes dropping them again.
HAND_WRITTEN_INDEXES = {"ix_memories_embedding_hnsw"}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001
    if type_ == "index" and name in HAND_WRITTEN_INDEXES:
        return False
    if type_ == "table":
        if ONLY_TABLES and name not in ONLY_TABLES:
            return False
        if name in SKIP_TABLES:
            return False
    return True
