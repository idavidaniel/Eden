def test_project_creation_makes_a_key_and_a_workspace(client, project):
    assert project["key"] == "SENSOR"
    assert project["counts"]["total"] == 0

    files = client.get(f"/projects/{project['id']}/files").json()
    assert any(entry["path"] == "README.md" for entry in files["entries"])


def test_board_flow_create_move_and_comment(client, company, project):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    engineer = next(e for e in employees if e["role_key"] == "backend_engineer")

    ticket = client.post(
        f"/projects/{project['id']}/tickets",
        json={
            "title": "Expose /sensors endpoint",
            "description": "Return every sensor as JSON.",
            "assignee_id": engineer["id"],
            "acceptance_criteria": ["GET /sensors returns 200"],
        },
    ).json()
    assert ticket["key"] == "SENSOR-1"
    assert ticket["status"] == "backlog"

    moved = client.patch(f"/tickets/{ticket['id']}", json={"status": "in_progress"}).json()
    assert moved["status"] == "in_progress"

    client.post(f"/tickets/{ticket['id']}/comments", json={"body": "Prioritise this one."})
    detail = client.get(f"/tickets/{ticket['id']}").json()
    assert detail["comments"][0]["body"] == "Prioritise this one."
    assert detail["acceptance_criteria"] == ["GET /sensors returns 200"]


def test_invalid_status_is_rejected(client, project):
    ticket = client.post(f"/projects/{project['id']}/tickets", json={"title": "x"}).json()
    response = client.patch(f"/tickets/{ticket['id']}", json={"status": "shipped"})
    assert response.status_code == 400


def test_ticket_counts_group_by_status(client, project):
    for index in range(3):
        client.post(f"/projects/{project['id']}/tickets", json={"title": f"T{index}"})
    tickets = client.get(f"/projects/{project['id']}/tickets").json()
    client.patch(f"/tickets/{tickets[0]['id']}", json={"status": "done"})

    counts = client.get(f"/projects/{project['id']}").json()["counts"]
    assert counts["total"] == 3
    assert counts["done"] == 1
    assert counts["backlog"] == 2


def test_run_requires_employees(client):
    empty = client.post("/companies", json={"name": "Solo Studio", "starting_team": []}).json()
    project = client.post(
        f"/companies/{empty['id']}/projects", json={"name": "Idea", "brief": "Do something"}
    ).json()
    response = client.post(f"/projects/{project['id']}/runs", json={})
    assert response.status_code == 400
    assert "employee" in response.json()["detail"]


def test_pending_tickets_are_ordered_and_filtered(client, company):
    project = client.post(
        f"/companies/{company['id']}/projects", json={"name": "Ordering", "brief": "b"}
    ).json()
    first = client.post(
        f"/projects/{project['id']}/tickets", json={"title": "one", "status": "todo"}
    ).json()
    client.post(f"/projects/{project['id']}/tickets", json={"title": "two", "status": "done"})
    stalled = client.post(
        f"/projects/{project['id']}/tickets", json={"title": "stalled", "status": "in_progress"}
    ).json()
    third = client.post(
        f"/projects/{project['id']}/tickets", json={"title": "three", "status": "backlog"}
    ).json()

    from agents.engine import _pending_tickets
    from db import session

    db = session()
    try:
        pending = _pending_tickets(db, project["id"])
    finally:
        db.close()

    # `in_progress` is included: an interrupted run leaves work mid-flight.
    assert [t.id for t in pending] == [first["id"], stalled["id"], third["id"]]


def test_restart_releases_runs_that_were_in_flight(client, company):
    from db import session
    from main import _release_orphaned_runs
    from models import Employee, Run

    project = client.post(
        f"/companies/{company['id']}/projects", json={"name": "Orphan", "brief": "b"}
    ).json()

    db = session()
    try:
        db.add(Run(company_id=company["id"], project_id=project["id"], status="running"))
        employee = db.query(Employee).filter_by(company_id=company["id"]).first()
        employee.status = "working"
        db.add(employee)
        db.commit()
    finally:
        db.close()

    _release_orphaned_runs()

    db = session()
    try:
        run = db.query(Run).filter_by(project_id=project["id"]).one()
        assert run.status == "interrupted"
        assert "restarted" in run.error
        assert not db.query(Employee).filter_by(company_id=company["id"], status="working").count()
    finally:
        db.close()


