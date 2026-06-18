"""A small circuit breaker for the upstream API.

After ``fail_max`` consecutive failures the breaker opens and calls fail fast for
``reset_seconds``; then it half-opens to let one probe through. A success closes it; a failure
re-opens it. Single-event-loop access (no awaits in the hot path), so no lock is needed.
"""

from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(self, fail_max: int, reset_seconds: float) -> None:
        self.fail_max = fail_max
        self.reset_seconds = reset_seconds
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.reset_seconds:
            return "half_open"
        return "open"

    def allow(self) -> bool:
        """True if a request may proceed (closed or half-open for a probe)."""
        return self.state != "open"

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.fail_max:
            self.opened_at = time.monotonic()

    def reset(self) -> None:
        self.failures = 0
        self.opened_at = None
