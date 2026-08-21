import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Tests must never reach a real database, cache or model provider.
os.environ.pop("DATABASE_URL", None)
os.environ.pop("REDIS_URL", None)
os.environ.setdefault("NVIDIA_API_KEY", "test-key")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from agent import graph  # noqa: E402


@pytest.fixture
def fake_llm(monkeypatch):
    """Replace the model with a deterministic two-token stream."""

    def _stream(messages):
        task = messages[-1]["content"]
        yield "reasoning", "thinking about "
        yield "reasoning", task
        yield "content", "answer: "
        yield "content", task.upper()

    monkeypatch.setattr(graph, "stream_chat", _stream)
    return _stream


@pytest.fixture
def client(fake_llm):
    with TestClient(main.app) as test_client:
        yield test_client
