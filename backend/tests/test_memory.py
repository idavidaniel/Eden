"""What an employee remembers, and what it is not allowed to remember."""

from db import session
from models import Company
from services import memory


def _employee(company: dict, role_key: str = "backend_engineer"):
    db = session()
    company_row = db.get(Company, company["id"])
    return db, company_row, next(e for e in company_row.employees if e.role_key == role_key)


def test_core_blocks_are_created_once_and_are_editable(client, company):
    db, _, employee = _employee(company)
    try:
        first = memory.blocks_for(db, employee)
        db.commit()
        again = memory.blocks_for(db, employee)
        assert [block.label for block in first] == ["persona", "company", "focus", "human"]
        assert {block.id for block in first} == {block.id for block in again}

        memory.set_block(db, employee, "focus", "Wiring up the sensor API.", updated_by="You")
        db.commit()
        assert "sensor API" in memory.blocks_text(db, employee)
    finally:
        db.close()


def test_a_block_respects_its_character_limit(client, company):
    db, _, employee = _employee(company)
    try:
        block = memory.set_block(db, employee, "human", "x" * 5000, updated_by="You")
        db.commit()
        assert len(block.content) == block.char_limit
    finally:
        db.close()


def test_a_pinned_block_is_yours_alone(client, company):
    db, _, employee = _employee(company)
    try:
        block = memory.set_block(db, employee, "persona", "Written by you.", updated_by="You")
        block.pinned = True
        db.add(block)
        db.commit()

        try:
            memory.set_block(db, employee, "persona", "Rewritten by me.", updated_by=employee.name)
            raise AssertionError("the agent should not have been able to rewrite a pinned block")
        except PermissionError as exc:
            assert "pinned" in str(exc)
    finally:
        db.close()


def test_saying_the_same_thing_twice_merges_rather_than_duplicates(
    client, company, fake_embeddings
):
    db, company_row, employee = _employee(company)
    try:
        first, what = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="The sensor API paginates with a cursor, not an offset",
        )
        assert what == "created"

        second, what = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="The sensor API paginates with a cursor, not an offset",
            body="Confirmed again.",
        )
        db.commit()

        assert what == "merged"
        assert second.id == first.id
        assert second.uses == 1
    finally:
        db.close()


def test_a_contradiction_supersedes_rather_than_overwrites(client, company, no_embeddings):
    """What an agent used to believe is evidence, so it is kept and marked."""
    db, company_row, employee = _employee(company)
    try:
        old, _ = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="Deploys go out on Friday afternoon",
            body="Release window Friday deploy schedule afternoon",
        )
        new, what = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="Deploys go out on Tuesday afternoon",
            body="Release window Tuesday deploy schedule afternoon",
        )
        db.commit()

        assert what == "superseded"
        db.refresh(old)
        assert old.superseded_by == new.id
        assert old.archived_at is None  # kept, not deleted
    finally:
        db.close()


def test_search_ranks_failures_above_successes(client, company, no_embeddings):
    """A rejection teaches more than a success, and the ranking says so."""
    db, company_row, employee = _employee(company)
    try:
        for outcome, title in [
            ("shipped", "Cursor pagination worked on the sensors endpoint"),
            ("rejected", "Cursor pagination failed on the sensors endpoint"),
        ]:
            memory.remember(
                db,
                company_id=company_row.id,
                employee_id=employee.id,
                kind="episode",
                title=title,
                outcome=outcome,
                confidence=0.8,
            )
        db.commit()

        hits, mode = memory.search(
            db, company_row.id, "cursor pagination sensors endpoint", employee_id=employee.id
        )
        assert mode == "lexical"
        assert hits[0].memory.outcome == "rejected"
    finally:
        db.close()


def test_search_says_which_mode_it_used(client, company, fake_embeddings):
    db, company_row, employee = _employee(company)
    try:
        memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="Postgres is behind pgbouncer in this deployment",
        )
        db.commit()
        _, mode = memory.search(
            db, company_row.id, "database connection pooling", employee_id=employee.id
        )
        assert mode == "vector"
    finally:
        db.close()


def test_promotion_needs_corroboration_from_more_than_one_agent(client, company, no_embeddings):
    db, company_row, employee = _employee(company)
    try:
        colleague = next(
            person for person in company_row.employees if person.id != employee.id
        )
        row, _ = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="The client signs off on Thursdays",
        )
        db.commit()

        memory.note_use(db, [row], employee.id)
        memory.note_use(db, [row], employee.id)
        db.commit()
        assert memory.promotable(db, company_row.id) == []  # three uses, one agent

        memory.note_use(db, [row], colleague.id)
        db.commit()
        assert [item.id for item in memory.promotable(db, company_row.id)] == [row.id]

        memory.promote(db, row)
        db.commit()
        assert row.scope == "company"
        assert row.employee_id is None
    finally:
        db.close()


def test_unused_low_confidence_memories_are_archived_not_deleted(client, company, no_embeddings):
    from datetime import UTC, datetime, timedelta

    db, company_row, employee = _employee(company)
    try:
        row, _ = memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="A guess nobody ever used",
            confidence=0.3,
        )
        row.decay_at = datetime.now(UTC) - timedelta(days=1)
        db.add(row)
        db.commit()

        assert memory.archive_stale(db, company_row.id) == 1
        db.commit()
        db.refresh(row)
        assert row.archived_at is not None

        hits, _ = memory.search(db, company_row.id, "guess", employee_id=employee.id)
        assert row.id not in {hit.memory.id for hit in hits}
    finally:
        db.close()


def test_the_memory_api_shows_what_would_be_retrieved(client, company, no_embeddings):
    employees = client.get(f"/companies/{company['id']}/employees").json()
    employee = employees[0]

    client.post(
        f"/agents/{employee['id']}/memory",
        json={"title": "Northwind bills monthly, in arrears", "kind": "fact"},
    )
    everything = client.get(f"/agents/{employee['id']}/memory").json()
    assert [block["label"] for block in everything["blocks"]] == [
        "persona",
        "company",
        "focus",
        "human",
    ]
    assert any("Northwind bills" in row["title"] for row in everything["memories"])

    searched = client.get(
        f"/agents/{employee['id']}/memory", params={"query": "when does Northwind get billed"}
    ).json()
    assert searched["retrieval_mode"] in {"lexical", "vector"}
    assert searched["memories"], "the query should retrieve the fact that was taught"
    assert searched["memories"][0]["score"] is not None


def test_the_api_refuses_to_write_a_procedure_directly(client, company):
    """The learning gate has no back door through HTTP."""
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]
    response = client.post(
        f"/agents/{employee['id']}/memory",
        json={"title": "How to ship", "kind": "procedure"},
    )
    assert response.status_code == 400
    assert "checks passed" in response.json()["detail"]
