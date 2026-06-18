"""Per-client token-bucket rate limiting for the HTTP transport.

Pure-ASGI middleware (streaming-safe). One in-memory bucket per client id (set by
:mod:`auth`), refilled at a steady rate up to a burst cap. Over-limit requests get 429 +
``Retry-After``. In-memory state is per-process; for a multi-instance deployment swap the
bucket store for Redis (already in the stack) — noted as the scale-out upgrade.
"""

from __future__ import annotations

import time

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import config


class _Bucket:
    __slots__ = ("tokens", "updated")

    def __init__(self, tokens: float, updated: float) -> None:
        self.tokens = tokens
        self.updated = updated


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        rps: float = config.RATE_LIMIT_RPS,
        burst: int = config.RATE_LIMIT_BURST,
    ) -> None:
        self.app = app
        self.rps = rps
        self.burst = burst
        self._buckets: dict[str, _Bucket] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in config.EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        client_id = scope.get("state", {}).get("client_id", "anonymous")
        if not self._allow(client_id):
            retry_after = max(1, int(1 / self.rps))
            await JSONResponse(
                {"error": "rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _allow(self, client_id: str) -> bool:
        """Refill the client's bucket by elapsed time, then try to spend one token.

        Single-event-loop access with no awaits between read and write, so no lock is needed.
        """
        now = time.monotonic()
        bucket = self._buckets.get(client_id)
        if bucket is None:
            self._buckets[client_id] = _Bucket(self.burst - 1, now)
            return True

        elapsed = now - bucket.updated
        bucket.tokens = min(self.burst, bucket.tokens + elapsed * self.rps)
        bucket.updated = now
        if bucket.tokens >= 1:
            bucket.tokens -= 1
            return True
        return False
