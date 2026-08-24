import pytest

from agents import tools
from agents.tools.base import ToolContext
from db import session
from models import Company, Employee, Project

PROTOCOL = {"Mcp-Protocol-Version": "2026-07-28"}


def mint_token(client, company, role_key="backend_engineer", scopes=None):
    """A real agent token. The MCP surface no longer accepts anything else."""
    employees = client.get(f"/companies/{company['id']}/employees").json()
    employee = next(e for e in employees if e["role_key"] == role_key)
    body = {"name": "test"}
    if scopes is not None:
        body["scopes"] = scopes
    minted = client.post(f"/agents/{employee['id']}/tokens", json=body)
    assert minted.status_code == 201, minted.text
    return employee, minted.json()["token"]


def test_default_channels_exist(client, company):
    channels = client.get(f"/companies/{company['id']}/channels").json()
    assert {c["name"] for c in channels} >= {"general", "engineering", "random"}


def test_human_message_without_mention_does_not_summon_anyone(client, company):
    channel = client.get(f"/companies/{company['id']}/channels").json()[0]
    posted = client.post(f"/channels/{channel['id']}/messages", json={"body": "morning all"}).json()
    assert posted["replying"] is None

    messages = client.get(f"/channels/{channel['id']}/messages").json()
    assert messages[-1]["body"] == "morning all"
    assert messages[-1]["author_label"] == "You"


def test_toolbelt_limits_what_an_employee_can_call(client, company):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    manager = next(e for e in employees if e["role_key"] == "engineering_manager")
    engineer = next(e for e in employees if e["role_key"] == "backend_engineer")

    db = session()
    try:
        manager_row = db.get(Employee, manager["id"])
        engineer_row = db.get(Employee, engineer["id"])
        manager_tools = {tool.name for tool in tools.for_employee(manager_row)}
        engineer_tools = {tool.name for tool in tools.for_employee(engineer_row)}
    finally:
        db.close()

    assert "write_file" not in manager_tools  # managers do not implement
    assert "write_file" in engineer_tools
    assert "list_colleagues" in manager_tools  # the directory is available to everyone


def test_tools_write_through_to_the_database(client, company, project):
    db = session()
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        engineer = next(e for e in company_row.employees if e.role_key == "backend_engineer")
        ctx = ToolContext(db=db, company=company_row, employee=engineer, project=project_row)

        assert "Created" in str(tools.execute("create_ticket", ctx, {"title": "Wire up CI"}))
        assert "Posted to #general" in str(
            tools.execute("post_message", ctx, {"body": "Starting on CI", "channel": "general"})
        )
        assert "Created" in str(
            tools.execute("write_file", ctx, {"path": "ci.yml", "content": "steps: []\n"})
        )
        assert "Updated" in str(
            tools.execute("write_file", ctx, {"path": "ci.yml", "content": "steps: [build]\n"})
        )
        db.commit()
    finally:
        db.close()

    work_items = client.get(f"/projects/{project['id']}/work-items").json()
    assert any(t["title"] == "Wire up CI" for t in work_items)

    feed = client.get(f"/companies/{company['id']}/activity").json()["events"]
    assert any(event["kind"] == "code.write" for event in feed)
    assert any(event["kind"] == "chat.message" for event in feed)


def test_tool_access_is_denied_across_toolbelts(client, company, project):
    db = session()
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        manager = next(e for e in company_row.employees if e.role_key == "engineering_manager")
        ctx = ToolContext(db=db, company=company_row, employee=manager, project=project_row)
        result = tools.execute("write_file", ctx, {"path": "x.py", "content": "x"})
    finally:
        db.close()
    assert result.ok is False
    assert "do not have access" in result.text


