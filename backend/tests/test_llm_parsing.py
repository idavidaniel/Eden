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


# --------------------------------------------------------------------------
# asking for structure, and the token budget that has to survive the thinking
# --------------------------------------------------------------------------


class _Reply:
    """Shaped like the provider's answer, with a finish reason that matters."""

    def __init__(self, arguments: str | None, finish_reason: str = "stop", tokens: int = 100):
        call = (
            type(
                "Call",
                (),
                {"function": type("Fn", (), {"name": "submit_plan", "arguments": arguments})()},
            )()
            if arguments is not None
            else None
        )
        self.choices = [
            type(
                "Choice",
                (),
                {
                    "finish_reason": finish_reason,
                    "message": type(
                        "Message", (), {"tool_calls": [call] if call else [], "content": ""}
                    )(),
                },
            )()
        ]
        self.usage = type("Usage", (), {"completion_tokens": tokens, "prompt_tokens": 50})()


def _ask(monkeypatch, replies: list):
    """Run `structured_call` against a scripted provider, returning the calls made."""
    from agents import llm

    seen: list[dict] = []
    queue = list(replies)

    def fake_complete(_kind, **kwargs):
        seen.append(kwargs)
        return queue.pop(0)

    monkeypatch.setattr(llm, "complete", fake_complete)
    return seen


def test_a_structured_call_leaves_room_for_thinking_and_the_answer(monkeypatch):
    """The bug: 3000 tokens, unbounded thinking, and no room left to answer.

    A whole run died with "Model did not call submit_plan" because the model
    spent every token reasoning. The budget has to cover both.
    """
    from agents.llm import STRUCTURED_ANSWER_TOKENS, structured_call
    from config import get_settings

    seen = _ask(monkeypatch, [_Reply('{"items": []}', finish_reason="tool_calls")])
    structured_call([], "submit_plan", "d", {"type": "object"})

    budget = seen[0]["extra_body"]["reasoning_budget"]
    assert seen[0]["max_tokens"] > budget, (
        "the cap must exceed the reasoning budget, or there is nothing left to answer with"
    )
    assert seen[0]["max_tokens"] == budget + STRUCTURED_ANSWER_TOKENS
    assert budget == get_settings().reasoning_budget


def test_thinking_is_bounded_rather_than_left_open(monkeypatch):
    from agents.llm import structured_call

    seen = _ask(monkeypatch, [_Reply('{"ok": true}', finish_reason="tool_calls")])
    structured_call([], "submit_plan", "d", {"type": "object"})

    assert "reasoning_budget" in seen[0]["extra_body"]
    assert seen[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "submit_plan"},
    }


def test_running_out_of_room_is_retried_with_thinking_off(monkeypatch):
    """A forced tool call does not need narration, so switching it off works."""
    from agents.llm import structured_call

    seen = _ask(
        monkeypatch,
        [
            _Reply(None, finish_reason="length", tokens=3000),
            _Reply('{"items": [{"title": "A"}]}', finish_reason="tool_calls", tokens=1000),
        ],
    )
    result = structured_call([], "submit_plan", "d", {"type": "object"})

    assert result["items"][0]["title"] == "A"
    assert len(seen) == 2, "it should have tried again"
    assert seen[0]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True
    assert seen[1]["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
    assert "reasoning_budget" not in seen[1]["extra_body"]


def test_a_call_that_succeeds_first_time_is_not_repeated(monkeypatch):
    from agents.llm import structured_call

    seen = _ask(monkeypatch, [_Reply('{"items": []}', finish_reason="tool_calls")])
    structured_call([], "submit_plan", "d", {"type": "object"})
    assert len(seen) == 1


def test_giving_up_says_why_rather_than_just_that(monkeypatch):
    """"Model did not call submit_plan" told nobody anything."""
    from agents.llm import structured_call

    _ask(
        monkeypatch,
        [
            _Reply(None, finish_reason="length", tokens=8096),
            _Reply(None, finish_reason="length", tokens=8096),
        ],
    )
    with pytest.raises(ValueError) as caught:
        structured_call([], "submit_plan", "d", {"type": "object"})

    message = str(caught.value)
    assert "submit_plan" in message
    assert "thinking switched off" in message
    assert "length" in message, "the reason it stopped is the whole diagnosis"
