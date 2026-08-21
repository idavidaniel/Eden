"""Central configuration, loaded from the environment (and a local .env file)."""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

# Load the repository-root .env when running outside Docker. Inside the
# container the values arrive as real environment variables and this is a no-op.
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    nvidia_api_key: str | None = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY"))
    nvidia_base_url: str = field(
        default_factory=lambda: os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    )
    model: str = field(
        default_factory=lambda: os.getenv("MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    )
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "4096")))
    reasoning_budget: int = field(
        default_factory=lambda: int(os.getenv("REASONING_BUDGET", "4096"))
    )

    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL"))
    redis_url: str | None = field(default_factory=lambda: os.getenv("REDIS_URL"))

    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )
    reranker_model: str = field(
        default_factory=lambda: os.getenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    )
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "384")))

    cors_origins: list[str] = field(
        default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    )
    mcp_protocol_version: str = field(
        default_factory=lambda: os.getenv("MCP_PROTOCOL_VERSION", "2026-07-28")
    )
    require_mcp_auth: bool = field(
        default_factory=lambda: os.getenv("REQUIRE_MCP_AUTH", "true").lower() != "false"
    )
    cache_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
