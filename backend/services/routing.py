"""Which model answers for which employee, doing which job.

Every model on this provider sits behind one base URL and one key, so routing is
a lookup rather than an integration. A planner can be a 253B model while the
engineer that writes the tenth file of the day is a fast one, and the cost of
that choice shows up per employee in `usage_events`.
"""

import logging
import os
from functools import lru_cache

from config import get_settings

log = logging.getLogger(__name__)

# Jobs a turn can be doing. `model_policy` on an employee may name a model for
# any of them; anything unnamed falls back to "default", then to the company's.
PURPOSES = ["default", "plan", "work", "review", "evaluate", "reflect", "chat", "embed"]

# Sensible starting points. Deliberately conservative: the fast model does the
# bulk, and only the jobs where being wrong is expensive get a bigger one.
SUGGESTED = {
    "plan": "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    "review": "moonshotai/kimi-k3",
    "evaluate": "moonshotai/kimi-k3",
}


@lru_cache
def known_models() -> tuple[str, ...]:
    """Model ids the provider offers, if it will tell us. Never fatal."""
    from agents.llm import get_client

    try:
        return tuple(sorted(model.id for model in get_client().models.list().data))
    except Exception as exc:
        log.info("could not list models: %s", exc)
        return ()


def model_for(employee=None, purpose: str = "default", company=None) -> str | None:
    """The model this turn should use. None means the configured default."""
    policy = dict((company.settings or {}).get("model_policy", {})) if company is not None else {}
    if employee is not None:
        policy.update(employee.model_policy or {})

    chosen = policy.get(purpose) or policy.get("default")
    if not chosen and employee is not None:
        chosen = employee.model
    if not chosen:
        chosen = os.getenv(f"MODEL_{purpose.upper()}", "").strip() or None
    return chosen or None


def resolved(employee=None, purpose: str = "default", company=None) -> str:
    """The model that will actually be called, for display."""
    return model_for(employee, purpose, company) or get_settings().model


def describe(employee=None, company=None) -> dict:
    return {
        "default": resolved(employee, "default", company),
        "by_purpose": {
            purpose: resolved(employee, purpose, company)
            for purpose in PURPOSES
            if purpose != "embed"
        },
        "embedding": get_settings().embedding_model,
        "suggested": SUGGESTED,
    }
