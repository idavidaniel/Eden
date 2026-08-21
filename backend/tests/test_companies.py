def test_create_company_hires_the_starting_team(client, company):
    assert company["slug"].startswith("northwind-labs")
    assert company["stats"]["employees"] == 3

    employees = client.get(f"/companies/{company['id']}/employees").json()
    titles = {e["title"] for e in employees}
    assert {"Engineering Manager", "Backend Engineer", "QA Engineer"} == titles


def test_every_employee_gets_accounts_for_their_tools(client, company):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    engineer = next(e for e in employees if e["role_key"] == "backend_engineer")

    tools = {account["tool"] for account in engineer["accounts"]}
    assert tools == set(engineer["toolbelt"])
    for account in engineer["accounts"]:
        assert account["username"].endswith(f"@{company['slug']}.{account['tool']}")


def test_credentials_can_be_revealed_and_rotated(client, company):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    employee_id = employees[0]["id"]

    revealed = client.get(f"/employees/{employee_id}/credentials").json()
    first = revealed["accounts"][0]
    assert len(first["password"]) >= 16
    assert first["token"].startswith(first["tool"][:4])

    rotated = client.post(f"/employees/{employee_id}/credentials/{first['tool']}/rotate").json()
    assert rotated["password"] != first["password"]
    assert rotated["token"] != first["token"]


def test_manager_is_the_default_reporting_line(client, company):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    manager = next(e for e in employees if e["role_key"] == "engineering_manager")
    reports = [e for e in employees if e["id"] != manager["id"]]
    assert all(e["manager_id"] == manager["id"] for e in reports)


def test_hiring_and_offboarding(client, company):
    hired = client.post(
        f"/companies/{company['id']}/employees",
        json={"role_key": "tech_writer", "name": "Wren Ito", "seniority": "Senior"},
    ).json()
    assert hired["title"] == "Technical Writer"
    assert "wiki" in hired["toolbelt"]

    assert client.delete(f"/employees/{hired['id']}").status_code == 204
    assert client.get(f"/employees/{hired['id']}").status_code == 404


def test_roles_catalogue_is_exposed(client):
    roles = client.get("/roles").json()
    keys = {role["key"] for role in roles}
    assert {"engineering_manager", "backend_engineer", "qa_engineer", "tech_writer"} <= keys


def test_activity_feed_records_company_events(client, company):
    feed = client.get(f"/companies/{company['id']}/activity").json()
    kinds = [event["kind"] for event in feed["events"]]
    assert "company.created" in kinds
    assert kinds.count("employee.hired") == 3
    assert feed["cursor"] > 0
