"""The record of what happened, and whether it can still be re-proved.

This is the part of the product that answers "did the work actually get done?"
without asking anyone to take an agent's word for it, so the tests here are
mostly attempts to make it lie.
"""

import json

from sqlalchemy import select

from db import session
from models import Company, LedgerEntry, Project, WorkItem
from models.ledger import GENESIS_HASH
from services import artifacts as artifact_service
from services import blobs, checks, ledger, proof


def _context(company_id, project_id=None):
    db = session()
    project = db.get(Project, project_id) if project_id else None
    return db, db.get(Company, company_id), project


def _write(db, company, project, name, body, kind="document"):
    return artifact_service.record(
        db,
        company=company,
        project=project,
        kind=kind,
        name=name,
        content=body,
        produced_by=company.employees[0],
    )


# --------------------------------------------------------------------------
# the chain
# --------------------------------------------------------------------------


def test_the_chain_starts_at_genesis_and_threads_forward(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        first = ledger.append(
            db,
            company_id=company_row.id,
            kind="company.founded",
            actor_label="You",
            payload={"name": company_row.name},
        )
        second = ledger.append(
            db,
            company_id=company_row.id,
            kind="project.created",
            actor_label="You",
            payload={"name": "Sensor Portal"},
        )
        db.commit()

        assert first.height == 0
        assert first.prev_hash == GENESIS_HASH
        assert second.height == 1
        assert second.prev_hash == first.hash
        assert ledger.verify_chain(db, company_row.id)["intact"] is True
    finally:
        db.close()


def test_two_companies_keep_separate_chains(client, company, law_firm):
    db = session()
    try:
        for company_id in (company["id"], law_firm["id"]):
            ledger.append(
                db,
                company_id=company_id,
                kind="company.founded",
                actor_label="You",
                payload={},
            )
        db.commit()

        one = ledger.chain(db, company["id"])
        other = ledger.chain(db, law_firm["id"])
        assert [entry.height for entry in one] == [0]
        assert [entry.height for entry in other] == [0]
        assert one[0].hash != other[0].hash, "different companies, different chains"
    finally:
        db.close()


def test_editing_a_recorded_payload_breaks_the_chain(client, company):
    """The point of the chain: you cannot quietly rewrite what happened."""
    db, company_row, _ = _context(company["id"])
    try:
        for index in range(3):
            ledger.append(
                db,
                company_id=company_row.id,
                kind="work_item.closed",
                actor_label="Ada Kern",
                payload={"key": f"ITEM-{index}", "verdict": "pass"},
            )
        db.commit()
        assert ledger.verify_chain(db, company_row.id)["intact"] is True

        tampered = db.scalar(
            select(LedgerEntry).where(
                LedgerEntry.company_id == company_row.id, LedgerEntry.height == 1
            )
        )
        tampered.payload = {"key": "ITEM-1", "verdict": "pass", "note": "it was fine, honest"}
        db.add(tampered)
        db.commit()

        verdict = ledger.verify_chain(db, company_row.id)
        assert verdict["intact"] is False
        assert verdict["problems"], "a broken chain must say where it broke"
        assert any(problem["height"] == 1 for problem in verdict["problems"])
    finally:
        db.close()


def test_deleting_an_entry_breaks_the_chain(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        for index in range(3):
            ledger.append(
                db,
                company_id=company_row.id,
                kind="note",
                actor_label="You",
                payload={"n": index},
            )
        db.commit()

        middle = db.scalar(
            select(LedgerEntry).where(
                LedgerEntry.company_id == company_row.id, LedgerEntry.height == 1
            )
        )
        db.delete(middle)
        db.commit()

        assert ledger.verify_chain(db, company_row.id)["intact"] is False
    finally:
        db.close()


def test_a_hash_is_stable_across_key_order(client, company):
    """Canonical JSON, or the chain would break on a dict reordering."""
    one = ledger.entry_hash(GENESIS_HASH, {"a": 1, "b": [1, 2], "c": {"x": 1, "y": 2}})
    other = ledger.entry_hash(GENESIS_HASH, {"c": {"y": 2, "x": 1}, "b": [1, 2], "a": 1})
    assert one == other


def test_the_verify_endpoint_reports_a_healthy_chain(client, company):
    db, company_row, _ = _context(company["id"])
    try:
        ledger.append(
            db, company_id=company_row.id, kind="note", actor_label="You", payload={}
        )
        db.commit()
    finally:
        db.close()

    body = client.post(f"/companies/{company['id']}/ledger/verify").json()
    assert body["intact"] is True
    assert body["entries"] >= 1

    listed = client.get(f"/companies/{company['id']}/ledger").json()
    assert listed["entries"][0]["kind"]


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------


def test_recording_an_artifact_puts_its_hash_in_the_chain(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        row = _write(db, company_row, project_row, "spec.md", "# Spec\n\nOne page.")
        db.commit()

        entry = db.scalar(
            select(LedgerEntry).where(
                LedgerEntry.company_id == company_row.id,
                LedgerEntry.kind == "artifact.version",
                LedgerEntry.subject_id == row.id,
            )
        )
        assert entry is not None
        assert entry.payload["content_hash"] == row.content_hash
    finally:
        db.close()


def test_an_edited_file_on_disk_is_caught(client, company, project):
    """The hash is what makes 'done' checkable rather than claimed."""
    import os

    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        row = _write(db, company_row, project_row, "report.md", "Latency is 40ms.")
        db.commit()
        assert artifact_service.verify_content_hash(db, row)["state"] == "intact"

        path = blobs.path(row.content_hash)
        with open(path, "w") as handle:
            handle.write("Latency is 4ms.")

        assert artifact_service.verify_content_hash(db, row)["state"] == "changed"
        os.remove(path)
        assert artifact_service.verify_content_hash(db, row)["state"] == "missing"
    finally:
        db.close()


def test_saving_the_same_bytes_twice_does_not_make_a_new_version(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        first = _write(db, company_row, project_row, "plan.md", "Same words.")
        db.commit()
        second = _write(db, company_row, project_row, "plan.md", "Same words.")
        db.commit()
        assert second.id == first.id
        assert second.version == 1

        third = _write(db, company_row, project_row, "plan.md", "Different words.")
        db.commit()
        assert third.version == 2
        assert third.content_hash != first.content_hash
    finally:
        db.close()


# --------------------------------------------------------------------------
# re-proving a finished project
# --------------------------------------------------------------------------


LAUNCH_NOTE = "## Summary\nWe shipped {key}.\n\n## Risks\nNone known.\n"
LAUNCH_SPEC = {"must_contain_sections": ["Summary", "Risks"]}


def _finished_item(db, company_row, project_row, *, key: str, body=None, spec=None):
    """A work item with an artifact and a passing deterministic check.

    Each caller passes its own key, because blobs are content-addressed: two
    tests writing identical bytes would share one file on disk, and a test that
    corrupts a deliverable on purpose would corrupt it for everybody.
    """
    from models import Check

    body = LAUNCH_NOTE.format(key=key) if body is None else body
    spec = LAUNCH_SPEC if spec is None else spec
    item = WorkItem(
        project_id=project_row.id,
        key=key,
        title="Write the launch note",
        kind="document",
        status="in_review",
        assignee_id=company_row.employees[0].id,
    )
    db.add(item)
    db.flush()

    artifact = artifact_service.record(
        db,
        company=company_row,
        project=project_row,
        work_item_id=item.id,
        kind="document",
        name="launch.md",
        content=body,
        produced_by=company_row.employees[0],
    )
    check = Check(
        company_id=company_row.id,
        project_id=project_row.id,
        work_item_id=item.id,
        key="launch_shape",
        name="The launch note has the sections we promised",
        kind="assertion",
        spec=spec,
    )
    db.add(check)
    db.flush()
    return item, artifact, check


def test_a_finished_project_re_proves_itself(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, _, _ = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-11",
        )
        results = checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()
        assert [row.status for row in results] == ["pass"]

        report = proof.reverify(db, project_row)
        assert report["proved"] is True
        assert report["chain"]["intact"] is True
        assert report["artifacts"]["not_in_ledger"] == []
        assert report["checks"]["disagreements"] == []
        assert report["note"] == "Everything the record claims still holds."
    finally:
        db.close()


def test_a_project_stops_proving_itself_once_the_deliverable_changes(
    client, company, project
):
    """Re-verification is not a formality: change the file, lose the proof."""
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, artifact, _ = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-12",
        )
        checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()

        with open(blobs.path(artifact.content_hash), "w") as handle:
            handle.write("## Summary\nWe shipped.\n")  # the Risks section is gone

        report = proof.reverify(db, project_row)
        assert report["proved"] is False
        assert report["artifacts"]["changed"], "the hash mismatch should be reported"
        assert "no longer match" in report["note"]
    finally:
        db.close()


def test_a_replayed_check_that_now_fails_is_reported_as_a_disagreement(
    client, company, project
):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, _, check = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-13",
        )
        checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()

        # Someone quietly tightened the standard after the fact.
        check.spec = {"must_contain_sections": ["Summary", "Risks", "Rollback plan"]}
        db.add(check)
        db.commit()

        report = proof.reverify(db, project_row)
        assert report["proved"] is False
        assert report["checks"]["disagreements"]
        disagreement = report["checks"]["disagreements"][0]
        assert disagreement["then"] == "pass"
        assert disagreement["now"] == "fail"
    finally:
        db.close()


def test_a_rubric_verdict_is_reported_rather_than_silently_replayed(
    client, company, project
):
    """A model's opinion is not reproducible, and the report says so."""
    from models import Check

    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, _, _ = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-14",
        )
        db.add(
            Check(
                company_id=company_row.id,
                project_id=project_row.id,
                work_item_id=item.id,
                key="reads_well",
                name="It reads like a person wrote it",
                kind="rubric",
                spec={"criteria": [{"key": "clear", "question": "Is it clear?"}]},
            )
        )
        db.flush()
        checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()

        report = proof.reverify(db, project_row)
        skipped_kinds = {row["kind"] for row in report["checks"]["skipped"]}
        assert "rubric" in skipped_kinds
        assert "could not be replayed" in report["note"] or report["proved"] is False
    finally:
        db.close()


def test_the_work_record_is_exportable_and_says_how_to_check_it(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, _, _ = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-15",
        )
        checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()
    finally:
        db.close()

    record = client.get(f"/projects/{project['id']}/work-record").json()
    assert record["project"]["key"] == project["key"]
    assert record["how_to_verify"]
    assert record["record_hash"]
    assert record["artifacts"], "a work record with no deliverables proves nothing"
    # It has to survive leaving this machine.
    assert json.loads(json.dumps(record))["record_hash"] == record["record_hash"]


def test_the_verify_endpoint_re_proves_a_project(client, company, project):
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        item, _, _ = _finished_item(
            db,
            company_row,
            project_row,
            key="SENSOR-16",
        )
        checks.run_for_work_item(
            db, company=company_row, project=project_row, work_item=item
        )
        db.commit()
    finally:
        db.close()

    body = client.post(f"/projects/{project['id']}/ledger/verify").json()
    assert body["proved"] is True
    assert body["chain"]["intact"] is True


def test_an_artifact_outside_the_chain_is_not_proof(client, company, project):
    """A deliverable that never reached the ledger cannot support a claim."""
    db, company_row, project_row = _context(company["id"], project["id"])
    try:
        row = _write(db, company_row, project_row, "sneaky.md", "Trust me.")
        db.commit()

        for entry in db.scalars(
            select(LedgerEntry).where(
                LedgerEntry.kind == "artifact.version",
                LedgerEntry.subject_id == row.id,
            )
        ):
            db.delete(entry)
        db.commit()

        report = proof.reverify(db, project_row, rerun_checks=False)
        assert row.id in report["artifacts"]["not_in_ledger"]
        assert report["proved"] is False
    finally:
        db.close()
