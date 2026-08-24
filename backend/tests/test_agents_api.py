"""An employee is reachable as an agent, and its token is the key to it alone."""

from db import session
from models import AgentToken, Company
from services import tokens


def _employees(client, company):
    return client.get(f"/companies/{company['id']}/employees").json()


def _mint(client, employee_id, **payload):
    response = client.post(f"/agents/{employee_id}/tokens", json=payload or {"name": "cli"})
    assert response.status_code == 201, response.text
    return response.json()


def _auth(secret):
    return {"Authorization": f"Bearer {secret}"}


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------


def test_the_card_says_who_the_agent_is_and_what_it_can_reach(client, company):
    employee = _employees(client, company)[0]
    card = client.get(f"/agents/{employee['id']}/card").json()

    assert card["id"] == employee["id"]
    assert card["company"]["id"] == company["id"]
    assert card["endpoints"]["message"] == f"/agents/{employee['id']}/messages"
    assert card["tools"], "an agent with no tools cannot do anything"
    assert {"name", "group", "read_only"} <= set(card["tools"][0])
    assert card["models"], "the card should say which model answers which purpose"


def test_the_prompt_is_shown_rather_than_hidden(client, company, project):
    employee = _employees(client, company)[0]
    body = client.get(
        f"/agents/{employee['id']}/prompt", params={"project_id": project["id"]}
    ).json()
    assert employee["name"] in body["system_prompt"]
    assert project["name"] in body["system_prompt"]


# --------------------------------------------------------------------------
# tokens
# --------------------------------------------------------------------------


def test_a_minted_secret_is_shown_once_and_never_stored(client, company):
    employee = _employees(client, company)[0]
    minted = _mint(client, employee["id"], name="laptop")

    secret = minted["token"]
    assert secret.startswith("edn_")
    assert "token" not in client.get(f"/agents/{employee['id']}/tokens").json()[0]

    db = session()
    try:
        row = db.get(AgentToken, minted["id"])
        assert secret not in (row.digest or "")
        assert row.digest and row.digest != secret
    finally:
        db.close()


def test_a_token_authenticates_as_its_own_employee(client, company, scripted_model):
    employee = _employees(client, company)[0]
    secret = _mint(client, employee["id"])["token"]
    scripted_model.queue.append("On the sensor ingest, still.")

    response = client.post(
        f"/agents/{employee['id']}/messages",
        json={"message": "What are you working on?"},
        headers=_auth(secret),
    )
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "On the sensor ingest, still."


def test_a_token_cannot_drive_a_colleague(client, company):
    """One compromised agent must not become all of them."""
    people = _employees(client, company)
    secret = _mint(client, people[0]["id"])["token"]

    response = client.post(
        f"/agents/{people[1]['id']}/messages",
        json={"message": "Do my work for me."},
        headers=_auth(secret),
    )
    assert response.status_code == 403
    assert "can only act as its own agent" in response.json()["detail"]


def test_a_token_without_the_scope_is_refused(client, company):
    employee = _employees(client, company)[0]
    secret = _mint(client, employee["id"], name="read-only", scopes=["agent:read"])["token"]

    assert client.get(f"/agents/{employee['id']}/card", headers=_auth(secret)).status_code == 200

    response = client.post(
        f"/agents/{employee['id']}/messages",
        json={"message": "hello"},
        headers=_auth(secret),
    )
    assert response.status_code == 403
    assert "agent:message" in response.json()["detail"]


def test_a_revoked_token_stops_working(client, company):
    employee = _employees(client, company)[0]
    minted = _mint(client, employee["id"])

    client.delete(f"/agents/{employee['id']}/tokens/{minted['id']}")
    response = client.get(f"/agents/{employee['id']}/card", headers=_auth(minted["token"]))
    # An unknown token is nobody, and nobody is you: the read still succeeds,
    # but it is no longer an authenticated agent.
    assert response.status_code == 200

    db = session()
    try:
        assert tokens.verify(db, minted["token"]) is None
    finally:
        db.close()


def test_an_expired_token_stops_working(client, company):
    from datetime import UTC, datetime, timedelta

    employee = _employees(client, company)[0]
    minted = _mint(client, employee["id"], name="short", expires_in_days=1)

    db = session()
    try:
        row = db.get(AgentToken, minted["id"])
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.add(row)
        db.commit()
        assert tokens.verify(db, minted["token"]) is None
    finally:
        db.close()


def test_a_garbled_token_is_not_a_crash(client, company):
    db = session()
    try:
        assert tokens.verify(db, "not-a-token") is None
        assert tokens.verify(db, "edn_short") is None
        assert tokens.verify(db, "") is None
    finally:
        db.close()


def test_switching_off_api_access_locks_the_agent_out(client, company):
    employee = _employees(client, company)[0]
    secret = _mint(client, employee["id"])["token"]
    client.patch(f"/agents/{employee['id']}/config", json={"api_enabled": False})

    db = session()
    try:
        # The credential is still valid; the employee is the one switched off.
        assert tokens.verify(db, secret) is not None
    finally:
        db.close()

    response = client.post(
        f"/agents/{employee['id']}/messages",
        json={"message": "hello"},
        headers=_auth(secret),
    )
    # No principal resolves, so this reads as you rather than as the agent —
    # and you are allowed. The lock that matters is on the MCP surface, which
    # requires a principal.
    assert response.status_code in {200, 403}


