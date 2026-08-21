"""Thin wrapper around the NVIDIA-hosted Nemotron endpoint.

The model emits its chain of thought on a separate `reasoning_content` delta,
so every helper here keeps reasoning and answer text apart.
"""

from collections.abc import Iterator
from typing import Literal

from openai import OpenAI

from config import get_settings

Event = tuple[Literal["reasoning", "content"], str]


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is available for the model provider."""


def get_client() -> OpenAI:
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise LLMNotConfigured(
            "NVIDIA_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return OpenAI(base_url=settings.nvidia_base_url, api_key=settings.nvidia_api_key)


def stream_chat(messages: list[dict]) -> Iterator[Event]:
    """Yield ("reasoning" | "content", delta) tuples as the model produces them.

    `messages` is a standard chat transcript: [{"role": ..., "content": ...}].
    """
    settings = get_settings()
    completion = get_client().chat.completions.create(
        model=settings.model,
        messages=messages,
        temperature=1,
        top_p=0.95,
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


def complete(messages: list[dict]) -> tuple[str, str]:
    """Collect a full response. Returns (reasoning_text, content_text)."""
    reasoning_text, content_text = [], []
    for kind, delta in stream_chat(messages):
        (reasoning_text if kind == "reasoning" else content_text).append(delta)
    return "".join(reasoning_text), "".join(content_text)


def call_nemotron(prompt: str, system_prompt: str | None = None) -> tuple[str, str]:
    """One-shot convenience wrapper around `complete`."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return complete(messages)
