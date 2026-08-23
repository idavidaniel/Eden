"""Content-addressed storage for anything that is not a file in a git workspace.

Keyed by the sha256 of the bytes, so identical content is stored once and the
key *is* the proof of what was delivered. The ledger commits to these hashes;
`ledger/verify` re-reads the bytes here and re-runs the checks against them.
"""

import hashlib
import os
from pathlib import Path

from config import get_settings


def root() -> Path:
    return Path(get_settings().data_dir) / "blobs"


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_text(text: str) -> str:
    return hash_bytes(text.encode())


def _path(key: str) -> Path:
    # Two-character fan-out keeps any one directory from holding every blob.
    return root() / key[:2] / key


def put(data: bytes) -> str:
    key = hash_bytes(data)
    path = _path(key)
    if path.exists():
        return key
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write then rename: a reader never sees a half-written blob.
    temporary = path.with_suffix(".partial")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return key


def put_text(text: str) -> str:
    return put(text.encode())


def exists(key: str) -> bool:
    return bool(key) and _path(key).exists()


def get(key: str) -> bytes:
    path = _path(key)
    if not path.exists():
        raise FileNotFoundError(f"No stored content for {key[:12]}…")
    return path.read_bytes()


def get_text(key: str) -> str:
    return get(key).decode(errors="replace")


def size(key: str) -> int:
    path = _path(key)
    return path.stat().st_size if path.exists() else 0
