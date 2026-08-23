"""Shared declarative base and column helpers."""

import json
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType

# Embedding width. nv-embedqa-e5-v5 returns 1024 dimensions, which is inside the
# 2000-dimension ceiling pgvector's HNSW index allows on a `vector` column.
EMBEDDING_DIM = 1024


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class IdMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# SQLite only auto-increments a plain INTEGER primary key, so append-only tables
# with a monotonic cursor need the variant to stay testable.
BigSerial = BigInteger().with_variant(Integer, "sqlite")


class Vector(UserDefinedType):
    """A pgvector column that degrades to TEXT on SQLite.

    The bind form is pgvector's own literal (`[0.1,0.2,...]`), which Postgres
    casts to `vector` and SQLite simply stores as text. That keeps one write path
    for both, so the test suite exercises the same code the server runs.
    Similarity search differs by dialect and lives in `services/memory.py`.
    """

    cache_ok = True

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def get_col_spec(self, **_kw) -> str:
        return f"vector({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(f"{float(v):.7g}" for v in value) + "]"

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                return [float(part) for part in value.strip("[] ").split(",") if part.strip()]
            return list(value)

        return process


@compiles(Vector, "sqlite")
def _vector_as_text(type_, compiler, **kw) -> str:  # noqa: ARG001
    return "TEXT"


def dumps(value) -> str:
    """Canonical JSON: sorted keys, no incidental whitespace.

    Used wherever a hash has to be reproducible from stored data.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
