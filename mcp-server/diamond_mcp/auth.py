"""API-key authentication for the HTTP transport.

Pure-ASGI middleware (not Starlette ``BaseHTTPMiddleware``) so it doesn't buffer the MCP
Streamable-HTTP streaming responses. Accepts a key via ``Authorization: Bearer <key>`` or
``X-API-Key``; compares its SHA-256 against the configured set. On success it stashes a stable
client id in the ASGI scope for the rate limiter and metrics. The stdio transport never goes
through here — it's the trusted local path.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in config.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})

        if not config.AUTH_ENABLED:
            # Auth disabled (no keys configured): identify clients by IP for rate limiting.
            state["client_id"] = _client_ip(scope)
            await self.app(scope, receive, send)
            return

        key = _extract_key(Headers(scope=scope))
        if key is None or config._hash_key(key) not in config.API_KEY_HASHES:
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return

        # Stable, non-secret client id: first 12 chars of the key hash.
        state["client_id"] = config._hash_key(key)[:12]
        await self.app(scope, receive, send)


def _extract_key(headers: Headers) -> str | None:
    auth = headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    api_key = headers.get("x-api-key")
    return api_key.strip() if api_key else None


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "anonymous"
