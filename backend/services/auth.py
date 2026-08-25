"""Signing people in.

Deliberately separate from `services/crypto.py`, which handles credentials the
platform *issues to agents*. Those are machine secrets the UI has to be able to
reveal. A person's password is the opposite: it is never revealed, never sealed,
only hashed — and slowly, because unlike a 256-bit token it is guessable.

Two token kinds, for two different jobs:

  * an **access token** is a short-lived JWT. It is self-contained, so checking
    it costs no database read, and it expires quickly enough that being unable
    to revoke it early is acceptable;
  * a **refresh token** is an opaque random string whose keyed digest is stored.
    It can be revoked, which is what makes "log out" mean something, and it is
    rotated on every use so a stolen one is detectable.
"""

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from models import RefreshToken, Tenant, User

log = logging.getLogger(__name__)

ALGORITHM = "HS256"
ACCESS_COOKIE = "eden_access"
REFRESH_COOKIE = "eden_refresh"
# bcrypt silently truncates at 72 bytes, which would make two different long
# passwords equivalent. Refuse rather than truncate.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 10


class AuthError(Exception):
    """Anything that should come back as a 401 or a 400 with a usable message."""

    def __init__(self, message: str, *, status: int = 401):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------
# passwords
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    check_password_strength(password)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def check_password_strength(password: str) -> None:
    """Length, and nothing else.

    Composition rules ("one capital, one symbol") push people towards
    `Password1!` and are worse than a length floor. Anything longer than
    bcrypt's 72-byte input is refused rather than quietly truncated.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(
            f"Use at least {MIN_PASSWORD_LENGTH} characters. A short phrase you can "
            "remember beats a short password you cannot.",
            status=400,
        )
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise AuthError(
            f"That is longer than {MAX_PASSWORD_BYTES} bytes, which is as much as the "
            "hash reads. Shorten it so all of it counts.",
            status=400,
        )


# --------------------------------------------------------------------------
# access tokens
# --------------------------------------------------------------------------


@dataclass
class Claims:
    user_id: str
    tenant_id: str
    kind: str  # access | 2fa


def _secret() -> bytes:
    """A full-length signing key, whatever length the configured secret is.

    A short JWT_SECRET would otherwise be used raw as an HMAC key, which is
    genuinely weaker than it looks — PyJWT warns about it, and it is right to.
    Hashing to 32 bytes costs nothing and removes the sharp edge.
    """
    return hashlib.sha256(get_settings().jwt_secret.encode()).digest()


def mint_access_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.id,
            "tid": user.tenant_id,
            "typ": "access",
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def mint_two_factor_token(user: User) -> str:
    """Proof that the password was right, and nothing more.

    Carries `typ: "2fa"` so it cannot be presented as an access token — which
    would turn the second factor into an optional extra.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.id,
            "tid": user.tenant_id,
            "typ": "2fa",
            "iat": now,
            "exp": now + timedelta(minutes=settings.two_factor_token_minutes),
        },
        _secret(),
        algorithm=ALGORITHM,
    )


