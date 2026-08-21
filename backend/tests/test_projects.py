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
