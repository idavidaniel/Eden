"""Response cache in front of the LLM.

This is an exact-prompt (SHA-256 keyed) cache, not a semantic one: two prompts
that mean the same thing but differ by a word are separate entries. Upgrading to
semantic hits means embedding the prompt and doing a vector search over cached
keys (Redis Stack's `FT.SEARCH` or pgvector); the interface below is designed so
that swap is local to this module.

Every operation degrades to a miss when Redis is unavailable, so a dead cache
never takes the API down with it.
"""

import hashlib
import json
import logging
from typing import Any

from config import get_settings

log = logging.getLogger(__name__)

_client: Any = None
_client_initialised = False


def get_client():
    """Return a shared Redis client, or None when caching is not configured."""
    global _client, _client_initialised
    if _client_initialised:
        return _client

    _client_initialised = True
    settings = get_settings()
    if not settings.redis_url:
        log.info("REDIS_URL not set - response caching disabled")
        _client = None
        return None

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _client = client
    except Exception as exc:  # pragma: no cover - depends on external service
        log.warning("Redis unavailable (%s) - response caching disabled", exc)
        _client = None
    return _client


def reset_client() -> None:
    """Drop the memoised client (used by tests and after config changes)."""
    global _client, _client_initialised
    _client, _client_initialised = None, False


def _key(prompt: str) -> str:
    settings = get_settings()
    digest = hashlib.sha256(f"{settings.model}\n{prompt}".encode()).hexdigest()
    return f"llm:{digest}"


def lookup(prompt: str) -> dict | None:
    client = get_client()
    if client is None:
        return None
    try:
        raw = client.get(_key(prompt))
    except Exception as exc:  # pragma: no cover - depends on external service
        log.warning("Cache read failed: %s", exc)
        return None
    return json.loads(raw) if raw else None


def store(prompt: str, reasoning: str, content: str) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.set(
            _key(prompt),
            json.dumps({"reasoning": reasoning, "content": content}),
            ex=get_settings().cache_ttl_seconds,
        )
    except Exception as exc:  # pragma: no cover - depends on external service
        log.warning("Cache write failed: %s", exc)
