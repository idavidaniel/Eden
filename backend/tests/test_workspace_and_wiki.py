def test_workspace_write_read_and_commit(client, project):
    written = client.put(
        f"/projects/{project['id']}/file",
        json={
            "path": "src/app.py",
            "content": "print('hello')\n",
            "commit_message": "Add entry point",
        },
    ).json()
    assert written["created"] is True
    assert written["commit"]["committed"] is True

    content = client.get(f"/projects/{project['id']}/file", params={"path": "src/app.py"}).json()
    assert content["content"] == "print('hello')\n"

    commits = client.get(f"/projects/{project['id']}/commits").json()
    assert commits[0]["subject"] == "Add entry point"
    assert (
        "app.py"
        in client.get(f"/projects/{project['id']}/commits/{commits[0]['sha']}").json()["diff"]
    )


def test_workspace_rejects_path_traversal(client, project):
    response = client.put(
        f"/projects/{project['id']}/file", json={"path": "../../etc/passwd", "content": "nope"}
    )
    assert response.status_code == 400


def test_missing_file_is_404(client, project):
    assert (
        client.get(f"/projects/{project['id']}/file", params={"path": "nope.txt"}).status_code
        == 404
    )


def test_wiki_pages_are_versioned(client, company):
    page = client.post(
        f"/companies/{company['id']}/documents",
        json={"title": "Onboarding", "body": "Day one steps.", "space": "People"},
    ).json()
    assert page["version"] == 1
    assert page["slug"] == "onboarding"

    updated = client.patch(f"/documents/{page['id']}", json={"body": "Day one and two."}).json()
    assert updated["version"] == 2

    detail = client.get(f"/documents/{page['id']}").json()
    assert [v["version"] for v in detail["history"]] == [2, 1]

    index = client.get(f"/companies/{company['id']}/documents").json()
    assert index["spaces"] == ["People"]


def test_duplicate_wiki_title_is_rejected(client, company):
    client.post(f"/companies/{company['id']}/documents", json={"title": "Runbook", "body": "a"})
    duplicate = client.post(
        f"/companies/{company['id']}/documents", json={"title": "Runbook", "body": "b"}
    )
    assert duplicate.status_code == 409


def test_workspace_runs_allow_listed_commands(client, project):
    client.put(
        f"/projects/{project['id']}/file",
        json={"path": "hello.py", "content": "print('from the workspace')\n"},
    )

    from agents import tools
    from agents.tools.base import ToolContext
    from db import session
    from models import Company, Project

    db = session()
    try:
        project_row = db.get(Project, project["id"])
        company_row = db.get(Company, project_row.company_id)
        engineer = next(e for e in company_row.employees if e.role_key == "backend_engineer")
        ctx = ToolContext(db=db, company=company_row, employee=engineer, project=project_row)

        ok = tools.execute("run_command", ctx, {"command": "python3 hello.py"})
        blocked = tools.execute("run_command", ctx, {"command": "curl https://example.com"})
        piped = tools.execute("run_command", ctx, {"command": "cat hello.py | wc -l"})
        db.commit()
    finally:
        db.close()

    assert "from the workspace" in ok
    assert "succeeded" in ok
    assert "not allowed" in blocked
    assert "without a shell" in piped


def test_workspace_ignores_build_and_test_caches(client, project):
    from db import session
    from models import Project
    from services import workspace

    db = session()
    try:
        project_row = db.get(Project, project["id"])
        space = workspace.for_project(project_row.company.slug, project_row.key)
    finally:
        db.close()

    (space.root / ".pytest_cache").mkdir(exist_ok=True)
    (space.root / ".pytest_cache" / "junk.txt").write_text("noise")
    (space.root / "__pycache__").mkdir(exist_ok=True)
    (space.root / "__pycache__" / "mod.pyc").write_text("noise")

    paths = [entry["path"] for entry in space.tree()]
    assert ".gitignore" in paths
    assert not any(path.startswith((".pytest_cache", "__pycache__")) for path in paths)


def test_work_is_committed_for_the_employee(client, company, project):
    from agents.engine import _autocommit
    from db import session
    from models import Company, Project, Run, Ticket

    ticket = client.post(
        f"/projects/{project['id']}/tickets", json={"title": "Add a module"}
    ).json()
    client.put(f"/projects/{project['id']}/file", json={"path": "module.py", "content": "x = 1\n"})

    db = session()
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        ticket_row = db.get(Ticket, ticket["id"])
        engineer = next(e for e in company_row.employees if e.role_key == "backend_engineer")
        run = Run(company_id=company_row.id, project_id=project_row.id, status="running")
        db.add(run)
        db.flush()

        _autocommit(db, run, project_row, ticket_row, engineer, company_row)
        db.commit()
    finally:
        db.close()

    commits = client.get(f"/projects/{project['id']}/commits").json()
    assert commits[0]["subject"] == f"{ticket['key']}: Add a module"
    assert commits[0]["author"] == engineer.name
