"""What a model call costs, as an estimate the UI is honest about.

Tokens are measured; money is derived. The rates below are per million tokens in
US dollars and are *estimates* for self-hosted-class open models — the provider
bills credits, not line items. Override them with MODEL_PRICES, a JSON object of
`{"model-or-prefix": [prompt_rate, completion_rate]}`.
"""

import json
import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

# Matched by longest prefix, so a family rate covers every size in it.
DEFAULT_RATES: dict[str, tuple[float, float]] = {
    "": (0.20, 0.60),
    "nvidia/nemotron-3.5-lightning": (0.08, 0.24),
    "nvidia/llama-3.1-nemotron-ultra": (0.90, 2.70),
    "nvidia/nv-embedqa": (0.02, 0.0),
    "nvidia/nv-embed": (0.02, 0.0),
    "moonshotai/kimi": (0.55, 2.20),
    "deepseek-ai/deepseek": (0.27, 1.10),
    "openai/gpt-oss": (0.15, 0.60),
    "meta/llama": (0.20, 0.60),
    "qwen/": (0.20, 0.60),
}


@lru_cache
def rates() -> dict[str, tuple[float, float]]:
    table = dict(DEFAULT_RATES)
    raw = os.getenv("MODEL_PRICES", "").strip()
    if raw:
        try:
            for key, value in json.loads(raw).items():
                table[key] = (float(value[0]), float(value[1]))
        except (ValueError, TypeError, IndexError, KeyError):
            log.warning("MODEL_PRICES is not a usable JSON rate table — using defaults.")
    return table


def rate_for(model: str) -> tuple[float, float]:
    table = rates()
    best_key = ""
    for key in table:
        if key and model.startswith(key) and len(key) > len(best_key):
            best_key = key
    return table[best_key]


def cost_micros(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimated cost in millionths of a dollar."""
    prompt_rate, completion_rate = rate_for(model)
    dollars = (prompt_tokens * prompt_rate + completion_tokens * completion_rate) / 1_000_000
    return round(dollars * 1_000_000, 4)


def format_cost(micros: float) -> str:
    dollars = micros / 1_000_000
    if dollars >= 1:
        return f"${dollars:,.2f}"
    if dollars >= 0.01:
        return f"${dollars:.3f}"
    return f"${dollars:.5f}"
