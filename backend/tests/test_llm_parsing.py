import pytest

from agents.llm import loads_lenient


def test_parses_plain_json():
    assert loads_lenient('{"items": []}') == {"items": []}


def test_strips_code_fences_and_prose():
    text = 'Here is the plan:\n```json\n{"items": [{"title": "A"}]}\n```'
    assert loads_lenient(text)["items"][0]["title"] == "A"


def test_salvages_a_truncated_plan():
    truncated = '{"items": [{"title": "A"}, {"title": "B"}, {"title": "C", "descripti'
    salvaged = loads_lenient(truncated)
    assert [t["title"] for t in salvaged["items"]] == ["A", "B"]


def test_raises_when_there_is_no_json():
    with pytest.raises(ValueError):
        loads_lenient("I cannot help with that.")


def test_plan_schema_is_shaped_by_the_company_not_by_software():
    """The planner's vocabulary comes from the industry pack, not from this file."""
    from agents.prompts import plan_schema

    schema = plan_schema(
        ["associate", "managing_partner"],
        ["matter", "drafting_task"],
        ["draft_document", "legal_research"],
    )
    item = schema["properties"]["items"]["items"]

    assert item["properties"]["role"]["enum"] == ["associate", "managing_partner"]
    assert item["properties"]["kind"]["enum"] == ["matter", "drafting_task"]
    assert item["properties"]["capability"]["enum"] == ["draft_document", "legal_research"]
    assert "acceptance_criteria" in item["required"]
    assert "capability" in item["required"]
