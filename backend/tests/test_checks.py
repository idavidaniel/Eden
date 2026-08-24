"""The six kinds of check, and the mechanisms that keep the soft one honest."""

import pytest

from db import session
from models import Approval, Check, Company, Project, WorkItem
from services import artifacts as artifact_service
from services import blobs
from services import checks as check_service
from services.checks.base import CheckContext
from services.checks.expressions import ExpressionError, evaluate


def _context(company_id: str, project_id: str | None = None, content: str = ""):
    db = session()
    company = db.get(Company, company_id)
    project = db.get(Project, project_id) if project_id else None
    return db, CheckContext(db=db, company=company, project=project, content=content)


def _artifact(db, company, project, name: str, content: str, kind: str = "document"):
    return artifact_service.record(
        db, company=company, project=project, name=name, kind=kind, content=content
    )


# --------------------------------------------------------------------------
# the safe expression evaluator
# --------------------------------------------------------------------------


def test_the_expression_evaluator_does_arithmetic_and_nothing_else():
    assert evaluate("abs(total - sum(lines)) < 0.01", {"total": 10.0, "lines": [4.0, 6.0]})
    assert evaluate("len(rows) >= 3", {"rows": [1, 2, 3]})

    for hostile in [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "(1).__class__.__bases__",
        "[x for x in ().__class__.__mro__]",
    ]:
        with pytest.raises(ExpressionError):
            evaluate(hostile, {})


# --------------------------------------------------------------------------
# assertion
# --------------------------------------------------------------------------


def test_assertion_finds_missing_sections_and_leftover_placeholders(client, law_firm, project=None):
    db, _ = _context(law_firm["id"])
    try:
        company = db.get(Company, law_firm["id"])
        project_row = Project(company_id=company.id, name="Matter", key="MAT")
        db.add(project_row)
        db.flush()

        draft = _artifact(
            db,
            company,
            project_row,
            "nda.md",
            "# Term\nOne year.\n\n# Governing Law\nEngland.\n\nFee: [AMOUNT]\n",
            kind="contract_draft",
        )
        check = db.scalar(
            db.query(Check).filter_by(company_id=company.id, key="required_clauses").statement
        )
        result = check_service.run_one(
            db, check, company=company, project=project_row, artifact=draft
        )
        db.commit()

        assert result.status == "fail"
        assert "Termination" in result.detail
        assert "Term" in result.evidence["sections_found"]

        placeholders = db.scalar(
            db.query(Check).filter_by(company_id=company.id, key="no_placeholders").statement
        )
        second = check_service.run_one(
            db, placeholders, company=company, project=project_row, artifact=draft
        )
        db.commit()
        assert second.status == "fail"
        assert "[AMOUNT]" in second.evidence["found"]
    finally:
        db.close()


def test_assertion_can_check_that_numbers_add_up(client, company, project):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        report = _artifact(
            db,
            company_row,
            project_row,
            "invoice.md",
            "Line: 120.00\nLine: 80.00\nTotal: 200.00\n",
        )
        check = Check(
            company_id=company_row.id,
            project_id=project_row.id,
            key="totals",
            name="Line items sum to the total",
            kind="assertion",
            spec={
                "extract": {"lines": r"Line: ([\d.]+)", "total": r"Total: ([\d.]+)"},
                "expression": "abs(total - sum(lines)) < 0.01",
            },
        )
        db.add(check)
        db.flush()
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=report
        )
        db.commit()
        assert result.status == "pass"

        wrong = _artifact(
            db,
            company_row,
            project_row,
            "invoice.md",
            "Line: 120.00\nLine: 80.00\nTotal: 260.00\n",
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=wrong
        )
        db.commit()
        assert result.status == "fail"
    finally:
        db.close()


# --------------------------------------------------------------------------
# schema
# --------------------------------------------------------------------------


def test_schema_check_rejects_a_file_that_does_not_parse(client, company, project):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        check = Check(
            company_id=company_row.id,
            project_id=project_row.id,
            key="config_shape",
            name="Config parses and has the required keys",
            kind="schema",
            spec={"format": "json", "required_keys": ["name", "version"]},
        )
        db.add(check)
        db.flush()

        broken = _artifact(db, company_row, project_row, "config.json", "{not json")
        assert (
            check_service.run_one(
                db, check, company=company_row, project=project_row, artifact=broken
            ).status
            == "fail"
        )

        incomplete = _artifact(db, company_row, project_row, "config.json", '{"name": "x"}')
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=incomplete
        )
        assert result.status == "fail" and "version" in result.detail

        good = _artifact(
            db, company_row, project_row, "config.json", '{"name": "x", "version": "1"}'
        )
        assert (
            check_service.run_one(
                db, check, company=company_row, project=project_row, artifact=good
            ).status
            == "pass"
        )
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# citation
# --------------------------------------------------------------------------


