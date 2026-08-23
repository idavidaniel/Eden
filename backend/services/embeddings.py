"""Turns text into vectors, and says so plainly when it cannot.

There is no offline stand-in here on purpose. A hash-based fake embedder would
return vectors with no semantic structure, and memory retrieval would keep
working while quietly returning nonsense. Instead this module reports
unavailability, and `memory.search` falls back to lexical matching and labels the
result as such — a worse answer you can see beats a wrong answer you cannot.
"""

import logging
import threading
import time

from config import get_settings
from models.base import EMBEDDING_DIM

log = logging.getLogger(__name__)

# One batch of this size embeds in well under a second; seven single calls did not.
MAX_BATCH = 32
# After a failure, stop trying for this long rather than adding provider latency
# to every turn.
COOLDOWN_SECONDS = 60.0

_state_lock = threading.Lock()
_blocked_until = 0.0
_last_error = ""


def available() -> bool:
    if not get_settings().nvidia_api_key:
        return False
    with _state_lock:
        return time.monotonic() >= _blocked_until


def status() -> dict:
    with _state_lock:
        waiting = max(0.0, _blocked_until - time.monotonic())
    return {
        "model": get_settings().embedding_model,
        "dimensions": EMBEDDING_DIM,
        "available": available(),
        "retry_in_seconds": round(waiting, 1),
        "last_error": _last_error,
    }


def _note_failure(exc: Exception) -> None:
    global _blocked_until, _last_error
    with _state_lock:
        _blocked_until = time.monotonic() + COOLDOWN_SECONDS
        _last_error = str(exc)[:300]
    log.warning("embeddings unavailable, falling back to lexical search: %s", exc)


def _note_success() -> None:
    global _blocked_until, _last_error
    with _state_lock:
        _blocked_until = 0.0
        _last_error = ""


def _embed(texts: list[str], input_type: str) -> list[list[float]] | None:
    if not texts or not available():
        return None
    from agents.llm import embed as call_provider

    out: list[list[float]] = []
    try:
        for start in range(0, len(texts), MAX_BATCH):
            chunk = [t[:8000] or " " for t in texts[start : start + MAX_BATCH]]
            out.extend(call_provider(chunk, input_type=input_type))
    except Exception as exc:
        _note_failure(exc)
        return None

    if any(len(vector) != EMBEDDING_DIM for vector in out):
        _note_failure(
            ValueError(
                f"{get_settings().embedding_model} returned {len(out[0]) if out else 0} "
                f"dimensions; the memories column is {EMBEDDING_DIM}"
            )
        )
        return None

    _note_success()
    return out


def embed_passages(texts: list[str]) -> list[list[float]] | None:
    """Embed things being *stored*. Returns None when the provider is unavailable."""
    return _embed(texts, "passage")


def embed_query(text: str) -> list[float] | None:
    """Embed a lookup. This model is asymmetric, so queries are not passages."""
    result = _embed([text], "query")
    return result[0] if result else None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
