"""Builds the HTTP (Streamable-HTTP) ASGI app for the networked transport.

Takes FastMCP's Streamable-HTTP Starlette app and wraps it with the auth + rate-limit ASGI
middleware. Auth is outermost so it runs first and stamps ``scope["state"]["client_id"]``,
which the rate limiter then keys on.
"""

from __future__ import annotations

from starlette.types import ASGIApp

from .auth import AuthMiddleware
from .ratelimit import RateLimitMiddleware
from .server import mcp


def build_app() -> ASGIApp:
    base = mcp.streamable_http_app()  # Starlette app (owns the session-manager lifespan)
    return AuthMiddleware(RateLimitMiddleware(base))