def test_a_citation_must_actually_appear_in_the_source(client, company, project):
    """The one thing a model cannot fake: the platform reads the page itself."""
    from datetime import UTC, datetime

    from models import Source

    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        source = Source(
            created_at=datetime.now(UTC),
            company_id=company_row.id,
            url="https://example.org/report",
            title="Annual report",
            content_hash="x" * 64,
            text_key=blobs.put_text("Revenue increased 14 per cent over the year."),
            chars=44,
        )
        db.add(source)
        db.flush()
        short = source.id[:8]

        check = Check(
            company_id=company_row.id,
            project_id=project_row.id,
            key="cited",
            name="Every claim resolves to a source",
            kind="citation",
            spec={},
        )
        db.add(check)
        db.flush()

        honest = _artifact(
            db,
            company_row,
            project_row,
            "memo.md",
            f'Revenue grew 14%. [src:{short} "revenue increased 14 per cent"]\n',
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=honest
        )
        assert result.status == "pass", result.detail

        invented = _artifact(
            db,
            company_row,
            project_row,
            "memo2.md",
            f'Revenue grew 40%. [src:{short} "revenue increased 40 per cent"]\n',
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=invented
        )
        assert result.status == "fail"
        assert "does not appear" in result.evidence["broken"][0]["problem"]

        unsourced = _artifact(
            db, company_row, project_row, "memo3.md", "Revenue grew 14% last year, roughly.\n"
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=unsourced
        )
        assert result.status == "fail"
        assert result.evidence["counts"]["uncited"] >= 1
        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# rubric
# --------------------------------------------------------------------------


def _rubric_check(db, company, project):
    check = Check(
        company_id=company.id,
        project_id=project.id,
        key="quality",
        name="Says something concrete",
        kind="rubric",
        spec={
            "evaluators": 3,
            "criteria": [{"id": "concrete", "question": "Is there a specific number in it?"}],
        },
    )
    db.add(check)
    db.flush()
    return check


def test_a_rubric_verdict_needs_a_quote_that_is_really_there(
    client, company, project, monkeypatch
):
    """An evaluator that cannot point at real text does not get a vote."""
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        check = _rubric_check(db, company_row, project_row)
        artifact = _artifact(
            db, company_row, project_row, "note.md", "Throughput reached 480 requests a second."
        )

        monkeypatch.setattr(
            "agents.llm.structured_call",
            lambda *args, **kwargs: {
                "criteria": [
                    {
                        "criterion_id": "concrete",
                        "verdict": "pass",
                        "evidence_quote": "we measured 9000 requests a second",
                        "reason": "It gives a number.",
                    }
                ]
            },
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=artifact
        )
        db.commit()

        assert result.status == "pending"
        assert result.evidence["quote_failures"] == 3
        assert result.evidence["criteria"][0]["verdict"] == "unresolved"
    finally:
        db.close()


def test_a_rubric_passes_when_the_quote_checks_out(client, company, project, monkeypatch):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        check = _rubric_check(db, company_row, project_row)
        artifact = _artifact(
            db, company_row, project_row, "note2.md", "Throughput reached 480 requests a second."
        )
        monkeypatch.setattr(
            "agents.llm.structured_call",
            lambda *args, **kwargs: {
                "criteria": [
                    {
                        "criterion_id": "concrete",
                        "verdict": "pass",
                        "evidence_quote": "480 requests a second",
                        "reason": "It gives a measured number.",
                    }
                ]
            },
        )
        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=artifact
        )
        db.commit()
        assert result.status == "pass"
        assert result.evidence["agreement"] == 1.0
    finally:
        db.close()


def test_a_split_panel_escalates_rather_than_averaging(client, company, project, monkeypatch):
    """Never average a disagreement into a pass."""
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        check = _rubric_check(db, company_row, project_row)
        artifact = _artifact(
            db, company_row, project_row, "note3.md", "Throughput reached 480 requests a second."
        )

        verdicts = iter(["pass", "fail", "pass", "fail"])

        def alternating(*args, **kwargs):
            return {
                "criteria": [
                    {
                        "criterion_id": "concrete",
                        "verdict": next(verdicts, "pass"),
                        "evidence_quote": "480 requests a second",
                        "reason": "…",
                    }
                ]
            }

        monkeypatch.setattr("agents.llm.structured_call", alternating)
        # Two evaluators, one each way: agreement 0.5, below the threshold.
        check.spec = {**check.spec, "evaluators": 2}
        db.add(check)
        db.flush()

        result = check_service.run_one(
            db, check, company=company_row, project=project_row, artifact=artifact
        )
        db.commit()
        assert result.status == "pending"
        assert result.evidence["needs_human"] is True
    finally:
        db.close()


