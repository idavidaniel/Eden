"""The second factor.

The shared secret is the whole game: anyone who reads it can generate this
person's codes forever. So it is sealed at rest with the same authenticated
symmetric sealing used for connector credentials, keyed from SECRET_KEY. That
is what `crypto.seal` already is — nonce, HMAC tag, keystream — so pulling in a
second encryption library for the same job would add a dependency and a second
key to lose, not security.

Backup codes are hashed, not sealed. They are for the person, not the platform:
nothing here ever needs to read one back, so nothing here can.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime

import pyotp
from sqlalchemy.orm import Session

from config import get_settings
from models import User

from . import crypto
from .auth import AuthError

log = logging.getLogger(__name__)

ISSUER = "Eden"
BACKUP_CODE_COUNT = 10
# Enough entropy that guessing is hopeless, short enough to read off paper.
BACKUP_CODE_BYTES = 5
# One step either side, so a slightly wrong clock does not lock somebody out.
VALID_WINDOW = 1


def _secret_for(user: User) -> str:
    if not user.totp_secret_sealed:
        raise AuthError("Two-factor authentication is not set up on this account.", status=400)
    try:
        return crypto.unseal(user.totp_secret_sealed)
    except ValueError as exc:
        # A changed SECRET_KEY makes every stored secret unreadable. Say so
        # plainly rather than reporting it as a wrong code forever.
        raise AuthError(
            "This account's two-factor secret cannot be read. If SECRET_KEY changed, "
            "two-factor has to be set up again.",
            status=500,
        ) from exc


def begin_setup(db: Session, user: User) -> dict:
    """Generate a secret and hand back what an authenticator app needs.

    Nothing is enabled here. The secret is stored so the confirm step can check
    a code against it, but `two_factor_enabled` stays false until somebody
    proves they can actually generate a code — otherwise a mis-scanned QR would
    lock them out of their own account.
    """
    if user.two_factor_enabled:
        raise AuthError(
            "Two-factor is already on. Turn it off first if you want a new secret.",
            status=409,
        )
    secret = pyotp.random_base32()
    user.totp_secret_sealed = crypto.seal(secret)
    db.add(user)
    db.flush()

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)
    return {
        "secret": secret,
        "uri": uri,
        "issuer": ISSUER,
        "note": (
            "Scan this, then enter a code to switch it on. It is not on until you do — "
            "so a mis-scanned code costs you nothing."
        ),
    }


def confirm_setup(db: Session, user: User, code: str) -> list[str]:
    """Enable 2FA, and return backup codes exactly once."""
    if user.two_factor_enabled:
        raise AuthError("Two-factor is already on.", status=409)
    if not verify_code(user, code):
        raise AuthError("That code is not right. Check the clock on your phone.", status=400)

    plain = [_new_backup_code() for _ in range(BACKUP_CODE_COUNT)]
    user.backup_codes = [_hash_backup_code(code) for code in plain]
    user.two_factor_enabled = True
    user.two_factor_enabled_at = datetime.now(UTC)
    db.add(user)
    db.flush()
    return plain


def disable(db: Session, user: User) -> None:
    user.two_factor_enabled = False
    user.two_factor_enabled_at = None
    user.totp_secret_sealed = None
    user.backup_codes = []
    db.add(user)
    db.flush()


def verify_code(user: User, code: str) -> bool:
    """A six-digit code from the app. Constant-time, and window-tolerant."""
    cleaned = (code or "").replace(" ", "").replace("-", "")
    if not cleaned.isdigit() or len(cleaned) != 6:
        return False
    return pyotp.TOTP(_secret_for(user)).verify(cleaned, valid_window=VALID_WINDOW)


def verify_backup_code(db: Session, user: User, code: str) -> bool:
    """A backup code, which is spent by using it."""
    cleaned = _normalise_backup_code(code)
    if not cleaned:
        return False
    digest = _hash_backup_code(cleaned)
    remaining = list(user.backup_codes or [])
    for stored in remaining:
        if hmac.compare_digest(stored, digest):
            remaining.remove(stored)
            user.backup_codes = remaining
            db.add(user)
            db.flush()
            log.info("%s used a backup code; %s left", user.email, len(remaining))
            return True
    return False


def verify_second_factor(db: Session, user: User, code: str) -> bool:
    """Either kind of code. Callers should not have to know which was given."""
    if verify_code(user, code):
        return True
    return verify_backup_code(db, user, code)


def status(user: User) -> dict:
    return {
        "enabled": user.two_factor_enabled,
        "enabled_at": user.two_factor_enabled_at.isoformat()
        if user.two_factor_enabled_at
        else None,
        "backup_codes_left": len(user.backup_codes or []),
        "setup_started": bool(user.totp_secret_sealed and not user.two_factor_enabled),
    }


# --------------------------------------------------------------------------


def _new_backup_code() -> str:
    raw = secrets.token_hex(BACKUP_CODE_BYTES).upper()
    return f"{raw[:5]}-{raw[5:]}"


def _normalise_backup_code(code: str) -> str:
    cleaned = (code or "").strip().upper().replace(" ", "").replace("-", "")
    return cleaned if len(cleaned) == BACKUP_CODE_BYTES * 2 else ""


def _hash_backup_code(code: str) -> str:
    key = hashlib.sha256(get_settings().secret_key.encode()).digest()
    return hmac.new(key, _normalise_backup_code(code).encode(), hashlib.sha256).hexdigest()
