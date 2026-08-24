"""A tool an agent wrote, and everything that stops it running on its own."""

import pytest

from db import session
from models import AuthoredTool, Company
from services import authored_tools


def _company(company_id):
    db = session()
    return db, db.get(Company, company_id)


VAT = {
    "name": "with_vat",
    "description": "Add VAT to a subtotal.",
    "rationale": "Every invoice needs it and I keep doing it by hand.",
    "parameters": {"subtotal": "number", "rate": "number"},
    "expression": "round(subtotal * (1 + rate), 2)",
    "examples": [
        {"given": {"subtotal": 100, "rate": 0.2}, "expect": 120.0},
        {"given": {"subtotal": 200, "rate": 0.05}, "expect": 210.0},
    ],
}


def _propose(db, company_row, **overrides):
    return authored_tools.propose(
        db,
        company=company_row,
        author=company_row.employees[0],
        **{**VAT, **overrides},
    )


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


def test_a_proposed_tool_cannot_be_called(client, company):
    """The whole point. Writing a tool is not permission to run it."""
    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        db.commit()
        assert row.status == "proposed"

        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            authored_tools.call(db, row, {"subtotal": 100, "rate": 0.2})
        assert "not approved" in str(caught.value)
    finally:
        db.close()


def test_a_proposed_tool_is_not_in_anyone_s_toolbelt(client, company):
    from agents import tools as registry

    db, company_row = _company(company["id"])
    try:
        _propose(db, company_row)
        db.commit()
        employee = company_row.employees[0]
        assert "with_vat" not in {tool.name for tool in registry.for_employee(employee)}
    finally:
        db.close()


def test_approving_it_puts_it_in_the_toolbelt(client, company):
    from agents import tools as registry

    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        authored_tools.review(db, row, approved=True, note="Fine.")
        db.commit()

        assert authored_tools.call(db, row, {"subtotal": 100, "rate": 0.2}) == 120.0
        employee = company_row.employees[0]
        names = {tool.name for tool in registry.for_employee(employee)}
        assert "with_vat" in names
    finally:
        db.close()


def test_a_rejected_tool_stays_unusable(client, company):
    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        authored_tools.review(db, row, approved=False, note="Rounding is wrong for us.")
        db.commit()

        assert row.status == "rejected"
        with pytest.raises(authored_tools.AuthoredToolError):
            authored_tools.call(db, row, {"subtotal": 100, "rate": 0.2})
    finally:
        db.close()


def test_retiring_an_approved_tool_takes_it_away_again(client, company):
    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        authored_tools.review(db, row, approved=True)
        db.commit()
        authored_tools.retire(db, row)
        db.commit()

        with pytest.raises(authored_tools.AuthoredToolError):
            authored_tools.call(db, row, {"subtotal": 100, "rate": 0.2})
        assert authored_tools.approved_for(db, company_row) == []
    finally:
        db.close()


# --------------------------------------------------------------------------
# what an expression is allowed to be
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "(1).__class__.__bases__",
        "[x for x in ().__class__.__mro__]",
        "globals()",
        "exec('x=1')",
    ],
)
def test_a_hostile_expression_is_refused(client, company, expression):
    db, company_row = _company(company["id"])
    try:
        with pytest.raises(authored_tools.AuthoredToolError):
            _propose(
                db,
                company_row,
                expression=expression,
                parameters={},
                examples=[{"given": {}, "expect": 1}, {"given": {}, "expect": 1}],
            )
    finally:
        db.close()


def test_a_tool_whose_own_examples_fail_never_reaches_a_person(client, company):
    """A person should never be asked to review something demonstrably broken."""
    db, company_row = _company(company["id"])
    try:
        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            _propose(
                db,
                company_row,
                examples=[
                    {"given": {"subtotal": 100, "rate": 0.2}, "expect": 999.0},
                    {"given": {"subtotal": 10, "rate": 0.1}, "expect": 11.0},
                ],
            )
        assert "does not do what its own examples say" in str(caught.value)
        assert (
            db.query(AuthoredTool).filter_by(company_id=company_row.id).count() == 0
        ), "a refused proposal must not be stored at all"
    finally:
        db.close()


def test_a_tool_needs_more_than_one_worked_example(client, company):
    db, company_row = _company(company["id"])
    try:
        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            _propose(db, company_row, examples=[VAT["examples"][0]])
        assert "at least 2 worked examples" in str(caught.value).lower()
    finally:
        db.close()


