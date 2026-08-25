"""The shapes the browser is written against.

Every one of these was wrong at least once. The API returned a bare list where
the client expected an envelope, `usage` where the client read `spend`, `tip`
where it read `head` — and none of it raised, because reading a missing field in
JavaScript yields `undefined` and `undefined` formats as "$0.00". A cost figure
that is silently always zero is worse than one that is missing, because it looks
like an answer.

TypeScript cannot catch this: it only knows what the hand-written client claims.
So the claims are asserted here, against the running application, where a change
to a serializer breaks a test instead of a page.

Adding a field is fine and deliberately not caught. Renaming or removing one the
interface reads is not.
"""

import pytest


def _company(client) -> str:
    response = client.post("/companies", json={"name": "Shape Check", "starting_team": []})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _keys(body) -> set:
    assert isinstance(body, dict), f"expected an object, got {type(body).__name__}"
    return set(body)


# --------------------------------------------------------------------------
# lists that must not become envelopes, and envelopes that must not become lists
# --------------------------------------------------------------------------


def test_packs_is_a_bare_list(client):
    """The founding dialog reads `packs.find(...)` straight off the response."""
    body = client.get("/packs").json()
    assert isinstance(body, list), "the industry picker iterates this directly"
    assert body, "no packs installed"
    assert {"key", "name", "description", "roles", "work_item_kinds"} <= _keys(body[0])
    assert {"key", "title", "department", "capabilities"} <= _keys(body[0]["roles"][0])


@pytest.mark.parametrize(
    "path",
    ["/companies", "/roles", "/companies/{id}/employees", "/companies/{id}/channels",
     "/companies/{id}/meetings", "/companies/{id}/tool-calls", "/companies/{id}/sources",
     "/companies/{id}/projects", "/users/me/sessions"],
)
def test_these_are_bare_lists(client, path):
    company_id = _company(client) if "{id}" in path else ""
    body = client.get(path.replace("{id}", company_id)).json()
    assert isinstance(body, list), f"{path} is iterated directly by the interface"


# --------------------------------------------------------------------------
# envelopes, field by field
# --------------------------------------------------------------------------


def test_ops_carries_the_fields_the_dashboard_reads(client):
    """`usage`, not `spend`. Reading the wrong one renders $0.00 forever."""
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/ops").json()

    assert {
        "clock",
        "autonomous",
        "halted",
        "halt_reason",
        "tasks",
        "in_flight",
        "checks",
        "usage",
        "by_employee",
        "cost_note",
    } <= _keys(body)

    assert isinstance(body["tasks"], list), "the queue panel counts these itself"
    assert {"today", "month", "all_time"} <= _keys(body["usage"])
    for window in ("today", "month", "all_time"):
        assert {"calls", "prompt_tokens", "completion_tokens", "cost_micros"} <= _keys(
            body["usage"][window]
        )
    assert {"running", "ticks", "dispatched", "reclaimed", "tick_seconds"} <= _keys(
        body["clock"]
    )


def test_the_ledger_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/ledger").json()
    assert {"entries", "tip", "height"} <= _keys(body)
    assert isinstance(body["entries"], list)


def test_the_inbox_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/inbox").json()
    assert {"approvals", "blocked_items", "count"} <= _keys(body)


def test_the_artifacts_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/artifacts").json()
    assert {"artifacts", "by_kind"} <= _keys(body)


def test_the_documents_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/documents").json()
    assert {"spaces", "documents"} <= _keys(body)


def test_the_pack_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/pack").json()
    assert {"key", "name", "roles", "artifact_kinds", "checks", "work_item_kinds"} <= _keys(body)
    # Unlike /packs, these are database rows and carry an ordering.
    assert "position" in _keys(body["roles"][0])


def test_the_connections_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/connections").json()
    assert {"connections", "mcp_servers", "egress"} <= _keys(body)
    assert {"open", "allow", "default"} <= _keys(body["egress"])


def test_the_catalogue_envelope(client):
    body = client.get("/connections/catalogue").json()
    assert {"providers", "tools", "runners"} <= _keys(body)


def test_the_performance_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/performance").json()
    assert "employees" in _keys(body)
    assert isinstance(body["employees"], list)


def test_the_authored_tools_envelope(client):
    company_id = _company(client)
    body = client.get(f"/companies/{company_id}/authored-tools").json()
    assert {"tools", "waiting", "usable_now"} <= _keys(body)


def test_the_work_item_checks_envelope(client):
    company_id = _company(client)
    project_id = client.post(
        f"/companies/{company_id}/projects", json={"name": "P", "brief": "b"}
    ).json()["id"]
    item_id = client.post(
        f"/projects/{project_id}/work-items", json={"title": "t", "kind": "task"}
    ).json()["id"]

    body = client.get(f"/work-items/{item_id}/checks").json()
    assert {"checks", "results", "verdict", "artifacts"} <= _keys(body)


def test_the_health_envelope(anonymous_client):
    body = anonymous_client.get("/health").json()
    assert {"status", "model", "llm_configured", "embeddings", "clock"} <= _keys(body)


# --------------------------------------------------------------------------
# the account, which the whole interface hangs off
# --------------------------------------------------------------------------


def test_the_account_envelope(client, account):
    body = client.get("/users/me").json()
    assert {
        "id",
        "email",
        "full_name",
        "is_active",
        "is_owner",
        "created_at",
        "tenant",
        "two_factor",
        "companies",
        "active_sessions",
    } <= _keys(body)
    assert {"id", "name", "slug"} <= _keys(body["tenant"])
    assert {"enabled", "backup_codes_left", "setup_started"} <= _keys(body["two_factor"])
    assert "hashed_password" not in body, "a password hash must never leave the server"
    assert "totp_secret_sealed" not in body


def test_signing_in_returns_what_the_client_stores(anonymous_client):
    import uuid

    body = anonymous_client.post(
        "/auth/signup",
        json={
            "email": f"shape-{uuid.uuid4().hex[:8]}@example.com",
            "password": "correct-horse-battery",
            "full_name": "Shape",
        },
    ).json()
    assert {"status", "access_token", "refresh_token", "expires_in", "user"} <= _keys(body)
    assert body["status"] == "signed_in"
    assert {"id", "email", "tenant", "two_factor"} <= _keys(body["user"])


def test_a_turn_returns_what_the_console_renders(client, company, scripted_model):
    scripted_model.queue.append("Done.")
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]
    body = client.post(
        f"/agents/{employee['id']}/messages", json={"message": "Hello"}
    ).json()

    assert {"task_id", "reply", "status", "tool_calls", "context", "step_id"} <= _keys(body)
    # The console prints these per tier; renaming one empties that panel.
    assert {"blocks", "estimated_tokens", "total_chars"} <= _keys(body["context"])


def test_the_agent_card_envelope(client, company):
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]
    body = client.get(f"/agents/{employee['id']}/card").json()
    assert {
        "id",
        "name",
        "title",
        "company",
        "capabilities",
        "tools",
        "models",
        "endpoints",
    } <= _keys(body)
    assert {"name", "group", "description", "read_only"} <= _keys(body["tools"][0])


def test_the_memory_envelope(client, company):
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]
    body = client.get(f"/agents/{employee['id']}/memory").json()
    assert {"blocks", "memories", "retrieval_mode", "counts"} <= _keys(body)
    assert {"label", "content", "char_limit", "pinned", "version"} <= _keys(body["blocks"][0])
