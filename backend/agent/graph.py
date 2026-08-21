"""LangGraph runtime for the AI employee.

One node per turn today (prompt -> model -> reply). The graph exists so tool
calls, reflection and memory-rewrite nodes can be added as edges later without
changing the API surface.
"""

import logging
import os
import time
from collections.abc import Iterator
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from . import cache
from .llm import complete, stream_chat
from .memory import AgentState, assistant_message, compile_system_prompt

log = logging.getLogger(__name__)

DB_CONNECT_ATTEMPTS = int(os.getenv("DB_CONNECT_ATTEMPTS", "10"))
DB_RETRY_SECONDS = float(os.getenv("DB_RETRY_SECONDS", "2"))


def _emit(kind: str, delta: str) -> None:
    """Push a token to the caller when the graph is run with stream_mode='custom'."""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:  # not streaming, or an older langgraph
        return
    if writer:
        writer({"type": kind, "delta": delta})


def build_prompt(state: AgentState) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": compile_system_prompt(state)}]
    messages.extend(
        {"role": m["role"], "content": m["content"]}
        for m in state.get("messages", [])
        if m.get("role") != "system"
    )
    return messages


def call_model_node(state: AgentState) -> dict:
    messages = build_prompt(state)
    cache_key = repr(messages)

    hit = cache.lookup(cache_key)
    if hit:
        log.info("cache hit")
        _emit("reasoning", hit["reasoning"])
        _emit("content", hit["content"])
        return {
            "messages": [assistant_message(hit["content"])],
            "current_reasoning": hit["reasoning"],
        }

    reasoning_parts: list[str] = []
    content_parts: list[str] = []
    for kind, delta in stream_chat(messages):
        (reasoning_parts if kind == "reasoning" else content_parts).append(delta)
        _emit(kind, delta)

    reasoning, content = "".join(reasoning_parts), "".join(content_parts)
    cache.store(cache_key, reasoning, content)

    return {
        "messages": [assistant_message(content)],
        "current_reasoning": reasoning,
    }


def build_graph() -> StateGraph:
    workflow = StateGraph(AgentState)
    workflow.add_node("call_model", call_model_node)
    workflow.add_edge(START, "call_model")
    workflow.add_edge("call_model", END)
    return workflow


def create_checkpointer() -> tuple[Any, Any]:
    """Return (checkpointer, closable).

    Uses Postgres when DATABASE_URL is set so threads survive restarts, and an
    in-process saver otherwise (tests, `uvicorn` without a database).
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.warning("DATABASE_URL not set - falling back to in-memory checkpoints")
        return InMemorySaver(), None

    import psycopg
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    # `setup()` issues DDL, which needs autocommit; the pooled connections used
    # for checkpoint reads/writes do not. Retry first: on a cold `docker compose
    # up` the database (and even its DNS name) can lag the backend by seconds.
    for attempt in range(1, DB_CONNECT_ATTEMPTS + 1):
        try:
            with psycopg.connect(db_url, autocommit=True, connect_timeout=5) as conn:
                PostgresSaver(conn).setup()
            break
        except psycopg.OperationalError as exc:
            if attempt == DB_CONNECT_ATTEMPTS:
                raise
            log.warning(
                "Database not ready (%s); retry %s/%s in %ss",
                exc,
                attempt,
                DB_CONNECT_ATTEMPTS,
                DB_RETRY_SECONDS,
            )
            time.sleep(DB_RETRY_SECONDS)

    pool = ConnectionPool(conninfo=db_url, max_size=20, open=True)
    return PostgresSaver(pool), pool


def compile_agent(checkpointer: Any):
    return build_graph().compile(checkpointer=checkpointer)


def stream_events(agent, state: dict, config: dict) -> Iterator[dict]:
    """Yield {'type': 'reasoning'|'content', 'delta': str} as the turn runs."""
    yield from agent.stream(state, config=config, stream_mode="custom")


def run_turn(agent, state: dict, config: dict) -> dict:
    return agent.invoke(state, config=config)


__all__ = [
    "build_graph",
    "compile_agent",
    "create_checkpointer",
    "run_turn",
    "stream_events",
    "complete",
]
