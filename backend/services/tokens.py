"""Agent API tokens: mint, verify, revoke.

An employee's credentials stop being set dressing here. A token issued to an
employee is the key to *that* employee: it authenticates the `/agents/{id}/*`
API and the MCP bridge, and every scope it carries is checked before a tool runs.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AgentToken, Employee
from models.agents import SCOPES

from .crypto import digests_match, token_digest

PREFIX_BYTES = 6
SECRET_BYTES = 32
DEFAULT_SCOPES = ["agent:message", "agent:task", "agent:read", "memory:read", "tools:*"]


class TokenError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def mint(
    db: Session,
    employee: Employee,
    *,
    name: str = "default",
    scopes: list[str] | None = None,
    expires_in_days: int | None = None,
    created_by: str = "You",
) -> tuple[AgentToken, str]:
    """Create a token. Returns the row and the plaintext, which is shown once."""
    wanted = scopes if scopes is not None else list(DEFAULT_SCOPES)
    for scope in wanted:
        if scope not in SCOPES and not scope.startswith("tools:"):
            raise TokenError(f"Unknown scope: {scope}")

    prefix = secrets.token_hex(PREFIX_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    plaintext = f"edn_{prefix}_{secret}"

    row = AgentToken(
        employee_id=employee.id,
        name=name[:120] or "default",
        prefix=prefix,
        digest=token_digest(secret),
        scopes=wanted,
        expires_at=_now() + timedelta(days=expires_in_days) if expires_in_days else None,
        created_by=created_by,
    )
    db.add(row)
    db.flush()
    return row, plaintext


def parse(presented: str) -> tuple[str, str] | None:
    """Split `edn_<prefix>_<secret>` without touching the database."""
    if not presented:
        return None
    presented = presented.strip()
    if presented.lower().startswith("bearer "):
        presented = presented[7:].strip()
    parts = presented.split("_", 2)
    if len(parts) != 3 or parts[0] != "edn" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify(db: Session, presented: str) -> AgentToken | None:
    """Return the live token row for a presented secret, or None."""
    parsed = parse(presented)
    if not parsed:
        return None
    prefix, secret = parsed

    row = db.scalar(select(AgentToken).where(AgentToken.prefix == prefix))
    if not row or row.revoked_at is not None:
        return None
    if not digests_match(row.digest, token_digest(secret)):
        return None
    if row.expires_at and _as_utc(row.expires_at) < _now():
        return None

    row.last_used_at = _now()
    db.add(row)
    return row


def revoke(db: Session, row: AgentToken) -> AgentToken:
    row.revoked_at = _now()
    db.add(row)
    return row


def has_scope(row: AgentToken, needed: str) -> bool:
    """`tools:*` covers every tool group; everything else is an exact match."""
    granted = set(row.scopes or [])
    if needed in granted:
        return True
    if needed.startswith("tools:") and "tools:*" in granted:
        return True
    return False


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