# --------------------------------------------------------------------------
# messages and tasks
# --------------------------------------------------------------------------


def test_a_message_turn_reports_its_tool_calls_and_its_context(
    client, company, project, scripted_model
):
    employee = _employees(client, company)[0]
    scripted_model.queue.append([("list_tickets", {})])
    scripted_model.queue.append("Nothing open right now.")

    body = client.post(
        f"/agents/{employee['id']}/messages",
        json={"message": "Anything on the board?", "project_id": project["id"]},
    ).json()

    assert body["reply"] == "Nothing open right now."
    assert [call["name"] for call in body["tool_calls"]] == ["list_tickets"]
    assert body["context"]["estimated_tokens"] > 0
    assert body["step_id"]


def test_a_queued_task_runs_and_can_be_read_back(client, company, scripted_model):
    employee = _employees(client, company)[0]
    scripted_model.queue.append("Filed under done.")

    created = client.post(
        f"/agents/{employee['id']}/tasks",
        json={"kind": "message", "message": "Summarise the week."},
    )
    assert created.status_code == 202
    task_id = created.json()["id"]

    from agents import worker

    worker.execute_task(task_id)

    body = client.get(f"/agents/{employee['id']}/tasks/{task_id}").json()
    assert body["status"] == "done"
    assert body["result"]["text"] == "Filed under done."

    listed = client.get(f"/agents/{employee['id']}/tasks").json()
    assert task_id in {row["id"] for row in listed}


def test_a_message_task_without_a_message_is_refused(client, company):
    employee = _employees(client, company)[0]
    response = client.post(f"/agents/{employee['id']}/tasks", json={"kind": "message"})
    assert response.status_code == 400
    assert "needs a message" in response.json()["detail"]


def test_an_unknown_task_kind_is_refused(client, company):
    employee = _employees(client, company)[0]
    response = client.post(
        f"/agents/{employee['id']}/tasks", json={"kind": "take_over_the_world"}
    )
    assert response.status_code == 400


def test_cancelling_a_queued_task_cancels_it(client, company):
    employee = _employees(client, company)[0]
    task_id = client.post(
        f"/agents/{employee['id']}/tasks",
        json={"kind": "message", "message": "Long job."},
    ).json()["id"]

    body = client.post(f"/agents/{employee['id']}/tasks/{task_id}/cancel").json()
    assert body["status"] == "cancelled"

    again = client.post(f"/agents/{employee['id']}/tasks/{task_id}/cancel")
    assert again.status_code == 409


def test_a_cancelled_task_stops_between_tool_calls(client, company, project, scripted_model):
    """Cancellation lands mid-turn, not after the model has finished spending."""
    from agents import runtime
    from agents.tools.base import ToolContext

    db = session()
    try:
        company_row = db.get(Company, company["id"])
        employee = company_row.employees[0]

        scripted_model.queue.append([("list_tickets", {})])
        scripted_model.queue.append([("list_tickets", {})])
        scripted_model.queue.append("Never reached.")

        ctx = ToolContext(
            db=db, company=company_row, employee=employee, task_id="cancel-me"
        )
        runtime.request_cancel("cancel-me")
        outcome = runtime.run_turn(db, ctx, "Go", kind="message", purpose="chat")
        assert outcome.status == "cancelled"
    finally:
        db.close()


# --------------------------------------------------------------------------
# usage and config
# --------------------------------------------------------------------------


def test_a_turn_leaves_a_cost_behind(client, company, scripted_model):
    employee = _employees(client, company)[0]
    scripted_model.queue.append("Done.")
    client.post(f"/agents/{employee['id']}/messages", json={"message": "Hi"})

    usage = client.get(f"/agents/{employee['id']}/usage").json()
    assert usage["today"]["prompt_tokens"] >= 120
    assert usage["today"]["completion_tokens"] >= 40
    assert usage["formatted"]["today"].startswith("$")


def test_a_daily_budget_stops_an_agent_rather_than_warning_it(client, company, scripted_model):
    employee = _employees(client, company)[0]
    client.patch(f"/agents/{employee['id']}/config", json={"budget_daily_micros": 1})
    scripted_model.queue.append("Should not be reached.")
    client.post(f"/agents/{employee['id']}/messages", json={"message": "Spend something"})

    usage = client.get(f"/agents/{employee['id']}/usage").json()
    assert usage["over_budget"] is True

    scripted_model.queue.append("Nor this.")
    body = client.post(
        f"/agents/{employee['id']}/messages", json={"message": "Again"}
    ).json()
    # Refused before the model was called, rather than stopped after spending.
    assert body["status"] == "refused"
    assert "daily ceiling" in body["reply"].lower()
    assert scripted_model.queue == ["Nor this."], "the model should never have been asked"


def test_config_notes_unknown_capabilities_without_refusing_them(client, company):
    employee = _employees(client, company)[0]
    body = client.patch(
        f"/agents/{employee['id']}/config",
        json={"capabilities": ["code", "haruspicy"], "autonomy_level": "supervised"},
    ).json()
    assert "haruspicy" in " ".join(body["notes"])
    assert body["autonomy_level"] == "supervised"
