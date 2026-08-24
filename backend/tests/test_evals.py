"""The harness that checks whether any of this is actually earning its place."""

import pytest

from db import session
from models import Company
from services import evals


def test_every_shipped_suite_loads(client):
    """A suite with a typo measures nothing, silently."""
    suites = evals.all_suites()
    assert set(suites) >= {"software_studio", "law_firm"}
    for key, suite in suites.items():
        assert suite.briefs, f"{key} has no briefs"
        for brief in suite.briefs:
            assert brief.brief.strip(), f"{key}:{brief.key} has an empty brief"
            for check in brief.checks:
                assert check["kind"] in {
                    "command",
                    "schema",
                    "assertion",
                    "citation",
                    "rubric",
                    "human",
                }, f"{key}:{brief.key} has an unknown check kind"


def test_an_unknown_suite_is_refused_by_name(client):
    with pytest.raises(evals.EvalError) as caught:
        evals.get_suite("telepathy")
    assert "telepathy" in str(caught.value)


def test_a_suite_is_repetitive_on_purpose(client):
    """If no two briefs share a convention, memory has nothing to help with."""
    suite = evals.get_suite("software_studio")
    keys = [check["key"] for brief in suite.briefs for check in brief.checks]
    assert len(keys) > len(set(keys)), (
        "at least one check must recur across briefs, or the A/B measures nothing"
    )


# --------------------------------------------------------------------------
# the memory switch the comparison depends on
# --------------------------------------------------------------------------


def test_switching_memory_off_actually_stops_retrieval(client, company, no_embeddings):
    """The A/B is worthless if the off arm still remembers."""
    from agents import context as context_builder
    from services import memory

    db = session()
    try:
        company_row = db.get(Company, company["id"])
        employee = company_row.employees[0]
        memory.remember(
            db,
            company_id=company_row.id,
            employee_id=employee.id,
            kind="fact",
            title="The sensor API paginates with a cursor",
        )
        db.commit()

        on = context_builder.assemble(
            db, company=company_row, employee=employee, query="sensor pagination"
        )
        assert on.report["facts"]["count"] == 1
        assert "cursor" in on.facts

        company_row.settings = {**(company_row.settings or {}), "memory_enabled": False}
        db.add(company_row)
        db.commit()

        off = context_builder.assemble(
            db, company=company_row, employee=employee, query="sensor pagination"
        )
        assert off.report["facts"]["count"] == 0
        assert off.report["facts"]["mode"] == "off"
        assert off.facts == ""
        # The blocks are who they are, not what they learnt; those stay.
        assert off.blocks
    finally:
        db.close()


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------


def _arm(memory: bool, **values) -> evals.ArmResult:
    return evals.ArmResult(memory=memory, company_id=f"c-{memory}", **values)


def test_the_report_says_when_memory_helped(client):
    arms = [
        _arm(True, first_try_pass_rate=0.8, tool_calls_per_item=4.0, tokens_per_artifact=900.0),
        _arm(False, first_try_pass_rate=0.5, tool_calls_per_item=7.0, tokens_per_artifact=1400.0),
    ]
    rows = evals._compare(arms)
    assert {row["verdict"] for row in rows} == {"better"}
    assert "helped on 3 of 3" in evals._verdict(arms)
    assert "repeat it before believing it" in evals._verdict(arms)


def test_the_report_says_so_when_memory_did_not_help(client):
    """The whole point: it has to be able to report that the idea failed."""
    arms = [
        _arm(True, first_try_pass_rate=0.4, tool_calls_per_item=9.0, tokens_per_artifact=2000.0),
        _arm(False, first_try_pass_rate=0.7, tool_calls_per_item=5.0, tokens_per_artifact=1100.0),
    ]
    rows = evals._compare(arms)
    assert {row["verdict"] for row in rows} == {"worse"}
    assert "not earning its complexity" in evals._verdict(arms)


def test_a_run_that_measured_nothing_does_not_claim_a_result(client):
    arms = [_arm(True), _arm(False)]
    assert all(row["verdict"] == "not measured" for row in evals._compare(arms))
    note = evals._verdict(arms)
    assert "Nothing was measurable" in note
    assert "says nothing about memory either way" in note


def test_a_mixed_result_is_reported_as_mixed(client):
    arms = [
        _arm(True, first_try_pass_rate=0.8, tool_calls_per_item=9.0, tokens_per_artifact=1000.0),
        _arm(False, first_try_pass_rate=0.5, tool_calls_per_item=5.0, tokens_per_artifact=1000.0),
    ]
    note = evals._verdict(arms)
    assert "No clear difference" in note
    assert "not paying for itself" in note


def test_the_api_lists_the_suites(client):
    body = client.get("/evals").json()
    assert {suite["key"] for suite in body["suites"]} >= {"software_studio", "law_firm"}
    assert all(suite["briefs"] for suite in body["suites"])
