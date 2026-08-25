"""Central configuration, loaded from the environment (and a local .env file)."""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _csv(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # --- model provider -------------------------------------------------
    nvidia_api_key: str | None = field(default_factory=lambda: os.getenv("NVIDIA_API_KEY"))
    nvidia_base_url: str = field(
        default_factory=lambda: os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    )
    model: str = field(
        default_factory=lambda: os.getenv("MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    )
    planner_model: str = field(default_factory=lambda: os.getenv("PLANNER_MODEL", ""))
    # Asymmetric retrieval model, 1024 dimensions — inside pgvector's HNSW ceiling.
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "nvidia/nv-embedqa-e5-v5")
    )
    max_tokens: int = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "4096")))
    reasoning_budget: int = field(
        default_factory=lambda: int(os.getenv("REASONING_BUDGET", "4096"))
    )

    # --- infrastructure -------------------------------------------------
    database_url: str | None = field(default_factory=lambda: os.getenv("DATABASE_URL"))
    data_dir: str = field(default_factory=lambda: os.getenv("DATA_DIR", "/data"))
    # Seals employee passwords and external tool secrets at rest.
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", "dev-insecure-key"))

    # --- agent runtime --------------------------------------------------
    # Rounds of tool calls one employee gets per ticket. Too low and they spend
    # the budget looking around and never write anything.
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "32")))
    max_tickets_per_run: int = field(
        default_factory=lambda: int(os.getenv("MAX_TICKETS_PER_RUN", "24"))
    )
    run_concurrency: int = field(default_factory=lambda: int(os.getenv("RUN_CONCURRENCY", "2")))
    # Upper bound on passes over the board. A run also stops early once a pass
    # finishes nothing, so this is a ceiling rather than a target.
    max_run_passes: int = field(default_factory=lambda: int(os.getenv("MAX_RUN_PASSES", "4")))

    # --- api ------------------------------------------------------------
    cors_origins: list[str] = field(
        default_factory=lambda: _csv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    )
    mcp_protocol_version: str = field(
        default_factory=lambda: os.getenv("MCP_PROTOCOL_VERSION", "2026-07-28")
    )
    require_mcp_auth: bool = field(
        default_factory=lambda: os.getenv("REQUIRE_MCP_AUTH", "true").lower() != "false"
    )

    # --- people signing in ----------------------------------------------
    # Short enough that a stolen access token is worth little, long enough that
    # the refresh round trip is not on every request.
    access_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    )
    refresh_token_days: int = field(
        default_factory=lambda: int(os.getenv("REFRESH_TOKEN_DAYS", "7"))
    )
    # The window between "your password was right" and "here is your code".
    two_factor_token_minutes: int = field(
        default_factory=lambda: int(os.getenv("TWO_FACTOR_TOKEN_MINUTES", "5"))
    )
    # Set only when the browser and the API are on different hosts.
    cookie_domain: str = field(default_factory=lambda: os.getenv("COOKIE_DOMAIN", ""))
    # Off in development because localhost is not https; on everywhere else.
    cookie_secure: bool = field(
        default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true"
    )
    # Signing key for access tokens. Falls back to SECRET_KEY so a fresh install
    # works, but they should differ: one seals data, the other mints identity.
    jwt_secret: str = field(
        default_factory=lambda: os.getenv("JWT_SECRET", "")
        or os.getenv("SECRET_KEY", "dev-insecure-key")
    )
    # Off in the test suite, which signs up hundreds of times from one address.
    # A dedicated test switches it back on to prove it still refuses.
    rate_limits_enabled: bool = field(
        default_factory=lambda: os.getenv("RATE_LIMITS", "on").lower() not in {"off", "false", "0"}
    )
    login_attempts_per_minute: str = field(
        default_factory=lambda: os.getenv("LOGIN_RATE_LIMIT", "10/minute")
    )
    signup_attempts_per_hour: str = field(
        default_factory=lambda: os.getenv("SIGNUP_RATE_LIMIT", "20/hour")
    )
    # Consecutive failures before an account stops answering for a while. The
    # rate limit protects the endpoint; this protects one account from a slow
    # distributed guess that never trips a per-IP limit.
    max_failed_logins: int = field(
        default_factory=lambda: int(os.getenv("MAX_FAILED_LOGINS", "8"))
    )
    lockout_minutes: int = field(default_factory=lambda: int(os.getenv("LOCKOUT_MINUTES", "15")))

    @property
    def workspaces_dir(self) -> str:
        return os.path.join(self.data_dir, "workspaces")


@lru_cache
def get_settings() -> Settings:
    return Settings()
