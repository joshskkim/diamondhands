"""Prometheus RED metrics (Rate, Errors, Duration) for the MCP server.

Two layers:
- per-tool: every ``@mcp.tool()`` is wrapped by :func:`instrument_tool`, recording call
  count (by tool + status) and latency.
- per-upstream-endpoint: :mod:`client` records each REST call (by endpoint + status).

``/metrics`` (see :mod:`server`) exposes the default registry for Prometheus to scrape.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from prometheus_client import Counter, Histogram

TOOL_CALLS = Counter(
    "mcp_tool_calls_total", "MCP tool invocations", ["tool", "status"]
)
TOOL_LATENCY = Histogram(
    "mcp_tool_latency_seconds", "MCP tool latency", ["tool"]
)
UPSTREAM_REQUESTS = Counter(
    "mcp_upstream_requests_total", "Upstream Diamond API requests", ["endpoint", "status"]
)
CACHE_EVENTS = Counter(
    "mcp_cache_events_total", "MCP response-cache lookups", ["result"]  # result = hit | miss
)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def instrument_tool(fn: F) -> F:
    """Wrap an async tool to record latency + a call counter labelled by tool and status.

    ``status`` is ``error`` when the tool raises or returns the ``{"error": ...}`` payload our
    client produces on upstream failure, else ``ok``. ``functools.wraps`` preserves the
    signature + docstring so FastMCP still derives the correct input schema.
    """

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        tool = fn.__name__
        start = time.perf_counter()
        status = "ok"
        try:
            result = await fn(*args, **kwargs)
            if isinstance(result, dict) and "error" in result:
                status = "error"
            return result
        except Exception:
            status = "error"
            raise
        finally:
            TOOL_LATENCY.labels(tool).observe(time.perf_counter() - start)
            TOOL_CALLS.labels(tool, status).inc()

    return wrapper  # type: ignore[return-value]


_ID_SEGMENT = re.compile(r"/\d+")


def record_upstream(endpoint: str, status: str) -> None:
    # Collapse numeric path segments (/api/games/42/... -> /api/games/{id}/...) to keep
    # the metric's label cardinality bounded.
    UPSTREAM_REQUESTS.labels(_ID_SEGMENT.sub("/{id}", endpoint), status).inc()


def record_cache(hit: bool) -> None:
    CACHE_EVENTS.labels("hit" if hit else "miss").inc()
