"""Builds the HTTP (Streamable-HTTP) ASGI app for the networked transport.

Takes FastMCP's Streamable-HTTP Starlette app and wraps it with the auth + rate-limit ASGI
middleware. Auth is outermost so it runs first and stamps ``scope["state"]["client_id"]``,
which the rate limiter then keys on.
"""

from __future__ import annotations

from starlette.types import ASGIApp

from . import config
from .auth import AuthMiddleware
from .ratelimit import RateLimitMiddleware
from .server import mcp


def build_app() -> ASGIApp:
    base = mcp.streamable_http_app()  # Starlette app (owns the session-manager lifespan)
    app: ASGIApp = RateLimitMiddleware(base) if config.RATE_LIMIT_ENABLED else base
    app = AuthMiddleware(app)
    if config.TRACING_ENABLED:
        # Outermost: an inbound server span per request, the root of the distributed trace.
        from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware

        app = OpenTelemetryMiddleware(app, excluded_urls="healthz,metrics")
    return app
