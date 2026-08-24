"""What a company is wired to: connectors, MCP servers, and the egress policy.

One page's worth of API. The egress policy is here rather than under settings
because it belongs with the other decisions about what agents can reach.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from db import get_db
from models import Connection, McpServer
from services import connectors, mcp_client, packs, runners
from services import web as web_service
from services.roles import TOOLS

from .companies import get_company

router = APIRouter(tags=["connections"])


class ConnectionIn(BaseModel):
    tool: str
    provider: str
    config: dict = {}
    secret: str | None = None
    base_url: str | None = None


class McpServerIn(BaseModel):
    name: str
    url: str
    token: str | None = None
    protocol_version: str = ""


class EgressIn(BaseModel):
    allow: list[str] | None = None
    open: bool | None = None


@router.get("/connections/catalogue")
def catalogue():
    """Everything a company can connect, and what each one needs."""
    return {
        "providers": connectors.catalogue(),
        "tools": TOOLS,
        "runners": runners.status(),
    }


@router.get("/companies/{company_id}/connections")
def list_connections(company_id: str, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    rows = list(
        db.scalars(select(Connection).where(Connection.company_id == company.id))
    )
    servers = list(
        db.scalars(select(McpServer).where(McpServer.company_id == company.id))
    )
    return {
        "connections": [
            {
                "id": row.id,
                "tool": row.tool,
                "provider": row.provider,
                "base_url": row.base_url,
                # Never the secret; whether one is set is all anyone needs.
                "config": {k: v for k, v in (row.config or {}).items() if k != "secret"},
                "has_secret": bool(row.secret_sealed),
                "status": row.status,
            }
            for row in rows
        ],
        "mcp_servers": [
            {
                "id": server.id,
                "name": server.name,
                "url": server.url,
                "status": server.status,
                "enabled": server.enabled,
                "last_error": server.last_error,
                "tools": [tool["name"] for tool in server.tools or []],
                "last_checked_at": server.last_checked_at.isoformat()
                if server.last_checked_at
                else None,
            }
            for server in servers
        ],
        "egress": {
            "open": web_service.egress_open(company),
            "allow": web_service.allowlist_for(company),
            "default": web_service.DEFAULT_ALLOWLIST,
        },
    }


@router.put("/companies/{company_id}/connections")
def upsert_connection(company_id: str, payload: ConnectionIn, db: Session = Depends(get_db)):
    company = get_company(db, company_id)
    try:
        row = connectors.save(
            db,
            company,
            tool=payload.tool,
            provider=payload.provider,
            config=payload.config,
            secret=payload.secret,
            base_url=payload.base_url,
        )
        result = connectors.test(db, row)
    except connectors.ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"tool": row.tool, "provider": row.provider, "status": row.status, "test": result}


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: str, db: Session = Depends(get_db)):
    row = db.get(Connection, connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such connection.")
    result = connectors.test(db, row)
    db.commit()
    return result


@router.delete("/connections/{connection_id}", status_code=204)
def delete_connection(connection_id: str, db: Session = Depends(get_db)):
    row = db.get(Connection, connection_id)
    if not row:
        raise HTTPException(status_code=404, detail="No such connection.")
    db.delete(row)
    db.commit()


@router.post("/companies/{company_id}/mcp-servers", status_code=201)
def add_mcp_server(company_id: str, payload: McpServerIn, db: Session = Depends(get_db)):
    """Register an MCP server. Its tools appear alongside the built-in ones."""
    company = get_company(db, company_id)
    server = mcp_client.register(
        db,
        company,
        name=payload.name,
        url=payload.url,
        token=payload.token,
        protocol_version=payload.protocol_version,
    )
    db.commit()
    return {
        "id": server.id,
        "name": server.name,
        "status": server.status,
        "tools": [tool["name"] for tool in server.tools or []],
        "last_error": server.last_error,
        "grant_with": f"mcp:{mcp_client._slug(server.name)}",
    }


@router.post("/mcp-servers/{server_id}/refresh")
def refresh_mcp_server(server_id: str, db: Session = Depends(get_db)):
    server = db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="No such server.")
    result = mcp_client.discover(db, server)
    db.commit()
    return result


@router.delete("/mcp-servers/{server_id}", status_code=204)
def remove_mcp_server(server_id: str, db: Session = Depends(get_db)):
    server = db.get(McpServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="No such server.")
    db.delete(server)
    db.commit()


@router.put("/companies/{company_id}/egress")
def set_egress(company_id: str, payload: EgressIn, db: Session = Depends(get_db)):
    """Which hosts this company's agents may reach. Default-deny unless opened."""
    company = get_company(db, company_id)
    settings = dict(company.settings or {})
    if payload.allow is not None:
        settings["egress_allow"] = [host.strip() for host in payload.allow if host.strip()]
    if payload.open is not None:
        settings["egress_open"] = bool(payload.open)
    company.settings = settings
    db.add(company)
    db.commit()
    return {
        "open": web_service.egress_open(company),
        "allow": web_service.allowlist_for(company),
        "warning": (
            "Open egress means an agent can fetch anything, including a page written "
            "to manipulate it. Fetched text is still treated as data and still cannot "
            "trigger an action in the same turn, but the allow-list is the stronger guard."
            if web_service.egress_open(company)
            else None
        ),
    }


@router.get("/companies/{company_id}/pack")
def read_pack(company_id: str, db: Session = Depends(get_db)):
    """The industry shape of this company: roles, deliverables, checks."""
    from models import ArtifactKind, Check, Role

    from . import serializers

    company = get_company(db, company_id)
    pack = packs.get_pack(company.pack_key)
    return {
        "key": pack.key,
        "name": pack.name,
        "description": pack.description,
        "departments": company.departments or pack.departments,
        "work_item_kinds": packs.kinds_for(company),
        "roles": [
            serializers.role(row)
            for row in db.scalars(
                select(Role).where(Role.company_id == company.id).order_by(Role.position)
            )
        ],
        "artifact_kinds": [
            {
                "key": row.key,
                "name": row.name,
                "storage": row.storage,
                "renderer": row.renderer,
                "default_checks": row.default_checks or [],
                "description": row.description,
            }
            for row in db.scalars(
                select(ArtifactKind).where(ArtifactKind.company_id == company.id)
            )
        ],
        "checks": [
            serializers.check(row)
            for row in db.scalars(
                select(Check).where(
                    Check.company_id == company.id,
                    Check.project_id.is_(None),
                    Check.work_item_id.is_(None),
                )
            )
        ],
    }


@router.post("/companies/{company_id}/pack/reapply")
def reapply_pack(company_id: str, pack_key: str | None = None, db: Session = Depends(get_db)):
    """Re-read the pack from disk. Existing rows are updated, not duplicated."""
    company = get_company(db, company_id)
    packs.all_packs.cache_clear()
    try:
        pack = packs.apply_pack(db, company, pack_key)
    except packs.PackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"pack": pack.key, "roles": len(pack.roles), "checks": len(pack.checks)}
