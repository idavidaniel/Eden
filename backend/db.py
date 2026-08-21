"""Database engine, session factory and schema helpers."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings


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
    return create_engine(sqlalchemy_url(settings.database_url), pool_pre_ping=True, future=True)


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


def init_db() -> None:
    """Create the extension and all tables. Safe to call repeatedly."""
    import models  # noqa: F401  (registers every mapper)
    from models.base import Base

    engine = get_engine()
    Base.metadata.create_all(engine)
