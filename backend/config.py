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
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "12")))
    max_tickets_per_run: int = field(
        default_factory=lambda: int(os.getenv("MAX_TICKETS_PER_RUN", "24"))
    )
    run_concurrency: int = field(default_factory=lambda: int(os.getenv("RUN_CONCURRENCY", "2")))
    # How many times a run revisits tickets QA sent back.
    max_run_passes: int = field(default_factory=lambda: int(os.getenv("MAX_RUN_PASSES", "2")))

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

    @property
    def workspaces_dir(self) -> str:
        return os.path.join(self.data_dir, "workspaces")


@lru_cache
def get_settings() -> Settings:
    return Settings()