@pytest.mark.parametrize("name", ["Bad Name", "x", "with-dashes", "9lives", ""])
def test_a_bad_name_is_refused(client, company, name):
    db, company_row = _company(company["id"])
    try:
        with pytest.raises(authored_tools.AuthoredToolError):
            _propose(db, company_row, name=name)
    finally:
        db.close()


def test_an_unknown_parameter_type_is_refused(client, company):
    db, company_row = _company(company["id"])
    try:
        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            _propose(db, company_row, parameters={"subtotal": "money", "rate": "number"})
        assert "money" in str(caught.value)
    finally:
        db.close()


def test_calling_with_the_wrong_type_is_refused(client, company):
    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        authored_tools.review(db, row, approved=True)
        db.commit()

        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            authored_tools.call(db, row, {"subtotal": "one hundred", "rate": 0.2})
        assert "must be a number" in str(caught.value)

        with pytest.raises(authored_tools.AuthoredToolError):
            authored_tools.call(db, row, {"subtotal": 100})
    finally:
        db.close()


def test_a_tool_edited_to_break_its_examples_cannot_be_approved(client, company):
    """Approval re-runs the evidence rather than trusting the earlier run."""
    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        db.commit()

        row.expression = "round(subtotal * rate, 2)"  # quietly different
        db.add(row)
        db.commit()

        with pytest.raises(authored_tools.AuthoredToolError) as caught:
            authored_tools.review(db, row, approved=True)
        assert "no longer passes its own examples" in str(caught.value)
        db.refresh(row)
        assert row.status == "proposed"
    finally:
        db.close()


# --------------------------------------------------------------------------
# the record, and the API
# --------------------------------------------------------------------------


def test_a_review_goes_into_the_chain(client, company):
    from services import ledger

    db, company_row = _company(company["id"])
    try:
        row = _propose(db, company_row)
        authored_tools.review(db, row, approved=True, note="Useful.")
        db.commit()

        entries = [entry for entry in ledger.chain(db, company_row.id)]
        reviewed = [entry for entry in entries if entry.kind == "tool.reviewed"]
        assert reviewed, "approving executable code must be in the record"
        assert reviewed[-1].payload["expression"] == VAT["expression"]
        assert ledger.verify_chain(db, company_row.id)["intact"] is True
    finally:
        db.close()


def test_the_api_walks_the_whole_gate(client, company):
    employee = client.get(f"/companies/{company['id']}/employees").json()[0]

    created = client.post(
        f"/companies/{company['id']}/authored-tools",
        json={**VAT, "author_id": employee["id"]},
    )
    assert created.status_code == 201, created.text
    tool_id = created.json()["id"]
    assert created.json()["status"] == "proposed"

    listed = client.get(f"/companies/{company['id']}/authored-tools").json()
    assert listed["waiting"] == 1
    assert listed["usable_now"] == []

    refused = client.post(f"/authored-tools/{tool_id}/try", json={"subtotal": 100, "rate": 0.2})
    assert refused.status_code == 400
    assert "not approved" in refused.json()["detail"]

    approved = client.post(f"/authored-tools/{tool_id}/review", json={"approved": True})
    assert approved.json()["status"] == "approved"

    ran = client.post(f"/authored-tools/{tool_id}/try", json={"subtotal": 100, "rate": 0.2})
    assert ran.status_code == 200
    assert ran.json()["result"] == 120.0

    again = client.get(f"/companies/{company['id']}/authored-tools").json()
    assert again["waiting"] == 0
    assert again["usable_now"] == ["with_vat"]


def test_the_api_refuses_a_broken_proposal_with_a_usable_message(client, company):
    response = client.post(
        f"/companies/{company['id']}/authored-tools",
        json={**VAT, "examples": [{"given": {"subtotal": 1, "rate": 1}, "expect": 5}] * 2},
    )
    assert response.status_code == 400
    assert "expected 5" in response.json()["detail"]


def test_an_agent_proposing_one_is_told_it_cannot_use_it_yet(client, company):
    """The refusal has to be in the tool result, or the agent will just retry."""
    from agents.tools import execute
    from agents.tools.base import ToolContext

    db, company_row = _company(company["id"])
    try:
        ctx = ToolContext(db=db, company=company_row, employee=company_row.employees[0])
        result = execute("propose_tool", ctx, VAT)
        assert result.ok
        assert "cannot call it until" in result.text
        assert "carry on without it" in result.text
    finally:
        db.close()
