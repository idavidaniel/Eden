"""The loop that turns a brief into a deliverable, and the ways it quietly did not.

A real run planned six items, made twenty-eight tool calls, produced nothing,
and reported itself completed. Every test here comes from one step of working
out why.
"""


from db import session
from models import Company, Project, Run, WorkItem
from services import web as web_service


def _context(company_id, project_id=None):
    db = session()
    project = db.get(Project, project_id) if project_id else None
    return db, db.get(Company, company_id), project


# --------------------------------------------------------------------------
# search and fetch have to agree with each other
# --------------------------------------------------------------------------


def test_search_says_which_results_can_actually_be_opened(client, company, monkeypatch):
    """Egress is default-deny, so most search results are unreachable.

    Handing an agent ten links it will be refused ten times is how a turn burns
    every step on nothing — which is exactly what happened.
    """
    from agents.tools import research
    from agents.tools.base import ToolContext

    db, company_row, _ = _context(company["id"])
    try:
        company_row.settings = {"egress_allow": ["docs.python.org"]}
        db.add(company_row)
        db.commit()

        monkeypatch.setattr(
            web_service,
            "search",
            lambda *_args, **_kwargs: [
                {"url": "https://docs.python.org/3/x", "title": "Allowed", "snippet": "a"},
                {"url": "https://zenfolio.com/y", "title": "Refused", "snippet": "b"},
            ],
        )
        ctx = ToolContext(db=db, company=company_row, employee=company_row.employees[0])
        result = research.search_web(ctx, "photo studio pricing")

        assert "1 of 2 can be opened" in result.text
        assert "cannot be opened" in result.text
        # And the marker is on the right one.
        allowed_line, refused_line = result.text.split("2. ")
        assert "cannot be opened" not in allowed_line.split("1. ")[1]
        assert "cannot be opened" in refused_line
    finally:
        db.close()


def test_search_says_so_plainly_when_nothing_can_be_opened(client, company, monkeypatch):
    from agents.tools import research
    from agents.tools.base import ToolContext

    db, company_row, _ = _context(company["id"])
    try:
        monkeypatch.setattr(
            web_service,
            "search",
            lambda *_args, **_kwargs: [
                {"url": "https://zenfolio.com/a", "title": "One", "snippet": "a"},
                {"url": "https://example.com/b", "title": "Two", "snippet": "b"},
            ],
        )
        ctx = ToolContext(db=db, company=company_row, employee=company_row.employees[0])
        result = research.search_web(ctx, "anything")

        assert "None of these can be opened" in result.text
        assert "do not try to fetch them" in result.text
        # It has to say what to do instead, or the agent just stops.
        assert "Work from the titles and snippets" in result.text
        assert result.meta["fetchable"] == 0
    finally:
        db.close()


def test_fetching_stops_asking_after_a_few_refusals(client, company, monkeypatch):
    """Twenty-three refusals in one turn is not persistence, it is a loop."""
    from agents.tools import research
    from agents.tools.base import ToolContext

    db, company_row, _ = _context(company["id"])
    try:
        ctx = ToolContext(db=db, company=company_row, employee=company_row.employees[0])

        for attempt in range(1, research.GIVE_UP_AFTER_REFUSALS):
            result = research.fetch_url(ctx, f"https://blocked-{attempt}.example/")
            assert result.ok is False
            assert "effectively closed" not in result.text

        final = research.fetch_url(ctx, "https://blocked-last.example/")
        assert final.ok is False
        assert "effectively closed" in final.text
        # And it says what to do instead of failing the work item.
        assert "Produce the deliverable" in final.error_hint
        assert "which claims you could not source" in final.error_hint
    finally:
        db.close()


def test_a_reachable_host_is_still_reachable(client, company):
    """The give-up rule must not become "never fetch anything"."""
    db, company_row, _ = _context(company["id"])
    try:
        company_row.settings = {"egress_allow": ["docs.python.org"]}
        allowed, _ = web_service.host_allowed(company_row, "https://docs.python.org/3/")
        assert allowed is True
    finally:
        db.close()


# --------------------------------------------------------------------------
# a run that finished nothing is not a completed run
# --------------------------------------------------------------------------


def test_a_run_that_finished_nothing_is_stalled_not_completed(client, company, project):
    """The product's own failure mode, committed by the product."""
    from agents import engine

    db, _, project_row = _context(company["id"], project["id"])
    try:
        for index in range(3):
            db.add(
                WorkItem(
                    project_id=project_row.id,
                    key=f"X-{index}",
                    title="Something nobody did",
                    status="todo",
                )
            )
        db.commit()

        assert engine._closing_status(db, project_row) == "stalled"
    finally:
        db.close()


def test_a_run_that_finished_something_is_completed(client, company, project):
    from agents import engine

    db, _, project_row = _context(company["id"], project["id"])
    try:
        db.add(WorkItem(project_id=project_row.id, key="Y-1", title="Done", status="done"))
        db.add(WorkItem(project_id=project_row.id, key="Y-2", title="Not", status="todo"))
        db.commit()

        assert engine._closing_status(db, project_row) == "completed"
    finally:
        db.close()


def test_a_run_with_no_items_at_all_is_stalled(client, company, project):
    from agents import engine

    db, _, project_row = _context(company["id"], project["id"])
    try:
        assert engine._closing_status(db, project_row) == "stalled"
    finally:
        db.close()


def test_the_run_status_reaches_the_api(client, company, project):
    """A green tick over an empty project is the thing to avoid."""
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        run = Run(
            company_id=company_row.id,
            project_id=project_row.id,
            status="stalled",
            phase="done",
            brief="b",
            stats={"items": 3, "done": 0},
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    body = client.get(f"/runs/{run_id}").json()
    assert body["status"] == "stalled"
    assert body["stats"]["done"] == 0


# --------------------------------------------------------------------------
# the audit trail the ops page reads
# --------------------------------------------------------------------------


def test_a_refused_tool_call_is_reported_as_refused_not_as_broken(client, company):
    """One is the platform working; the other is something to fix."""
    from datetime import UTC, datetime

    from models import ToolCall

    db, company_row, _ = _context(company["id"])
    try:
        person = company_row.employees[0]
        db.add(
            ToolCall(
                created_at=datetime.now(UTC),
                company_id=company_row.id,
                employee_id=person.id,
                tool="fetch_url",
                arguments={"url": "https://zenfolio.com/x"},
                ok=False,
                error="zenfolio.com is not on this company's allow-list.",
                result_preview="refused",
                duration_ms=3,
            )
        )
        db.add(
            ToolCall(
                created_at=datetime.now(UTC),
                company_id=company_row.id,
                employee_id=person.id,
                tool="write_deliverable",
                arguments={},
                ok=False,
                error="Disk was full.",
                result_preview="broke",
                duration_ms=3,
            )
        )
        db.commit()
        name = person.name
    finally:
        db.close()

    rows = client.get(f"/companies/{company['id']}/tool-calls").json()
    by_tool = {row["tool"]: row for row in rows}

    refused = by_tool["fetch_url"]
    assert refused["blocked_reason"], "a policy refusal should read as refused"
    assert refused["group"] == "research"
    assert refused["employee_label"] == name

    broken = by_tool["write_deliverable"]
    assert broken["blocked_reason"] is None, "a genuine failure is not a refusal"
    assert broken["group"] == "documents"
