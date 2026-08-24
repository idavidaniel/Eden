"""One small interface every tracker speaks, built-in or not.

The point is that `create_ticket` is the same tool whether this company's tracker
is the built-in board or a real Jira project. The employee does not learn a
different tool; the connection decides where the write lands.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Item:
    """A tracker item, in whatever system it lives."""

    key: str
    title: str
    status: str = ""
    assignee: str = ""
    url: str = ""
    kind: str = ""
    description: str = ""
    external_id: str = ""
    meta: dict = field(default_factory=dict)

    def line(self) -> str:
        who = self.assignee or "unassigned"
        return f"{self.key} [{self.status or '—'}] {self.title} — {who}"


class ConnectorError(RuntimeError):
    """Something went wrong out there. The message reaches the model."""


class Connector(Protocol):
    provider: str

    def test(self) -> dict: ...

    def list_items(
        self, *, status: str = "", assignee: str = "", limit: int = 50
    ) -> list[Item]: ...

    def create_item(
        self, *, title: str, description: str = "", kind: str = "task", assignee: str = ""
    ) -> Item: ...

    def update_item(
        self, *, key: str, status: str = "", assignee: str = "", result: str = ""
    ) -> Item: ...

    def comment(self, *, key: str, body: str) -> str: ...
