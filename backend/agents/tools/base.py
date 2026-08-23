"""Tool plumbing: what a tool is, and the context one runs inside."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from models import Artifact, Company, Employee, Project, Run, Source, WorkItem


@dataclass
class ToolResult:
    """What a tool hands back.

    A bare string was enough while every tool wrote to the database and nothing
    produced a deliverable. `artifacts` is how a tool says "this is the thing you
    were asked for"; `sources` is how a fetch makes a later citation checkable;
    and `error_hint` is the sentence that teaches the model how to recover — the
    same trick that turned `edit_file` from a coin flip into a reliable tool.
    """

    text: str = ""
    ok: bool = True
    artifacts: list[Artifact] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    error_hint: str = ""
    # Set by a tool that pulled in text from outside. The runtime uses it to
    # stop the same turn from also taking an action.
    untrusted: bool = False
    meta: dict = field(default_factory=dict)

    def for_model(self) -> str:
        body = self.text
        if self.error_hint:
            body = f"{body}\n\n{self.error_hint}".strip()
        return body

    def __str__(self) -> str:
        return self.for_model()


def failed(text: str, hint: str = "") -> ToolResult:
    return ToolResult(text=text, ok=False, error_hint=hint)


@dataclass
class ToolContext:
    """Everything a tool call needs to act as this employee, right now."""

    db: Session
    company: Company
    employee: Employee
    project: Project | None = None
    work_item: WorkItem | None = None
    run: Run | None = None
    task_id: str | None = None
    step_id: str | None = None
    # True once something in this turn pulled in text from outside the platform.
    tainted: bool = False

    @property
    def actor(self) -> str:
        return f"{self.employee.name} ({self.employee.title})"

    @property
    def git_author(self) -> tuple[str, str]:
        handle = self.employee.name.lower().replace(" ", ".")
        return self.employee.name, f"{handle}@{self.company.slug}.eden"


@dataclass
class Tool:
    name: str
    group: str
    description: str
    parameters: dict
    handler: Callable[..., Any]
    # Token scopes required to call it. `tools:<group>` is implied.
    scopes: list[str] = field(default_factory=list)
    # Changes something outside the platform, or cannot be undone inside it.
    destructive: bool = False
    # The company must have a Connection for this tool before it can be used.
    requires_connection: bool = False
    # Rough sense of what a call costs, for the interface and for budgeting.
    cost_hint: str = "cheap"
    # Reads only. A turn that has just pulled in text from outside may still call
    # these, but not the ones that change something.
    read_only: bool = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or list(properties.keys()),
    }


def string(description: str) -> dict:
    return {"type": "string", "description": description}