def test_outcome_note_explains_how_a_run_ended():
    from types import SimpleNamespace

    from agents.engine import _outcome_note

    open_tickets = [SimpleNamespace(key="ABC-2"), SimpleNamespace(key="ABC-3")]
    note = _outcome_note(1, open_tickets, [SimpleNamespace(key="ABC-4")], 2)

    assert "1 ticket finished" in note
    assert "2 still open (ABC-2, ABC-3)" in note
    assert "run again" in note
    assert "1 blocked" in note
    assert "2 turns ran out of tool calls" in note


def test_outcome_note_is_quiet_when_everything_landed():
    from agents.engine import _outcome_note

    assert _outcome_note(4, [], [], 0) == "4 tickets finished."


def test_tickets_can_be_deleted(client, project):
    ticket = client.post(f"/projects/{project['id']}/tickets", json={"title": "Junk"}).json()

    assert client.delete(f"/tickets/{ticket['id']}").status_code == 204
    assert client.get(f"/tickets/{ticket['id']}").status_code == 404
    assert ticket["key"] not in [
        t["key"] for t in client.get(f"/projects/{project['id']}/tickets").json()
    ]


def test_verify_command_must_pass_the_sandbox_rules(client, project):
    rejected = client.patch(
        f"/projects/{project['id']}", json={"verify_command": "curl http://example.com"}
    )
    assert rejected.status_code == 400
    assert "not allowed" in rejected.json()["detail"]

    piped = client.patch(f"/projects/{project['id']}", json={"verify_command": "pytest | tee out"})
    assert piped.status_code == 400

    accepted = client.patch(f"/projects/{project['id']}", json={"verify_command": "pytest -q"})
    assert accepted.status_code == 200
    assert accepted.json()["verify_command"] == "pytest -q"


def test_failing_verification_reopens_a_ticket(client, company, project):
    """The platform's own check overrides what the employee claims."""
    from agents.engine import verify_project
    from db import session
    from models import Company, Project, Run, Ticket

    client.patch(f"/projects/{project['id']}", json={"verify_command": "python3 fails.py"})
    client.put(
        f"/projects/{project['id']}/file",
        json={"path": "fails.py", "content": "raise SystemExit(3)\n"},
    )
    ticket = client.post(
        f"/projects/{project['id']}/tickets", json={"title": "Claims to work", "status": "done"}
    ).json()

    db = session()
    try:
        project_row = db.get(Project, project["id"])
        company_row = db.get(Company, company["id"])
        ticket_row = db.get(Ticket, ticket["id"])
        run = Run(company_id=company_row.id, project_id=project_row.id, status="running")
        db.add(run)
        db.flush()
        verdict = verify_project(db, run, project_row, ticket_row, company_row)
        db.commit()
    finally:
        db.close()

    assert verdict["exit_code"] == 3
    detail = client.get(f"/tickets/{ticket['id']}").json()
    verification = [c for c in detail["comments"] if c["author_label"] == "Verification"]
    assert verification and "FAILED (exit 3)" in verification[0]["body"]


def test_passing_verification_is_recorded(client, company, project):
    from agents.engine import verify_project
    from db import session
    from models import Company, Project, Run, Ticket

    client.patch(f"/projects/{project['id']}", json={"verify_command": "python3 ok.py"})
    client.put(
        f"/projects/{project['id']}/file", json={"path": "ok.py", "content": "print('ok')\n"}
    )
    ticket = client.post(f"/projects/{project['id']}/tickets", json={"title": "Real work"}).json()

    db = session()
    try:
        run = Run(company_id=company["id"], project_id=project["id"], status="running")
        db.add(run)
        db.flush()
        verdict = verify_project(
            db,
            run,
            db.get(Project, project["id"]),
            db.get(Ticket, ticket["id"]),
            db.get(Company, company["id"]),
        )
        db.commit()
    finally:
        db.close()

    assert verdict["exit_code"] == 0
    detail = client.get(f"/tickets/{ticket['id']}").json()
    assert any("passed" in c["body"] for c in detail["comments"])
