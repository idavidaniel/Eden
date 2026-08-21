"""Stateless JSON-RPC 2.0 endpoint implementing the MCP server role.

Stateless means no session is established: every request carries its own
context, so any replica can serve any call.
"""

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from config import get_settings

from . import tools

router = APIRouter(prefix="/mcp", tags=["MCP"])

METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

SERVER_INFO = {"name": "eaas-integration-registry", "version": "0.1.0"}


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _result(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


@router.post("")
async def mcp_endpoint(req: JSONRPCRequest):
    if req.method == "initialize":
        return _result(
            req.id,
            {
                "protocolVersion": get_settings().mcp_protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )

    if req.method == "ping":
        return _result(req.id, {})

    if req.method == "tools/list":
        return _result(req.id, {"tools": tools.list_definitions()})

    if req.method == "tools/call":
        name = req.params.get("name")
        if not name:
            return _error(req.id, INVALID_PARAMS, "Missing 'name'.")
        try:
            text = tools.call(name, req.params.get("arguments", {}))
        except KeyError:
            return _error(req.id, METHOD_NOT_FOUND, f"Unknown tool: {name}")
        except Exception as exc:
            # Tool failures are reported in-band so the model can react to them.
            return _result(
                req.id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return _result(req.id, {"content": [{"type": "text", "text": text}], "isError": False})

    return _error(req.id, METHOD_NOT_FOUND, f"Unknown method: {req.method}")
