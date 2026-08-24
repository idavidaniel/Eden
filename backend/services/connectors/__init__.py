"""Choosing where a tool's writes actually land.

A company with no connection uses the built-in tracker and wiki, exactly as
before. Connect Jira and `create_ticket` starts creating Jira issues — same tool,
same prompt, different destination. Secrets are sealed with the existing
`crypto.seal`, and a connector that is misconfigured says so in a sentence the
model can act on rather than throwing a stack trace into a turn.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Connection

from .. import crypto
from .base import Connector, ConnectorError, Item
from .github import GitHubConnector
from .jira import JiraConnector

log = logging.getLogger(__name__)

PROVIDERS = {
    "builtin": {
        "label": "Built-in",
        "tools": ["tracker", "wiki", "chat", "documents"],
        "fields": [],
    },
    "github": {
        "label": "GitHub Issues",
        "tools": ["tracker"],
        "fields": [
            {"key": "repo", "label": "Repository (owner/name)", "required": True},
            {"key": "token", "label": "Personal access token", "secret": True, "required": True},
        ],
    },
    "jira": {
        "label": "Jira Cloud",
        "tools": ["tracker"],
        "fields": [
            {"key": "base_url", "label": "Site URL", "required": True},
            {"key": "email", "label": "Account email", "required": True},
            {"key": "project_key", "label": "Project key", "required": True},
            {"key": "api_token", "label": "API token", "secret": True, "required": True},
        ],
    },
}


def catalogue() -> list[dict]:
    return [{"provider": key, **value} for key, value in PROVIDERS.items()]


def connection_for(db: Session, company: Company, tool: str) -> Connection | None:
    return db.scalar(
        select(Connection).where(
            Connection.company_id == company.id,
            Connection.tool == tool,
            Connection.status == "connected",
        )
    )


def build(connection: Connection) -> Connector | None:
    """Instantiate a connector from a stored connection. None means built-in."""
    if not connection or connection.provider in {"builtin", ""}:
        return None
    config = dict(connection.config or {})
    secret = crypto.unseal(connection.secret_sealed) if connection.secret_sealed else ""

    if connection.provider == "github":
        return GitHubConnector(token=secret, repo=config.get("repo", ""))
    if connection.provider == "jira":
        return JiraConnector(
            base_url=connection.base_url or config.get("base_url", ""),
            email=config.get("email", ""),
            api_token=secret,
            project_key=config.get("project_key", ""),
        )
    raise ConnectorError(f"No connector is implemented for '{connection.provider}'.")


def tracker_for(db: Session, company: Company) -> Connector | None:
    """The external tracker for this company, if one is connected."""
    connection = connection_for(db, company, "tracker")
    if not connection:
        return None
    try:
        return build(connection)
    except ConnectorError as exc:
        log.warning("tracker connection for %s is unusable: %s", company.slug, exc)
        return None


def save(
    db: Session,
    company: Company,
    *,
    tool: str,
    provider: str,
    config: dict,
    secret: str | None = None,
    base_url: str | None = None,
) -> Connection:
    if provider not in PROVIDERS:
        raise ConnectorError(f"Unknown provider '{provider}'. Have: {', '.join(PROVIDERS)}")
    required = [
        field["key"]
        for field in PROVIDERS[provider]["fields"]
        if field.get("required") and not field.get("secret")
    ]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ConnectorError(f"{PROVIDERS[provider]['label']} needs: {', '.join(missing)}")

    row = db.scalar(
        select(Connection).where(Connection.company_id == company.id, Connection.tool == tool)
    ) or Connection(company_id=company.id, tool=tool)
    row.provider = provider
    row.config = {key: value for key, value in config.items() if key != "secret"}
    row.base_url = base_url or config.get("base_url")
    if secret:
        row.secret_sealed = crypto.seal(secret)
    row.status = "connected" if provider != "builtin" else "connected"
    db.add(row)
    db.flush()
    return row


def test(db: Session, connection: Connection) -> dict:
    try:
        connector = build(connection)
    except ConnectorError as exc:
        connection.status = "error"
        connection.config = {**(connection.config or {}), "last_error": str(exc)}
        db.add(connection)
        return {"ok": False, "error": str(exc)}
    if connector is None:
        return {"ok": True, "provider": "builtin", "note": "Nothing external to reach."}
    try:
        result = connector.test()
        connection.status = "connected"
        db.add(connection)
        return result
    except ConnectorError as exc:
        connection.status = "error"
        db.add(connection)
        return {"ok": False, "error": str(exc)}


__all__ = [
    "Connector",
    "ConnectorError",
    "Item",
    "PROVIDERS",
    "build",
    "catalogue",
    "connection_for",
    "save",
    "test",
    "tracker_for",
]
