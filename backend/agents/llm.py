"""Model client: one place that knows how to talk to the provider.

Supports plain completions, streaming, and OpenAI-style tool calling, which is
what the employee loop runs on.
"""

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from config import get_settings
from services import usage

log = logging.getLogger(__name__)

# Room for the structured answer itself, on top of the reasoning budget. A plan
# with eight items and acceptance criteria runs to about 2,300 tokens.
STRUCTURED_ANSWER_TOKENS = 4000


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


# A rate limit or a bad gateway is the provider having a moment, not the work
# being wrong. A run that dies on one loses every item after it, so these are
# waited out rather than raised. Anything else — a bad request, a refused key —
# is a real answer and comes straight back.
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 4
BACKOFF_SECONDS = 3.0


def _retry_after(error: Exception, attempt: int) -> float:
    """Honour the provider's own Retry-After when it sends one."""
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    for key in ("retry-after", "Retry-After"):
        if key in headers:
            try:
                return min(float(headers[key]), 60.0)
            except (TypeError, ValueError):
                break
    # Exponential, so a provider under load is not hammered by every worker.
    return BACKOFF_SECONDS * (2 ** (attempt - 1))


def _worth_retrying(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(
        getattr(error, "response", None), "status_code", None
    )
    return status in RETRY_STATUSES


def complete(kind: str = "chat", **kwargs):
    """One completion call, timed and booked against whoever asked for it.

    Every model call in the platform goes through here so that no spend is
    invisible — including the ones made by evaluators and the reflection pass.

    Also the one place that waits out a rate limit. A single 429 used to end a
    whole run mid-execution, taking every unstarted item with it.
    """
    model = kwargs.get("model") or get_settings().model
    started = time.perf_counter()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = get_client().chat.completions.create(**kwargs)
            break
        except Exception as error:
            if attempt < MAX_ATTEMPTS and _worth_retrying(error):
                delay = _retry_after(error, attempt)
                log.warning(
                    "%s: %s — waiting %.0fs and trying again (%s/%s)",
                    model,
                    error,
                    delay,
                    attempt,
                    MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue
            usage.record(
                model,
                kind=kind,
                latency_ms=int((time.perf_counter() - started) * 1000),
                ok=False,
            )
            raise
    if kwargs.get("stream"):
        # Token counts arrive in the final chunk; the consumer books them.
        return completion
    counts = getattr(completion, "usage", None)
    usage.record(
        model,
        kind=kind,
        prompt_tokens=getattr(counts, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(counts, "completion_tokens", 0) or 0,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return completion


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

    completion = complete("chat", **kwargs)
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
    chosen = model or settings.model
    started = time.perf_counter()
    completion = complete(
        "stream",
        model=chosen,
        messages=messages,
        temperature=0.7,
        max_tokens=settings.max_tokens,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": settings.reasoning_budget,
        },
        stream=True,
        stream_options={"include_usage": True},
    )
    counts = None
    for chunk in completion:
        counts = getattr(chunk, "usage", None) or counts
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            yield "reasoning", reasoning
        if delta.content:
            yield "content", delta.content

    usage.record(
        chosen,
        kind="stream",
        prompt_tokens=getattr(counts, "prompt_tokens", 0) or 0,
        completion_tokens=getattr(counts, "completion_tokens", 0) or 0,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def structured_call(
    messages: list[dict],
    name: str,
    description: str,
    parameters: dict,
    model: str | None = None,
    max_tokens: int | None = None,
) -> Any:
    """Get structured data by forcing a tool call.

    More reliable than asking for JSON in prose: reasoning models narrate before
    answering, and the narration is what breaks a JSON parse. A forced function
    call has nowhere to put prose.

    Reasoning tokens count against `max_tokens`, which is the trap here. This
    used to ask for a plan in 3000 tokens with thinking left unbounded; the
    model spent all 3000 thinking, emitted no call, and the run died with
    "Model did not call submit_plan" — which says nothing about what went wrong.

    So: enough room for the thinking *and* the answer, a bounded reasoning
    budget, and if it still does not call, one retry with thinking switched off.
    A forced tool call does not need narration to produce, and the retry both
    succeeds and costs less than the attempt that failed.
    """
    settings = get_settings()
    tools = [
        {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": parameters},
        }
    ]
    choice = {"type": "function", "function": {"name": name}}
    # The budget has to leave room for the answer after the thinking, or the
    # model stops the moment it finishes reasoning and returns nothing at all.
    ceiling = max_tokens or (settings.reasoning_budget + STRUCTURED_ANSWER_TOKENS)

    attempts = [
        {
            "max_tokens": ceiling,
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": settings.reasoning_budget,
            },
        },
        # No thinking. Deterministic, cheaper, and the only thing that helps
        # when the first attempt ran out of room rather than out of ideas.
        {
            "max_tokens": ceiling,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    ]

    last = ""
    for index, options in enumerate(attempts):
        completion = complete(
            "structured",
            model=model or settings.model,
            messages=messages,
            temperature=0.3,
            tools=tools,
            tool_choice=choice,
            **options,
        )
        choice_out = completion.choices[0]
        calls = choice_out.message.tool_calls or []
        if calls:
            if index:
                log.info("%s needed a second attempt with thinking off", name)
            return loads_lenient(calls[0].function.arguments or "{}")

        last = choice_out.finish_reason or "unknown"
        log.warning(
            "%s produced no tool call (finish_reason=%s, completion_tokens=%s)",
            name,
            last,
            getattr(getattr(completion, "usage", None), "completion_tokens", "?"),
        )

    raise ValueError(
        f"The model would not produce a {name}, even with thinking switched off "
        f"(it stopped because: {last}). The request may be too large for the "
        "model's context, or the schema too complex for it to fill in."
    )


def embed(
    texts: list[str], input_type: str = "passage", model: str | None = None
) -> list[list[float]]:
    """Embed a batch of texts.

    Batch, always. Seven sequential single-item calls timed out at two minutes
    against this endpoint; the same seven in one request come back in under a
    second. `input_type` matters: this model is asymmetric, so a stored memory is
    a "passage" and a lookup is a "query", and mixing them costs real accuracy.
    """
    if not texts:
        return []
    settings = get_settings()
    chosen = model or settings.embedding_model
    started = time.perf_counter()
    try:
        response = get_client().embeddings.create(
            model=chosen,
            input=texts,
            extra_body={"input_type": input_type, "truncate": "END"},
        )
    except Exception:
        usage.record(
            chosen, kind="embed", latency_ms=int((time.perf_counter() - started) * 1000), ok=False
        )
        raise
    counts = getattr(response, "usage", None)
    usage.record(
        chosen,
        kind="embed",
        prompt_tokens=getattr(counts, "prompt_tokens", 0) or 0,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )
    return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]


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
