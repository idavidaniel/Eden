"""The company keeps working without anyone starting a run.

The clock, the leases that stop two workers taking the same task, the protocol
agents use to talk to each other, and the two switches that stop all of it.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from db import session
from models import AgentMessage, AgentTask, Approval, Company, Project, WorkItem
from services import clock, inbox


@pytest.fixture(autouse=True)
def empty_queue():
    """The clock is global, so leftover tasks from another test would be leased.

    The suite shares one database, and `lease_next` deliberately does not filter
    by company — a worker takes whatever is next. Start each test from nothing.
    """
    db = session()
    try:
        db.query(AgentTask).delete()
        db.commit()
    finally:
        db.close()
    yield


def _context(company_id, project_id=None):
    db = session()
    project = db.get(Project, project_id) if project_id else None
    return db, db.get(Company, company_id), project


def _tasks_for(db, company_id) -> list[AgentTask]:
    """Only this company's queue. Other tests leave autonomous companies behind,
    and `schedule_ready_work` deliberately looks at all of them."""
    return list(db.scalars(select(AgentTask).where(AgentTask.company_id == company_id)))


def _queue(db, company_row, employee, **kwargs):
    from agents import worker

    return worker.enqueue(
        db,
        company=company_row,
        employee=employee,
        kind=kwargs.pop("kind", "message"),
        request=kwargs.pop("request", {"message": "Do a thing."}),
        source="test",
        created_by="Test",
        **kwargs,
    )


# --------------------------------------------------------------------------
# leasing
# --------------------------------------------------------------------------


def test_a_leased_task_is_not_offered_twice(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        _queue(db, company_row, company_row.employees[0])
        db.commit()

        first = clock.lease_next(db, 10)
        assert len(first) == 1
        assert first[0].status == "leased"
        assert first[0].lease_until is not None

        assert clock.lease_next(db, 10) == [], "a leased task must not be leased again"
    finally:
        db.close()


def test_an_employee_only_holds_one_turn_at_a_time(client, company):
    """They have one workspace and one identity; two turns would trample."""
    db, company_row, _ = _context(company["id"])
    try:
        person = company_row.employees[0]
        _queue(db, company_row, person)
        _queue(db, company_row, person)
        db.commit()

        assert len(clock.lease_next(db, 10)) == 1
        assert len(clock.lease_next(db, 10)) == 0
    finally:
        db.close()


def test_work_for_different_people_runs_side_by_side(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        for person in company_row.employees[:3]:
            _queue(db, company_row, person)
        db.commit()
        assert len(clock.lease_next(db, 10)) == 3
    finally:
        db.close()


def test_a_task_scheduled_for_later_waits(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        task = _queue(db, company_row, company_row.employees[0])
        task.scheduled_for = datetime.now(UTC) + timedelta(hours=1)
        db.add(task)
        db.commit()
        assert clock.lease_next(db, 10) == []

        task.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
        db.add(task)
        db.commit()
        assert len(clock.lease_next(db, 10)) == 1
    finally:
        db.close()


def test_a_worker_that_dies_mid_turn_has_its_work_taken_back(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        person = company_row.employees[0]
        task = _queue(db, company_row, person)
        db.commit()
        clock.lease_next(db, 1)

        task.lease_until = datetime.now(UTC) - timedelta(minutes=1)
        person.status = "working"
        db.add_all([task, person])
        db.commit()

        assert clock.reclaim_expired(db) == 1
        db.refresh(task)
        db.refresh(person)
        assert task.status == "queued"
        assert task.attempts <= 3
        assert person.status == "idle", "the employee should not be left looking busy"
    finally:
        db.close()


def test_a_task_that_never_finishes_is_given_up_on_rather_than_looping(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        task = _queue(db, company_row, company_row.employees[0])
        task.status = "running"
        task.attempts = 3
        task.lease_until = datetime.now(UTC) - timedelta(minutes=1)
        db.add(task)
        db.commit()

        clock.reclaim_expired(db)
        db.refresh(task)
        assert task.status == "failed"
        assert "three attempts" in task.error
    finally:
        db.close()


# --------------------------------------------------------------------------
# scheduling
# --------------------------------------------------------------------------


def test_the_clock_does_nothing_to_a_company_that_did_not_ask(client, company, project):
    """Autonomy spends money, so it is off until you switch it on."""
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item = WorkItem(
            project_id=project_row.id,
            key="SENSOR-100",
            title="Something to do",
            status="todo",
            assignee_id=company_row.employees[0].id,
        )
        db.add(item)
        project_row.status = "in_progress"
        db.commit()

        clock.schedule_ready_work(db)
        assert _tasks_for(db, company_row.id) == []
    finally:
        db.close()


def test_switching_autonomy_on_makes_the_clock_pick_work_up(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item = WorkItem(
            project_id=project_row.id,
            key="SENSOR-101",
            title="Something to do",
            status="todo",
            assignee_id=company_row.employees[0].id,
        )
        db.add(item)
        project_row.status = "in_progress"
        company_row.settings = {"autonomous": True}
        db.commit()

        clock.schedule_ready_work(db)
        assert len(_tasks_for(db, company_row.id)) == 1
        queued = db.scalar(
            select(AgentTask).where(AgentTask.work_item_id == item.id)
        )
        assert queued.kind == "work_item"
        assert queued.source == "clock"

        # And it does not queue the same item twice on the next pass.
        clock.schedule_ready_work(db)
        assert len(_tasks_for(db, company_row.id)) == 1
    finally:
        db.close()


def test_an_unread_message_is_enough_to_wake_somebody_up(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        sender, recipient = company_row.employees[0], company_row.employees[1]
        company_row.settings = {"autonomous": True}
        inbox.send(
            db,
            company=company_row,
            sender=sender,
            recipient=recipient,
            kind="request",
            subject="Can you look at the ingest?",
            body="It has been failing since Tuesday.",
        )
        db.commit()

        created = clock.schedule_ready_work(db)
        assert created >= 1
        task = db.scalar(
            select(AgentTask).where(
                AgentTask.employee_id == recipient.id, AgentTask.kind == "inbox"
            )
        )
        assert task is not None
    finally:
        db.close()


def test_halting_a_company_stops_the_clock_from_touching_it(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        company_row.settings = {"autonomous": True}
        company_row.halted = True
        company_row.halt_reason = "I want to read what it did first."
        project_row.status = "in_progress"
        db.add(
            WorkItem(
                project_id=project_row.id,
                key="SENSOR-102",
                title="Something to do",
                status="todo",
                assignee_id=company_row.employees[0].id,
            )
        )
        db.commit()

        clock.schedule_ready_work(db)
        assert _tasks_for(db, company_row.id) == []

        # A task queued before the halt is not leased once the halt is on.
        company_row.halted = False
        db.commit()
        clock.schedule_ready_work(db)
        assert _tasks_for(db, company_row.id), "the setup should have queued something"
        company_row.halted = True
        db.commit()

        leased = clock.lease_next(db, 20)
        assert [task for task in leased if task.company_id == company_row.id] == []
    finally:
        db.close()


def test_the_halt_switch_refuses_an_agent_turn_outright(client, company, scripted_model):
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]
    client.post(
        f"/companies/{company['id']}/halt",
        json={"halted": True, "reason": "Reading the ledger."},
    )

    scripted_model.queue.append("Should never be reached.")
    body = client.post(
        f"/agents/{employee['id']}/messages", json={"message": "Carry on"}
    ).json()

    assert body["status"] == "refused"
    assert "halted" in body["reply"]
    assert "Reading the ledger" in body["reply"]
    assert scripted_model.queue == ["Should never be reached."]


def test_a_tick_can_be_driven_by_hand(client, company):
    body = client.post("/clock/tick").json()
    assert set(body) == {"reclaimed", "created", "dispatched"}


# --------------------------------------------------------------------------
# the protocol between agents
# --------------------------------------------------------------------------


def test_a_message_lands_in_a_thread_and_shows_up_unread(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        sender, recipient = company_row.employees[0], company_row.employees[1]
        message = inbox.send(
            db,
            company=company_row,
            sender=sender,
            recipient=recipient,
            kind="request",
            subject="Review needed",
            body="Have a look at SENSOR-3.",
        )
        db.commit()

        assert message.thread_id
        assert [row.id for row in inbox.unread(db, recipient.id)] == [message.id]
        assert inbox.unread(db, sender.id) == [], "a sender does not message themselves"

        inbox.mark_handled(db, [message])
        db.commit()
        assert inbox.unread(db, recipient.id) == []
    finally:
        db.close()


def test_a_thread_that_goes_round_in_circles_is_escalated(client, company):
    """Two agents politely handing work back and forth is a failure mode."""
    db, company_row, _ = _context(company["id"])
    try:
        junior = next(
            person for person in company_row.employees if person.role_key != "engineering_manager"
        )
        manager = next(
            person for person in company_row.employees if person.role_key == "engineering_manager"
        )
        junior.manager_id = manager.id
        db.add(junior)
        db.flush()

        who = inbox.escalate(
            db,
            company=company_row,
            from_employee=junior,
            work_item=None,
            thread_id="thread-1",
            reason="This has been passed back and forth four times.",
        )
        db.commit()

        assert who == manager.name
        escalated = db.scalar(
            select(AgentMessage).where(
                AgentMessage.to_id == manager.id, AgentMessage.kind == "escalate"
            )
        )
        assert escalated is not None
        assert escalated.hops == inbox.MAX_HOPS, "an escalation cannot be passed on again"
    finally:
        db.close()


def test_with_nobody_to_escalate_to_it_asks_you(client):
    created = client.post("/companies", json={"name": "Solo Shop", "pack": "blank"}).json()
    db, company_row, _ = _context(created["id"])
    try:
        only = company_row.employees[0]
        only.manager_id = None
        db.add(only)
        db.flush()

        who = inbox.escalate(
            db,
            company=company_row,
            from_employee=only,
            work_item=None,
            thread_id="thread-2",
            reason="Nobody here can decide this.",
        )
        db.commit()
        assert who == "you"
        assert inbox.pending_approvals(db, company_row.id)
    finally:
        db.close()


def test_asking_you_a_question_blocks_the_work_until_you_answer(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item = WorkItem(
            project_id=project_row.id,
            key="SENSOR-103",
            title="Rename the customer field",
            status="in_progress",
            assignee_id=company_row.employees[0].id,
        )
        db.add(item)
        db.flush()

        approval = inbox.ask_human(
            db,
            company=company_row,
            employee=company_row.employees[0],
            work_item=item,
            question="Does 'customer' mean the buyer or the account?",
            reason="Both readings are defensible and they produce different schemas.",
        )
        db.commit()

        assert item.status == "blocked"
        assert "Waiting on you" in item.blocked_reason
        approval_id = approval.id
    finally:
        db.close()

    listed = client.get(f"/companies/{company['id']}/inbox").json()
    assert approval_id in {row["id"] for row in listed["approvals"]}

    decided = client.post(
        f"/approvals/{approval_id}/decide",
        json={"approved": True, "note": "The buyer."},
    ).json()
    assert decided["status"] == "approved"

    db, _, _ = _context(company["id"])
    try:
        item = db.scalar(select(WorkItem).where(WorkItem.key == "SENSOR-103"))
        assert item.status == "todo", "answering the question should unblock the work"
        assert item.blocked_reason is None
    finally:
        db.close()


def test_a_decision_is_written_into_the_chain(client, company):
    from services import ledger

    db, company_row, _ = _context(company["id"])
    try:
        approval = Approval(
            company_id=company_row.id,
            subject_kind="question",
            requested_label="Ada Kern (Backend Engineer)",
            title="Ship on Friday?",
        )
        db.add(approval)
        db.flush()
        inbox.decide(db, approval, approved=False, by="You", note="Monday.")
        db.commit()

        kinds = [entry.kind for entry in ledger.chain(db, company_row.id)]
        assert "approval.decided" in kinds
        assert ledger.verify_chain(db, company_row.id)["intact"] is True
    finally:
        db.close()


def test_the_ops_page_says_what_the_company_is_doing(client, company):
    body = client.get(f"/companies/{company['id']}/ops").json()
    assert "clock" in body
    assert "halted" in body
    assert "autonomous" in body
