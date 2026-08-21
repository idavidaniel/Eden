"""Enterprise-Managed Authorization (EMA) gate for the MCP surface.

This is a stand-in for a real OAuth 2.1 resource server: it enforces the
protocol-version header and the presence of a bearer token, and advertises the
protected-resource metadata URI on 401 as the MCP spec requires. Token
signatures are NOT verified - wire this to your IdP's JWKS before production.
"""

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings

PRM_URI = "https://auth.example.com/.well-known/oauth-protected-resource"


class MockOAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        settings = get_settings()

        if request.method == "OPTIONS" or not request.url.path.startswith("/mcp"):
            return await call_next(request)

        version = request.headers.get("Mcp-Protocol-Version")
        if version != settings.mcp_protocol_version:
            return JSONResponse(
                status_code=400,
                content={
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": (
                            "Unsupported MCP protocol version. Expected "
                            f"{settings.mcp_protocol_version}."
                        ),
                    },
                },
            )

        if settings.require_mcp_auth:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer ") or not auth_header[7:].strip():
                return JSONResponse(
                    status_code=401,
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32001, "message": "Unauthorized"},
                    },
                    headers={
                        "WWW-Authenticate": (f'Bearer realm="mcp", resource_metadata="{PRM_URI}"')
                    },
                )

        return await call_next(request)
