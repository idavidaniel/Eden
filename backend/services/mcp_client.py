"""Calling other MCP servers.

We were already an MCP server; this is the client half. Tools discovered from a
registered server appear to an employee alongside the built-in ones, prefixed
with the server's name so two servers can both have a `search`.

Failure is isolated on purpose: a server that is down, slow or wrong degrades to
"that tool is unavailable right now" inside one tool result. It never breaks a
turn, because an agent losing its whole turn to somebody else's outage is a
worse failure than the outage.
"""

import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from models import Company, McpServer

from . import crypto

log = logging.getLogger(__name__)

TIMEOUT = 25.0
DISCOVERY_TIMEOUT = 12.0
NAME_SEPARATOR = "__"


class McpError(RuntimeError):
    pass


def _headers(server: McpServer) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Mcp-Protocol-Version": server.protocol_version
        or get_settings().mcp_protocol_version,
    }
    if server.auth_sealed:
        headers["Authorization"] = f"Bearer {crypto.unseal(server.auth_sealed)}"
    return headers


def _rpc(server: McpServer, method: str, params: dict | None = None, timeout: float = TIMEOUT):
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or {},
    }
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(server.url, json=payload, headers=_headers(server))
    except httpx.HTTPError as exc:
        raise McpError(f"{server.name} did not answer: {exc}") from exc

    if response.status_code == 401:
        raise McpError(f"{server.name} rejected the credentials.")
    if response.status_code >= 400:
        raise McpError(f"{server.name} returned {response.status_code}: {response.text[:200]}")

    body = response.json()
    if "error" in body:
        raise McpError(f"{server.name}: {body['error'].get('message', 'unknown error')}")
    return body.get("result", {})


def register(
    db: Session,
    company: Company,
    *,
    name: str,
    url: str,
    token: str | None = None,
    protocol_version: str = "",
) -> McpServer:
    row = db.scalar(
        select(McpServer).where(McpServer.company_id == company.id, McpServer.name == name)
    ) or McpServer(company_id=company.id, name=name)
    row.url = url
    row.protocol_version = protocol_version or get_settings().mcp_protocol_version
    if token:
        row.auth_sealed = crypto.seal(token)
    row.enabled = True
    db.add(row)
    db.flush()
    discover(db, row)
    return row


def discover(db: Session, server: McpServer) -> dict:
    """Handshake and cache the tool list, so a turn does not pay for discovery."""
    try:
        initialised = _rpc(
            server,
            "initialize",
            {
                "protocolVersion": server.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "eden", "version": "2.0.0"},
            },
            timeout=DISCOVERY_TIMEOUT,
        )
        listed = _rpc(server, "tools/list", timeout=DISCOVERY_TIMEOUT)
    except McpError as exc:
        server.status = "error"
        server.last_error = str(exc)[:1000]
        server.last_checked_at = datetime.now(UTC)
        db.add(server)
        return {"ok": False, "error": str(exc)}

    server.tools = [
        {
            "name": tool.get("name", ""),
            "description": (tool.get("description") or "")[:600],
            "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            "read_only": bool((tool.get("annotations") or {}).get("readOnlyHint")),
        }
        for tool in listed.get("tools", [])
        if tool.get("name")
    ]
    server.status = "connected"
    server.last_error = None
    server.last_checked_at = datetime.now(UTC)
    db.add(server)
    return {
        "ok": True,
        "server": initialised.get("serverInfo", {}),
        "tools": [tool["name"] for tool in server.tools],
    }


def servers_for(db: Session, company: Company) -> list[McpServer]:
    return list(
        db.scalars(
            select(McpServer).where(
                McpServer.company_id == company.id, McpServer.enabled.is_(True)
            )
        )
    )


def tools_for(db: Session, company: Company) -> list:
    """Cached remote tools, as `Tool` objects the registry can hand to a model."""
    from agents.tools.base import Tool, ToolResult, failed

    built: list = []
    for server in servers_for(db, company):
        if server.status != "connected":
            continue
        for definition in server.tools or []:
            built.append(_wrap(server, definition, Tool, ToolResult, failed))
    return built


def _wrap(server: McpServer, definition: dict, Tool, ToolResult, failed):  # noqa: N803
    remote_name = definition["name"]
    local_name = f"{_slug(server.name)}{NAME_SEPARATOR}{remote_name}"[:64]

    def handler(ctx, **arguments):
        db = ctx.db
        row = db.get(McpServer, server.id)
        if not row or not row.enabled:
            return failed(
                f"{server.name} is no longer connected.",
                "Carry on with the tools you do have.",
            )
        try:
            result = _rpc(row, "tools/call", {"name": remote_name, "arguments": arguments})
        except McpError as exc:
            row.status = "error"
            row.last_error = str(exc)[:1000]
            db.add(row)
            return failed(
                f"{server.name} is unavailable: {exc}",
                "Do the part that does not need it and say what you could not do.",
            )
        text = "\n".join(
            part.get("text", "")
            for part in result.get("content", [])
            if part.get("type") == "text"
        )
        return ToolResult(
            text=text or "(the server returned nothing)",
            ok=not result.get("isError"),
            # Anything from another server is outside text, and treated as such.
            untrusted=True,
        )

    return Tool(
        name=local_name,
        group=f"mcp:{_slug(server.name)}",
        description=f"[{server.name}] {definition.get('description', '')}",
        parameters=definition.get("inputSchema") or {"type": "object", "properties": {}},
        handler=handler,
        read_only=definition.get("read_only", False),
        requires_connection=False,
        cost_hint="slow",
    )


def _slug(name: str) -> str:
    return "".join(
        character if character.isalnum() else "_" for character in (name or "server").lower()
    ).strip("_")[:24]
