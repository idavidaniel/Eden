"""Jira Cloud as a company's tracker."""

import base64

import httpx

from .base import Connector, ConnectorError, Item

TIMEOUT = 25.0


class JiraConnector(Connector):
    provider = "jira"

    def __init__(self, base_url: str, email: str, api_token: str, project_key: str):
        if not base_url:
            raise ConnectorError("Jira needs a site URL, e.g. https://acme.atlassian.net")
        if not project_key:
            raise ConnectorError("Jira needs a project key, e.g. ENG.")
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key.upper()
        credentials = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _call(self, method: str, path: str, **kwargs):
        with httpx.Client(timeout=TIMEOUT, headers=self.headers) as client:
            response = client.request(method, f"{self.base_url}{path}", **kwargs)
        if response.status_code == 401:
            raise ConnectorError("Jira rejected the email and API token.")
        if response.status_code == 403:
            raise ConnectorError("Jira refused: that account cannot do this in this project.")
        if response.status_code == 404:
            raise ConnectorError(f"Jira has no such resource: {path}")
        if response.status_code >= 400:
            raise ConnectorError(f"Jira returned {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}

    def test(self) -> dict:
        data = self._call("GET", f"/rest/api/3/project/{self.project_key}")
        return {"ok": True, "project": data.get("name"), "key": data.get("key")}

    def list_items(self, *, status: str = "", assignee: str = "", limit: int = 50) -> list[Item]:
        jql = [f"project = {self.project_key}"]
        if status:
            jql.append(f'status = "{_jira_status(status)}"')
        if assignee:
            jql.append(f'assignee = "{assignee}"')
        data = self._call(
            "POST",
            "/rest/api/3/search",
            json={
                "jql": " AND ".join(jql) + " ORDER BY created DESC",
                "maxResults": min(limit, 100),
                "fields": ["summary", "status", "assignee", "issuetype", "description"],
            },
        )
        return [self._item(row) for row in data.get("issues", [])]

    def create_item(
        self, *, title: str, description: str = "", kind: str = "task", assignee: str = ""
    ) -> Item:
        fields: dict = {
            "project": {"key": self.project_key},
            "summary": title[:250],
            "issuetype": {"name": _jira_type(kind)},
        }
        if description:
            fields["description"] = _document(description)
        created = self._call("POST", "/rest/api/3/issue", json={"fields": fields})
        key = created.get("key", "")
        if assignee:
            self._assign(key, assignee)
        return Item(
            key=key,
            title=title,
            status="To Do",
            url=f"{self.base_url}/browse/{key}",
            kind=kind,
            external_id=created.get("id", ""),
        )

    def update_item(
        self, *, key: str, status: str = "", assignee: str = "", result: str = ""
    ) -> Item:
        if status:
            self._transition(key, _jira_status(status))
        if assignee:
            self._assign(key, assignee)
        if result:
            self.comment(key=key, body=f"Result: {result}")
        data = self._call("GET", f"/rest/api/3/issue/{key}")
        return self._item(data)

    def comment(self, *, key: str, body: str) -> str:
        self._call("POST", f"/rest/api/3/issue/{key}/comment", json={"body": _document(body)})
        return f"Commented on {key}."

    def _transition(self, key: str, target: str) -> None:
        available = self._call("GET", f"/rest/api/3/issue/{key}/transitions")
        match = next(
            (
                transition
                for transition in available.get("transitions", [])
                if transition["to"]["name"].lower() == target.lower()
                or transition["name"].lower() == target.lower()
            ),
            None,
        )
        if not match:
            names = ", ".join(t["name"] for t in available.get("transitions", []))
            raise ConnectorError(
                f"Jira will not move {key} to '{target}'. Available here: {names or 'none'}."
            )
        self._call(
            "POST", f"/rest/api/3/issue/{key}/transitions", json={"transition": {"id": match["id"]}}
        )

    def _assign(self, key: str, name: str) -> None:
        found = self._call(
            "GET", "/rest/api/3/user/search", params={"query": name, "maxResults": 1}
        )
        if not found:
            raise ConnectorError(f"Jira has no user matching '{name}'.")
        self._call(
            "PUT", f"/rest/api/3/issue/{key}/assignee", json={"accountId": found[0]["accountId"]}
        )

    def _item(self, row: dict) -> Item:
        fields = row.get("fields", {})
        assignee = (fields.get("assignee") or {}).get("displayName", "")
        return Item(
            key=row.get("key", ""),
            title=fields.get("summary", ""),
            status=(fields.get("status") or {}).get("name", ""),
            assignee=assignee,
            url=f"{self.base_url}/browse/{row.get('key', '')}",
            kind=(fields.get("issuetype") or {}).get("name", "Task"),
            external_id=row.get("id", ""),
        )


# The built-in board and Jira do not agree on names; translate rather than leak.
STATUS_MAP = {
    "todo": "To Do",
    "backlog": "To Do",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done",
    "blocked": "Blocked",
}
TYPE_MAP = {"bug": "Bug", "story": "Story", "epic": "Epic", "chore": "Task", "task": "Task"}


def _jira_status(status: str) -> str:
    return STATUS_MAP.get(status, status)


def _jira_type(kind: str) -> str:
    return TYPE_MAP.get(kind, "Task")


def _document(text: str) -> dict:
    """Jira's rich-text format. Plain paragraphs are enough and always valid."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line or " "}]}
            for line in text.split("\n")[:200]
        ],
    }
