"""Test fixtures.

The suite runs against a SQLite database and a stubbed model provider, so it
needs no Postgres, no Redis and no API key.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEMP_DATA = tempfile.mkdtemp(prefix="eden-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEMP_DATA}/test.db"
os.environ["DATA_DIR"] = TEMP_DATA
os.environ["SECRET_KEY"] = "test-secret"
os.environ.setdefault("NVIDIA_API_KEY", "test-key")
# The suite signs up hundreds of times from one address, which is exactly what
# the limiter exists to stop. `test_auth.py` switches it back on to prove it does.
os.environ.setdefault("RATE_LIMITS", "off")

import db as db_module  # noqa: E402


def _sqlite_url(url: str) -> str:
    return url


db_module.sqlalchemy_url = _sqlite_url

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from models.base import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    """Build the schema from the models and mark it current.

    The suite runs on SQLite, where several of the Postgres migrations (a vector
    index, a constraint rename) have nothing to do. Stamping head means the
    application's own `init_db()` finds an up-to-date database and does nothing,
    while `tests/test_migrations.py` exercises the real migration path against
    Postgres where it belongs.
    """
    from alembic import command

    import models  # noqa: F401

    Base.metadata.create_all(db_module.get_engine())
    command.stamp(db_module._alembic_config(), "head")
    yield
    Base.metadata.drop_all(db_module.get_engine())


@pytest.fixture
def anonymous_client():
    """A client that has not signed in. For testing that it cannot get in."""
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def account(anonymous_client):
    """A signed-up person, and the organisation they own.

    Each test gets its own, so one test's data is never visible to another —
    which also means the suite is exercising tenant isolation constantly rather
    than only in the tests that mention it.
    """
    import uuid

    email = f"person-{uuid.uuid4().hex[:10]}@example.com"
    password = "correct-horse-battery"
    response = anonymous_client.post(
        "/auth/signup",
        json={"email": email, "password": password, "full_name": "Test Person"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return {**body["user"], "email": email, "password": password, "tokens": body}


@pytest.fixture
def client(account):
    """Signed in. Almost every test wants this, so it is the default."""
    with TestClient(main.app) as test_client:
        test_client.cookies.set("eden_access", account["tokens"]["access_token"])
        test_client.cookies.set("eden_refresh", account["tokens"]["refresh_token"])
        yield test_client


@pytest.fixture
def company(client):
    response = client.post(
        "/companies",
        json={
            "name": "Northwind Labs",
            "tagline": "Instrumentation for small factories",
            "description": "We build sensor dashboards.",
            "industry": "Industrial IoT",
            "starting_team": ["engineering_manager", "backend_engineer", "qa_engineer"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def project(client, company):
    response = client.post(
        f"/companies/{company['id']}/projects",
        json={"name": "Sensor Portal", "brief": "Ship a portal that lists sensors."},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def law_firm(client):
    response = client.post(
        "/companies",
        json={
            "name": "Marsh & Idris",
            "pack": "law_firm",
            "description": "Commercial contracts for small manufacturers.",
            "starting_team": ["managing_partner", "associate"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


class FakeCompletion:
    """Shaped like the provider's reply, so nothing under test knows the difference."""

    def __init__(self, content="", tool_calls=None, reasoning=""):
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "message": type(
                        "Message",
                        (),
                        {
                            "content": content,
                            "reasoning_content": reasoning,
                            "tool_calls": tool_calls or [],
                        },
                    )()
                },
            )()
        ]
        self.usage = type("Usage", (), {"prompt_tokens": 120, "completion_tokens": 40})()


def fake_tool_call(name, arguments):
    import json as _json

    return type(
        "Call",
        (),
        {
            "id": f"call_{name}",
            "function": type(
                "Fn", (), {"name": name, "arguments": _json.dumps(arguments)}
            )(),
        },
    )()


@pytest.fixture
def scripted_model(monkeypatch):
    """Drive the agent loop without a provider.

    Push replies onto the queue; each `chat` call pops one. A reply is either a
    string (the turn ends) or a list of (tool_name, arguments) pairs.
    """
    from agents import llm
    from services import usage

    queue: list = []
    seen: list = []

    def scripted_chat(messages, tools=None, model=None, **kwargs):
        seen.append({"messages": messages, "tools": tools, "model": model})
        # The real provider wrapper is what writes usage, so the stand-in does
        # too — otherwise every accounting path would be untested.
        usage.record(
            model or "stub-model", prompt_tokens=120, completion_tokens=40, latency_ms=5
        )
        if not queue:
            return llm.ModelCall(reasoning="", content="Nothing left to do.", tool_calls=[])
        nxt = queue.pop(0)
        if isinstance(nxt, str):
            return llm.ModelCall(reasoning="thinking", content=nxt, tool_calls=[])
        return llm.ModelCall(
            reasoning="",
            content="",
            tool_calls=[
                {"id": f"c{index}", "name": name, "arguments": arguments}
                for index, (name, arguments) in enumerate(nxt)
            ],
        )

    monkeypatch.setattr(llm, "chat", scripted_chat)
    monkeypatch.setattr("agents.runtime.chat", scripted_chat)
    return type("Script", (), {"queue": queue, "seen": seen})()


@pytest.fixture
def structured_answers(monkeypatch):
    """Replace forced-tool-call output with canned answers, keyed by tool name."""
    from agents import llm

    answers: dict = {}
    calls: list = []

    def scripted(messages, name, description, parameters, model=None, max_tokens=3000):
        calls.append({"name": name, "messages": messages})
        if name not in answers:
            raise AssertionError(f"No scripted answer for structured_call({name})")
        value = answers[name]
        return value(messages) if callable(value) else value

    monkeypatch.setattr(llm, "structured_call", scripted)
    monkeypatch.setattr("agents.engine.structured_call", scripted)
    monkeypatch.setattr("agents.reflect.structured_call", scripted)
    return type("Structured", (), {"answers": answers, "calls": calls})()


@pytest.fixture
def no_embeddings(monkeypatch):
    """Force the lexical retrieval path, which is what runs without a provider."""
    from services import embeddings

    monkeypatch.setattr(embeddings, "available", lambda: False)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: None)
    monkeypatch.setattr(embeddings, "embed_query", lambda text: None)


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic vectors with real structure: shared words move them together.

    Not a stand-in for the real model — it exists so the *vector code path* is
    exercised, including cosine ranking and the merge threshold.
    """
    import hashlib

    from services import embeddings, memory

    def vector(text: str) -> list[float]:
        words = sorted(memory.tokenise(text))
        out = [0.0] * 32
        for word in words:
            digest = hashlib.sha256(word.encode()).digest()
            for index in range(32):
                out[index] += digest[index] / 255.0
        total = sum(value * value for value in out) ** 0.5 or 1.0
        return [value / total for value in out]

    monkeypatch.setattr(embeddings, "available", lambda: True)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [vector(t) for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: vector(text))
