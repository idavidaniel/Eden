"""Tool plumbing: what a tool is, and the context one runs inside."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from models import Company, Employee, Project, Run, Ticket


@dataclass
class ToolContext:
    """Everything a tool call needs to act as this employee, right now."""

    db: Session
    company: Company
    employee: Employee
    project: Project | None = None
    ticket: Ticket | None = None
    run: Run | None = None

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
