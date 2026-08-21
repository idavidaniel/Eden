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

import db as db_module  # noqa: E402


def _sqlite_url(url: str) -> str:
    return url


db_module.sqlalchemy_url = _sqlite_url

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from models.base import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def schema():
    import models  # noqa: F401

    Base.metadata.create_all(db_module.get_engine())
    yield
    Base.metadata.drop_all(db_module.get_engine())


@pytest.fixture
def client():
    with TestClient(main.app) as test_client:
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
