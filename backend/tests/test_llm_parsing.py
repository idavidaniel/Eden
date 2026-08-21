import pytest

from agents.llm import loads_lenient


def test_parses_plain_json():
    assert loads_lenient('{"tickets": []}') == {"tickets": []}


def test_strips_code_fences_and_prose():
    text = 'Here is the plan:\n```json\n{"tickets": [{"title": "A"}]}\n```'
    assert loads_lenient(text)["tickets"][0]["title"] == "A"


def test_salvages_a_truncated_plan():
    truncated = '{"tickets": [{"title": "A"}, {"title": "B"}, {"title": "C", "descripti'
    salvaged = loads_lenient(truncated)
    assert [t["title"] for t in salvaged["tickets"]] == ["A", "B"]


def test_raises_when_there_is_no_json():
    with pytest.raises(ValueError):
        loads_lenient("I cannot help with that.")


def test_plan_schema_restricts_roles_and_requires_criteria():
    from agents.prompts import plan_schema

    schema = plan_schema(["backend_engineer", "qa_engineer"])
    item = schema["properties"]["tickets"]["items"]

    assert item["properties"]["role"]["enum"] == ["backend_engineer", "qa_engineer"]
    assert "acceptance_criteria" in item["required"]
    assert item["properties"]["type"]["enum"] == ["task", "story", "bug", "chore"]
