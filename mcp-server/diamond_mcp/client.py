"""Async HTTP client over the Diamond REST API.

Every tool funnels through :func:`get`, which returns parsed JSON on success and an
``{"error": ...}`` dict on any failure. Surfacing errors as data (rather than raising)
lets Claude recover gracefully — it mirrors the error-as-JSON contract the in-app
"Ask Diamond" tools use (``AskToolRegistry.execute``).

The client is async so tools can fan out concurrent upstream calls and so the HTTP
transport serves requests without blocking the event loop.
"""

from __future__ import annotations

from typing import Any

import httpx

from . import config

_TIMEOUT = httpx.Timeout(config.API_TIMEOUT_SECONDS)

# Module-level async client so connections are pooled across tool calls within the process.
_client = httpx.AsyncClient(base_url=config.API_BASE_URL, timeout=_TIMEOUT)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop None-valued params so optional args (e.g. an omitted date) fall through to
    the API's own defaults instead of being sent as empty strings."""
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


async def get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``path`` (relative to the API base) and return parsed JSON.

    Returns an ``{"error": ...}`` dict instead of raising, so tool failures degrade
    gracefully into something the model can read and react to.
    """
    try:
        resp = await _client.get(path, params=_clean_params(params))
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP {e.response.status_code} from {path}", "body": e.response.text[:500]}
    except httpx.HTTPError as e:
        return {"error": f"request to {path} failed: {e}"}
    except ValueError as e:  # JSON decode error
        return {"error": f"invalid JSON from {path}: {e}"}


async def aclose() -> None:
    """Close the shared client (called on HTTP server shutdown)."""
    await _client.aclose()
