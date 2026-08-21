"""Model client: one place that knows how to talk to the provider.

Supports plain completions, streaming, and OpenAI-style tool calling, which is
what the employee loop runs on.
"""

import json
import logging
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from config import get_settings

log = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is available for the model provider."""


class ModelCall(dict):
    """The model's reply: reasoning, text and any tool calls it wants to make."""

    @property
    def reasoning(self) -> str:
        return self.get("reasoning", "")

    @property
    def content(self) -> str:
        return self.get("content", "")

    @property
    def tool_calls(self) -> list[dict]:
        return self.get("tool_calls", [])


def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise LLMNotConfigured(
            "NVIDIA_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return OpenAI(base_url=settings.nvidia_base_url, api_key=settings.nvidia_api_key, timeout=180)


def chat(
    messages: list[dict],
    tools: list[dict] | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    thinking: bool = True,
) -> ModelCall:
    """One non-streaming turn. Returns reasoning, content and tool calls."""
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model or settings.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens or settings.max_tokens,
    }
    if thinking:
        kwargs["extra_body"] = {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": settings.reasoning_budget,
        }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    completion = get_client().chat.completions.create(**kwargs)
    message = completion.choices[0].message

    calls = []
    for call in message.tool_calls or []:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {"_raw": call.function.arguments}
        calls.append({"id": call.id, "name": call.function.name, "arguments": arguments})

    return ModelCall(
        reasoning=getattr(message, "reasoning_content", "") or "",
        content=message.content or "",
        tool_calls=calls,
    )


def stream(messages: list[dict], model: str | None = None) -> Iterator[tuple[str, str]]:
    """Yield ("reasoning" | "content", delta) tuples, for chat-style surfaces."""
    settings = get_settings()
    completion = get_client().chat.completions.create(
        model=model or settings.model,
        messages=messages,
        temperature=0.7,
        max_tokens=settings.max_tokens,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": settings.reasoning_budget,
        },
        stream=True,
    )
    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield "reasoning", reasoning
        if delta.content:
            yield "content", delta.content


def structured_call(
    messages: list[dict],
    name: str,
    description: str,
    parameters: dict,
    model: str | None = None,
    max_tokens: int = 3000,
) -> Any:
    """Get structured data by forcing a tool call.

    More reliable than asking for JSON in prose: reasoning models narrate before
    answering, and the narration is what breaks a JSON parse. A forced function
    call has nowhere to put prose.
    """
    settings = get_settings()
    completion = get_client().chat.completions.create(
        model=model or settings.model,
        messages=messages,
        temperature=0.3,
        max_tokens=max_tokens,
        tools=[
            {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            }
        ],
        tool_choice={"type": "function", "function": {"name": name}},
    )
    calls = completion.choices[0].message.tool_calls or []
    if not calls:
        raise ValueError(f"Model did not call {name}.")
    return loads_lenient(calls[0].function.arguments or "{}")


def loads_lenient(text: str) -> Any:
    """Parse JSON that may be fenced, prefixed with prose, or cut off mid-object.

    Long plans get truncated by the token limit, and losing a whole plan because
    its last ticket is half-written is worse than dropping that ticket.
    """
    text = text.strip()
    if "```" in text:
        block = text.split("```")[1]
        text = block[4:] if block.lower().startswith("json") else block
        text = text.strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start > 0:
        text = text[start:]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Walk back to the last complete object and close whatever is still open.
    closers = ["", "}", "]}", "}]}", '"}]}']
    for cut in range(len(text) - 1, 0, -1):
        if text[cut] != "}":
            continue
        head = text[: cut + 1]
        for suffix in closers:
            try:
                return json.loads(head + suffix)
            except json.JSONDecodeError:
                continue
    raise ValueError("Model did not return usable JSON.")


def json_call(
    messages: list[dict],
    schema_hint: str,
    model: str | None = None,
    max_tokens: int = 3000,
) -> Any:
    """Ask for JSON and parse it, retrying once if the reply is unusable.

    Thinking is off here: reasoning tokens eat the same budget as the answer, and
    a truncated plan is useless.
    """
    instruction = {
        "role": "system",
        "content": (
            f"Reply with JSON only - no prose, no code fences. Shape: {schema_hint}. "
            "Keep every string short."
        ),
    }
    attempt_messages = [*messages, instruction]

    for attempt in (1, 2):
        reply = chat(
            attempt_messages,
            model=model,
            temperature=0.2 if attempt == 1 else 0.0,
            max_tokens=max_tokens,
            thinking=False,
        )
        try:
            return loads_lenient(reply.content)
        except ValueError:
            log.warning("Attempt %s did not yield JSON: %s", attempt, reply.content[:300])
            attempt_messages = [
                *messages,
                instruction,
                {"role": "system", "content": "Your last reply was not valid JSON. Be brief."},
            ]
    raise ValueError("Model did not return valid JSON after two attempts.")
