"""Authorisation for the MCP surface.

This used to check that a bearer token was *present*. It now checks that one is
*valid*: the token is looked up, verified against its stored digest, and resolved
to the employee it belongs to. That employee is who the call acts as — there is
no longer an `employee_id` argument to spoof, because identity comes from the
credential rather than from the request body.
"""

import logging

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings

log = logging.getLogger(__name__)

# Advertised on a 401 as the MCP specification requires.
PRM_URI = "/.well-known/oauth-protected-resource"

UNAUTHORISED_HINT = (
    "Send an employee's agent token: Authorization: Bearer edn_<prefix>_<secret>. "
    "Mint one on that employee's page, or with POST /agents/{id}/tokens."
)


def _error(status: int, code: int, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}},
        headers=headers or {},
    )


class AgentTokenMiddleware(BaseHTTPMiddleware):
    """Resolves the caller once, and hands the request the employee it belongs to."""

    async def dispatch(self, request, call_next):
        settings = get_settings()

        if request.method == "OPTIONS" or not request.url.path.startswith("/mcp"):
            return await call_next(request)

        version = request.headers.get("Mcp-Protocol-Version")
        if version != settings.mcp_protocol_version:
            return _error(
                400,
                -32600,
                f"Unsupported MCP protocol version. Expected {settings.mcp_protocol_version}.",
            )

        if not settings.require_mcp_auth:
            request.state.agent = None
            return await call_next(request)

        header = request.headers.get("Authorization", "")
        if not header.lower().startswith("bearer ") or not header[7:].strip():
            return _error(
                401,
                -32001,
                f"Unauthorized. {UNAUTHORISED_HINT}",
                {"WWW-Authenticate": f'Bearer realm="mcp", resource_metadata="{PRM_URI}"'},
            )

        from db import session
        from models import Employee
        from services import tokens

        db = session()
        try:
            row = tokens.verify(db, header[7:].strip())
            if not row:
                return _error(
                    401,
                    -32001,
                    "That token is not valid, has expired, or has been revoked.",
                    {"WWW-Authenticate": 'Bearer realm="mcp"'},
                )
            employee = db.get(Employee, row.employee_id)
            if not employee or not employee.api_enabled:
                return _error(403, -32002, "That employee's API access is switched off.")
            if employee.company.halted:
                return _error(
                    409,
                    -32003,
                    f"{employee.company.name} is halted: "
                    f"{employee.company.halt_reason or 'stopped by the operator'}",
                )
            request.state.agent = {
                "employee_id": employee.id,
                "company_id": employee.company_id,
                "token_id": row.id,
                "token_name": row.name,
                "scopes": list(row.scopes or []),
            }
            db.commit()
        finally:
            db.close()

        return await call_next(request)


# Kept under the old name so nothing that imports it breaks; it is no longer a mock.
MockOAuthMiddleware = AgentTokenMiddleware
