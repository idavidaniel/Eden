"""Postgres + pgvector schema for the knowledge base."""

import uuid
from functools import lru_cache

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import get_settings

Base = declarative_base()


def new_id() -> str:
    return str(uuid.uuid4())


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(String, primary_key=True, default=new_id)
    tenant_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=new_id)
    kb_id = Column(String, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True)
    position = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)  # the raw chunk
    context = Column(Text, nullable=True)  # LLM-generated situating context
    embedding = Column(Vector(get_settings().embedding_dim))


def _sqlalchemy_url(url: str) -> str:
    """Pin SQLAlchemy to psycopg 3, which is what this project installs.

    A bare `postgresql://` URL makes SQLAlchemy reach for psycopg2.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


@lru_cache
def get_engine():
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set - the knowledge base needs Postgres.")
    return create_engine(_sqlalchemy_url(settings.database_url), pool_pre_ping=True)


@lru_cache
def get_sessionmaker():
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def session():
    return get_sessionmaker()()


def init_db() -> None:
    """Create the pgvector extension and the tables. Safe to call repeatedly."""
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(engine)