@pytest.mark.parametrize("method", ["tools/list", "initialize"])
def test_mcp_needs_a_real_token_not_just_a_bearer_header(client, company, method):
    """The bridge used to accept any string. It resolves a real credential now."""
    call = {"jsonrpc": "2.0", "id": 1, "method": method}

    assert client.post("/mcp", json=call, headers=PROTOCOL).status_code == 401

    made_up = client.post(
        "/mcp", json=call, headers={**PROTOCOL, "Authorization": "Bearer test-token"}
    )
    assert made_up.status_code == 401

    _, token = mint_token(client, company)
    response = client.post(
        "/mcp", json=call, headers={**PROTOCOL, "Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert "result" in response.json()


def test_mcp_acts_as_the_token_holder_and_only_their_tools(client, company, project):
    """Identity comes from the credential, so there is no employee_id to spoof."""
    engineer, engineer_token = mint_token(client, company, "backend_engineer")
    manager, manager_token = mint_token(client, company, "engineering_manager")

    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={**PROTOCOL, "Authorization": f"Bearer {manager_token}"},
    ).json()
    manager_tools = {tool["name"] for tool in listed["result"]["tools"]}
    assert "write_file" not in manager_tools
    assert "create_ticket" in manager_tools

    written = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "write_file",
                "arguments": {
                    "path": "via_mcp.txt",
                    "content": "hello",
                    "project_id": project["id"],
                },
            },
        },
        headers={**PROTOCOL, "Authorization": f"Bearer {engineer_token}"},
    ).json()
    assert written["result"]["isError"] is False

    refused = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "write_file", "arguments": {"path": "x", "content": "y"}},
        },
        headers={**PROTOCOL, "Authorization": f"Bearer {manager_token}"},
    ).json()
    assert "error" in refused or refused["result"]["isError"] is True

    feed = client.get(f"/companies/{company['id']}/activity").json()["events"]
    assert any(
        event["kind"] == "code.write" and event["employee_id"] == engineer["id"]
        for event in feed
    )
    assert manager["id"] != engineer["id"]


def test_a_revoked_token_stops_working(client, company):
    employee, token = mint_token(client, company)
    header = {**PROTOCOL, "Authorization": f"Bearer {token}"}
    call = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert client.post("/mcp", json=call, headers=header).status_code == 200

    listed = client.get(f"/agents/{employee['id']}/tokens").json()
    client.delete(f"/agents/{employee['id']}/tokens/{listed[0]['id']}")

    assert client.post("/mcp", json=call, headers=header).status_code == 401


def test_prompt_tells_an_employee_what_they_cannot_reach(client, company):
    from agents.prompts import employee_system_prompt
    from db import session
    from models import Company

    db = session()
    try:
        company_row = db.get(Company, company["id"])
        manager = next(e for e in company_row.employees if e.role_key == "engineering_manager")
        prompt = employee_system_prompt(company_row, manager, list(company_row.employees), None)
    finally:
        db.close()

    assert "the work tracker" in prompt
    assert "You do NOT have: workspace" in prompt
    assert "cannot write code" in prompt
    assert company["name"] in prompt


def test_employees_are_told_not_to_split_their_own_ticket(client, company):
    from agents.prompts import employee_system_prompt
    from db import session
    from models import Company

    db = session()
    try:
        company_row = db.get(Company, company["id"])
        engineer = next(e for e in company_row.employees if e.role_key == "backend_engineer")
        prompt = employee_system_prompt(company_row, engineer, list(company_row.employees), None)
    finally:
        db.close()

    assert "never split" in prompt
    assert "already current" in prompt
    # Engineers are told which toolchains the sandbox actually has.
    assert "The workspace can run:" in prompt
    assert "flutter" in prompt


def test_edit_file_replaces_one_unique_snippet(client, company, project):
    from agents import tools
    from agents.tools.base import ToolContext
    from db import session
    from models import Company, Project

    client.put(
        f"/projects/{project['id']}/file",
        json={
            "path": "app.dart",
            "content": "import 'a.dart';\n\nvoid main() {}\nvoid other() {}\n",
        },
    )

    db = session()
    try:
        project_row = db.get(Project, project["id"])
        company_row = db.get(Company, company["id"])
        engineer = next(e for e in company_row.employees if e.role_key == "backend_engineer")
        ctx = ToolContext(db=db, company=company_row, employee=engineer, project=project_row)

        ok = tools.execute(
            "edit_file",
            ctx,
            {"path": "app.dart", "old_text": "import 'a.dart';", "new_text": "import 'b.dart';"},
        )
        missing = tools.execute(
            "edit_file", ctx, {"path": "app.dart", "old_text": "nope", "new_text": "x"}
        )
        ambiguous = tools.execute(
            "edit_file", ctx, {"path": "app.dart", "old_text": "void ", "new_text": "Future "}
        )
        db.commit()
    finally:
        db.close()

    assert "Edited app.dart" in ok.text
    assert missing.ok is False and "No match" in missing.text
    assert ambiguous.ok is False and "2 matches" in ambiguous.text

    content = client.get(f"/projects/{project['id']}/file", params={"path": "app.dart"}).json()
    assert content["content"].startswith("import 'b.dart';")
    assert "void main() {}" in content["content"]