def read_token(token: str, *, expect: str = "access") -> Claims:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("That session has expired. Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("That token is not valid.") from exc

    if payload.get("typ") != expect:
        raise AuthError(
            f"That is a '{payload.get('typ')}' token, not a '{expect}' one."
        )
    return Claims(user_id=payload["sub"], tenant_id=payload["tid"], kind=payload["typ"])


# --------------------------------------------------------------------------
# refresh tokens
# --------------------------------------------------------------------------


def _digest(token: str) -> str:
    return hmac.new(_secret(), token.encode(), hashlib.sha256).hexdigest()


def issue_refresh_token(
    db: Session, user: User, *, user_agent: str = "", ip: str = ""
) -> str:
    settings = get_settings()
    raw = secrets.token_urlsafe(48)
    db.add(
        RefreshToken(
            user_id=user.id,
            digest=_digest(raw),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
            user_agent=user_agent[:300],
            ip=ip[:64],
        )
    )
    db.flush()
    return raw


def rotate_refresh_token(
    db: Session, presented: str, *, user_agent: str = "", ip: str = ""
) -> tuple[User, str]:
    """Exchange a refresh token for a new one, and refuse a replay.

    A token that has already been rotated should never appear again. If it does,
    either it was stolen or a client is confused; both are handled the same way,
    by revoking every token this user holds and making them sign in.
    """
    row = db.scalar(select(RefreshToken).where(RefreshToken.digest == _digest(presented)))
    if not row:
        raise AuthError("That refresh token is not recognised. Sign in again.")

    user = db.get(User, row.user_id)
    if row.replaced_by:
        if user:
            revoke_all(db, user, reason="a refresh token was presented twice")
            db.commit()
        raise AuthError(
            "That refresh token had already been used. Every session has been "
            "signed out as a precaution. Sign in again."
        )
    if row.revoked_at:
        raise AuthError("That session was signed out. Sign in again.")
    if _expired(row.expires_at):
        raise AuthError("That session has expired. Sign in again.")
    if not user or not user.is_active:
        raise AuthError("That account is no longer active.")

    fresh = issue_refresh_token(db, user, user_agent=user_agent, ip=ip)
    row.replaced_by = _digest(fresh)[:36]
    row.revoked_at = datetime.now(UTC)
    db.add(row)
    return user, fresh


def revoke_refresh_token(db: Session, presented: str) -> bool:
    row = db.scalar(select(RefreshToken).where(RefreshToken.digest == _digest(presented)))
    if not row or row.revoked_at:
        return False
    row.revoked_at = datetime.now(UTC)
    db.add(row)
    return True


def revoke_all(db: Session, user: User, *, reason: str = "") -> int:
    live = list(
        db.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    )
    now = datetime.now(UTC)
    for row in live:
        row.revoked_at = now
        db.add(row)
    if live and reason:
        log.info("revoked %s session(s) for %s: %s", len(live), user.email, reason)
    return len(live)


def _expired(when: datetime | None) -> bool:
    if when is None:
        return False
    # SQLite hands back naive datetimes; treating one as UTC is correct here
    # because that is what was written.
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when < datetime.now(UTC)


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------


def normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def find_user(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalise_email(email)))


def sign_up(
    db: Session, *, email: str, password: str, full_name: str, organisation: str = ""
) -> tuple[User, Tenant]:
    """Create an account, and the organisation it owns."""
    from api.companies import unique_slug  # local: avoids an import cycle

    address = normalise_email(email)
    if "@" not in address or len(address) < 5:
        raise AuthError("That does not look like an email address.", status=400)
    if find_user(db, address):
        # Deliberately explicit. Hiding it does not stop enumeration — signup
        # has to answer somehow — and being coy just confuses honest people.
        raise AuthError("There is already an account with that email.", status=409)

    hashed = hash_password(password)
    name = organisation.strip() or f"{full_name.strip() or address.split('@')[0]}'s workspace"
    tenant = Tenant(name=name[:160], slug=unique_slug(db, name, model=Tenant))
    db.add(tenant)
    db.flush()

    user = User(
        tenant_id=tenant.id,
        email=address,
        hashed_password=hashed,
        full_name=full_name.strip()[:160],
        is_owner=True,
    )
    db.add(user)
    db.flush()
    return user, tenant


def authenticate(db: Session, *, email: str, password: str) -> User:
    """Check an email and password. Raises rather than returning None."""
    settings = get_settings()
    user = find_user(db, email)

    if user and user.locked_until and not _expired(user.locked_until):
        raise AuthError(
            "Too many failed attempts. Try again in a few minutes.", status=429
        )

    # Hash even when the account does not exist, so the time taken does not say
    # whether the email is registered.
    if not user:
        bcrypt.hashpw(b"absent", bcrypt.gensalt())
        raise AuthError("That email and password do not match.")

    if not verify_password(password, user.hashed_password):
        user.failed_logins += 1
        if user.failed_logins >= settings.max_failed_logins:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes)
            user.failed_logins = 0
        db.add(user)
        db.commit()
        raise AuthError("That email and password do not match.")

    if not user.is_active:
        raise AuthError("That account has been deactivated.", status=403)

    user.failed_logins = 0
    user.locked_until = None
    db.add(user)
    return user


def note_signed_in(db: Session, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    db.add(user)
