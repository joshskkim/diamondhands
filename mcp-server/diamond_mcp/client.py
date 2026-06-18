"""Thin HTTP client over the Diamond REST API.

Every tool funnels through :func:`get`, which returns parsed JSON on success and an
``{"error": ...}`` dict on any failure. Surfacing errors as data (rather than raising)
lets Claude recover gracefully — it mirrors the error-as-JSON contract the in-app
"Ask Diamond" tools use (``AskToolRegistry.execute``).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

#: Base URL of the running Diamond API. Override with DIAMOND_API_URL.
BASE_URL = os.environ.get("DIAMOND_API_URL", "http://localhost:8080").rstrip("/")

_TIMEOUT = httpx.Timeout(10.0)

# Module-level client so connections are pooled across tool calls within the process.
_client = httpx.Client(base_url=BASE_URL, timeout=_TIMEOUT)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop None-valued params so optional args (e.g. an omitted date) fall through to
    the API's own defaults instead of being sent as empty strings."""
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


def get(path: str, params: dict[str, Any] | None = None) -> Any:
    """GET ``path`` (relative to the API base) and return parsed JSON.

    Returns an ``{"error": ...}`` dict instead of raising, so tool failures degrade
    gracefully into something the model can read and react to.
    """
    try:
        resp = _client.get(path, params=_clean_params(params))
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
