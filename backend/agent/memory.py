"""Agent state schema.

Core memory is kept in named blocks (Letta/MemGPT style) that live outside the
message history: they are always in context, and they survive summarisation or
truncation of the transcript.
"""

import operator
from typing import Annotated, Literal, TypedDict

Role = Literal["user", "assistant", "system"]


class Message(TypedDict):
    role: Role
    content: str


class AgentState(TypedDict, total=False):
    # Conversation transcript. `operator.add` makes node returns append rather
    # than overwrite, so the checkpointer accumulates history per thread.
    messages: Annotated[list[Message], operator.add]

    # Core memory blocks, rewritten (not appended) on each turn.
    persona_block: str
    human_block: str

    # Transient: the reasoning trace for the most recent turn.
    current_reasoning: str


def compile_system_prompt(state: AgentState) -> str:
    """Render the core memory blocks into the system prompt for one turn."""
    persona = state.get("persona_block") or "You are a helpful AI employee."
    human = state.get("human_block") or "No specific details known about the user."
    return (
        "You are an AI employee operating inside a multi-tenant platform.\n\n"
        f"<persona>\n{persona.strip()}\n</persona>\n\n"
        f"<human>\n{human.strip()}\n</human>\n\n"
        "Answer the user's task directly and concisely."
    )


def user_message(content: str) -> Message:
    return {"role": "user", "content": content}


def assistant_message(content: str) -> Message:
    return {"role": "assistant", "content": content}
