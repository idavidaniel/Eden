"""Password hashing and reversible sealing for stored credentials.

Employee credentials are platform-issued service accounts, not human secrets:
the UI has to be able to show them (like an admin console showing a bot's API
key), so they are sealed with a key derived from SECRET_KEY rather than being
one-way hashed only. The hash is what verification uses; the sealed copy is what
the reveal endpoint decrypts.
"""

import base64
import hashlib
import hmac
import os
import secrets

from config import get_settings

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}


def generate_password(length: int = 20) -> str:
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_token(prefix: str = "eden") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def hash_secret(value: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(value.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_secret(value: str, stored: str) -> bool:
    try:
        algorithm, salt_b64, digest_b64 = stored.split("$")
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(value.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def token_digest(value: str) -> str:
    """Keyed digest for a high-entropy API token.

    Tokens are 256 bits of randomness, so there is nothing to brute-force and a
    slow KDF would only tax every authenticated request. Passwords still go
    through scrypt above; this is for machine credentials only.
    """
    return hmac.new(_key(), value.encode(), hashlib.sha256).hexdigest()


def digests_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def _key() -> bytes:
    return hashlib.sha256(get_settings().secret_key.encode()).digest()


def seal(value: str) -> str:
    """Encrypt with a keystream derived from SECRET_KEY, authenticated with HMAC."""
    nonce = os.urandom(16)
    stream = _keystream(nonce, len(value.encode()))
    ciphertext = bytes(a ^ b for a, b in zip(value.encode(), stream, strict=True))
    tag = hmac.new(_key(), nonce + ciphertext, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode()


def unseal(sealed: str) -> str:
    raw = base64.urlsafe_b64decode(sealed.encode())
    nonce, tag, ciphertext = raw[:16], raw[16:32], raw[32:]
    expected = hmac.new(_key(), nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise ValueError("Sealed value failed authentication (wrong SECRET_KEY?).")
    stream = _keystream(nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, stream, strict=True)).decode()


def _keystream(nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(_key(), nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])
