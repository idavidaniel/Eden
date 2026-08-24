"""GitHub Issues as a company's tracker."""

import httpx

from .base import Connector, ConnectorError, Item

API = "https://api.github.com"
TIMEOUT = 20.0

# GitHub has open and closed. Everything else is a label, which is how a board
# with six columns survives the round trip.
STATUS_LABELS = {"todo", "in_progress", "in_review", "blocked", "backlog"}


class GitHubConnector(Connector):
    provider = "github"

    def __init__(self, token: str, repo: str, base_url: str = API):
        if "/" not in (repo or ""):
            raise ConnectorError("GitHub needs a repo as 'owner/name'.")
        self.token = token
        self.repo = repo
        self.base_url = (base_url or API).rstrip("/")

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=TIMEOUT,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _call(self, method: str, path: str, **kwargs) -> dict | list:
        with self._client() as client:
            response = client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code == 401:
            raise ConnectorError("GitHub rejected the token.")
        if response.status_code == 403:
            raise ConnectorError("GitHub refused: rate limit, or the token lacks issue scope.")
        if response.status_code == 404:
            raise ConnectorError(f"GitHub has no {self.repo}, or the token cannot see it.")
        if response.status_code >= 400:
            raise ConnectorError(f"GitHub returned {response.status_code}: {response.text[:200]}")
        return response.json()

    def test(self) -> dict:
        data = self._call("GET", f"/repos/{self.repo}")
        return {
            "ok": True,
            "repo": data.get("full_name"),
            "issues_enabled": data.get("has_issues", False),
            "open_issues": data.get("open_issues_count", 0),
        }

    def list_items(self, *, status: str = "", assignee: str = "", limit: int = 50) -> list[Item]:
        params: dict = {"per_page": min(limit, 100), "state": "all"}
        if status == "done":
            params["state"] = "closed"
        elif status:
            params["state"] = "open"
            params["labels"] = status
        if assignee:
            params["assignee"] = assignee
        data = self._call("GET", f"/repos/{self.repo}/issues", params=params)
        return [self._item(row) for row in data if "pull_request" not in row]

    def create_item(
        self, *, title: str, description: str = "", kind: str = "task", assignee: str = ""
    ) -> Item:
        payload: dict = {"title": title, "body": description, "labels": [kind] if kind else []}
        if assignee:
            payload["assignees"] = [assignee]
        return self._item(self._call("POST", f"/repos/{self.repo}/issues", json=payload))

    def update_item(
        self, *, key: str, status: str = "", assignee: str = "", result: str = ""
    ) -> Item:
        number = _number(key)
        payload: dict = {}
        if status == "done":
            payload["state"] = "closed"
        elif status in STATUS_LABELS:
            payload["state"] = "open"
            payload["labels"] = [status]
        if assignee:
            payload["assignees"] = [assignee]
        item = self._item(self._call("PATCH", f"/repos/{self.repo}/issues/{number}", json=payload))
        if result:
            self.comment(key=key, body=f"Result: {result}")
        return item

    def comment(self, *, key: str, body: str) -> str:
        self._call(
            "POST", f"/repos/{self.repo}/issues/{_number(key)}/comments", json={"body": body}
        )
        return f"Commented on {key}."

    def _item(self, row: dict) -> Item:
        labels = [label["name"] for label in row.get("labels", []) if isinstance(label, dict)]
        status = next((label for label in labels if label in STATUS_LABELS), None)
        return Item(
            key=f"#{row['number']}",
            title=row.get("title", ""),
            status=status or ("done" if row.get("state") == "closed" else "todo"),
            assignee=", ".join(user["login"] for user in row.get("assignees", [])),
            url=row.get("html_url", ""),
            kind=next((label for label in labels if label not in STATUS_LABELS), "task"),
            description=(row.get("body") or "")[:4000],
            external_id=str(row.get("number")),
        )


def _number(key: str) -> str:
    digits = "".join(character for character in str(key) if character.isdigit())
    if not digits:
        raise ConnectorError(f"'{key}' is not a GitHub issue number.")
    return digits