def test_the_evaluator_is_never_told_who_wrote_it(client, company, project, monkeypatch):
    db, _ = _context(company["id"], project["id"])
    seen: list = []
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        author = company_row.employees[0]
        check = _rubric_check(db, company_row, project_row)
        artifact = _artifact(db, company_row, project_row, "note4.md", "Reached 480 rps.")

        def capture(messages, *args, **kwargs):
            seen.append("\n".join(message["content"] for message in messages))
            return {"criteria": []}

        monkeypatch.setattr("agents.llm.structured_call", capture)
        check_service.run_one(
            db,
            check,
            company=company_row,
            project=project_row,
            artifact=artifact,
            author=author,
        )
        db.commit()

        assert seen, "the evaluator should have been asked"
        assert author.name not in seen[0]
        assert "you do not know who wrote it" in seen[0].lower()
    finally:
        db.close()


# --------------------------------------------------------------------------
# human
# --------------------------------------------------------------------------


def test_a_human_check_is_pending_until_a_person_decides(client, company, project):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        item = WorkItem(project_id=project_row.id, key="X-1", title="Send it")
        db.add(item)
        check = Check(
            company_id=company_row.id,
            project_id=project_row.id,
            work_item_id=None,
            key="signoff",
            name="A partner has signed off",
            kind="human",
            spec={"reason": "Nothing is filed unsigned."},
        )
        db.add(check)
        db.flush()

        first = check_service.run_one(
            db, check, company=company_row, project=project_row, work_item=item
        )
        db.commit()
        assert first.status == "pending"

        approval_id = first.evidence["approval_id"]
        approval = db.get(Approval, approval_id)
        assert approval.status == "pending"

        from services import inbox

        inbox.decide(db, approval, approved=True, by="You")
        db.commit()

        second = check_service.run_one(
            db, check, company=company_row, project=project_row, work_item=item
        )
        db.commit()
        assert second.status == "pass"
        assert "You" in second.detail
    finally:
        db.close()


# --------------------------------------------------------------------------
# the framework itself
# --------------------------------------------------------------------------


def test_a_check_that_blows_up_is_an_error_not_a_pass(client, company, project, monkeypatch):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        check = Check(
            company_id=company_row.id,
            project_id=project_row.id,
            key="boom",
            name="Explodes",
            kind="command",
            spec={"command": "pytest -q"},
        )
        db.add(check)
        db.flush()

        def explode(*args, **kwargs):
            raise RuntimeError("the check runner fell over")

        monkeypatch.setitem(check_service.RUNNERS, "command", explode)
        result = check_service.run_one(db, check, company=company_row, project=project_row)
        db.commit()
        assert result.status == "error"
        assert "fell over" in result.detail
    finally:
        db.close()


def test_the_legacy_verify_command_becomes_an_ordinary_check(client, company, project):
    """An upgrade must not change what an existing project does."""
    client.patch(f"/projects/{project['id']}", json={"verify_command": "python3 ok.py"})
    client.put(f"/projects/{project['id']}/file", json={"path": "ok.py", "content": "print(1)\n"})

    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        created = check_service.ensure_project_checks(db, company_row, project_row)
        db.commit()
        assert [check.key for check in created] == ["verify_command"]
        assert created[0].kind == "command"
        assert created[0].spec["command"] == "python3 ok.py"

        # Idempotent: a second call does not stack up duplicates.
        assert check_service.ensure_project_checks(db, company_row, project_row) == []
    finally:
        db.close()


def test_running_checks_from_the_api_reports_a_verdict(client, company, project):
    client.patch(f"/projects/{project['id']}", json={"verify_command": "python3 fails.py"})
    client.put(
        f"/projects/{project['id']}/file",
        json={"path": "fails.py", "content": "raise SystemExit(2)\n"},
    )
    item = client.post(
        f"/projects/{project['id']}/work-items", json={"title": "Claims to work"}
    ).json()

    response = client.post(f"/work-items/{item['id']}/checks/run").json()
    assert response["verdict"]["ok"] is False
    assert any(result["status"] == "fail" for result in response["results"])
    assert "exit 2" in response["verdict"]["summary"]


def test_an_artifact_is_recorded_with_its_hash_and_deduplicated(client, company, project):
    db, _ = _context(company["id"], project["id"])
    try:
        company_row = db.get(Company, company["id"])
        project_row = db.get(Project, project["id"])
        first = _artifact(db, company_row, project_row, "memo.md", "Same words.")
        again = _artifact(db, company_row, project_row, "memo.md", "Same words.")
        changed = _artifact(db, company_row, project_row, "memo.md", "Different words.")
        db.commit()

        assert again.id == first.id, "identical content should not create a version"
        assert changed.version == 2
        db.refresh(first)
        assert first.superseded_by == changed.id
        assert artifact_service.verify_content_hash(db, changed)["state"] == "intact"
    finally:
        db.close()
