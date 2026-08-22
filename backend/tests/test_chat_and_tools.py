import pytest

from agents import tools
from agents.tools.base import ToolContext
from db import session
from models import Company, Employee, Project

HEADERS = {"Mcp-Protocol-Version": "2026-07-28", "Authorization": "Bearer test-token"}


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

        assert "Created" in tools.execute("create_ticket", ctx, {"title": "Wire up CI"})
        assert "Posted to #general" in tools.execute(
            "post_message", ctx, {"body": "Starting on CI", "channel": "general"}
        )
        assert "Created" in tools.execute(
            "write_file", ctx, {"path": "ci.yml", "content": "steps: []\n"}
        )
        assert "Updated" in tools.execute(
            "write_file", ctx, {"path": "ci.yml", "content": "steps: [build]\n"}
        )
        db.commit()
    finally:
        db.close()

    tickets = client.get(f"/projects/{project['id']}/tickets").json()
    assert any(t["title"] == "Wire up CI" for t in tickets)

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
    assert "do not have access" in result


@pytest.mark.parametrize("method", ["tools/list", "initialize"])
def test_mcp_surface_is_protected_and_lists_platform_tools(client, method):
    unauthorised = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method},
        headers={"Mcp-Protocol-Version": "2026-07-28"},
    )
    assert unauthorised.status_code == 401

    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method}, headers=HEADERS
    ).json()
    assert "result" in response


def test_mcp_tools_require_an_employee_identity(client):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "post_message", "arguments": {"body": "hi"}},
        },
        headers=HEADERS,
    ).json()
    assert response["result"]["isError"] is True
    assert "employee_id" in response["result"]["content"][0]["text"]


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

    assert "the issue tracker" in prompt
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
    assert "do not re-fetch" in prompt
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

    assert "Edited app.dart" in ok
    assert "No match" in missing
    assert "2 matches" in ambiguous

    content = client.get(f"/projects/{project['id']}/file", params={"path": "app.dart"}).json()
    assert content["content"].startswith("import 'b.dart';")
    assert "void main() {}" in content["content"]
