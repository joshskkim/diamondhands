"""Resilient async HTTP client over the Diamond REST API.

Every tool funnels through :func:`get`, which layers (in order):
  1. a short-TTL response cache (cuts repeat round-trips, shields against brief blips),
  2. a circuit breaker (fail fast when the API is down),
  3. retry with exponential backoff + jitter on transient failures,
and always returns parsed JSON on success or an ``{"error": ...}`` dict on failure — never
raising — mirroring the in-app "Ask Diamond" error-as-JSON contract so the model can recover.
"""

from __future__ import annotations

from typing import Any

import httpx
from cachetools import TTLCache
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from . import config, metrics
from .breaker import CircuitBreaker

_TIMEOUT = httpx.Timeout(config.API_TIMEOUT_SECONDS)

# Module-level async client so connections are pooled across tool calls within the process.
_client = httpx.AsyncClient(base_url=config.API_BASE_URL, timeout=_TIMEOUT)

_breaker = CircuitBreaker(config.BREAKER_FAIL_MAX, config.BREAKER_RESET_SECONDS)
_cache: TTLCache[str, Any] = TTLCache(maxsize=config.CACHE_MAXSIZE, ttl=config.CACHE_TTL_SECONDS)


def _clean_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """Drop None-valued params so optional args (e.g. an omitted date) fall through to
    the API's own defaults instead of being sent as empty strings."""
    if not params:
        return {}
    return {k: v for k, v in params.items() if v is not None}


def _cache_key(path: str, params: dict[str, Any]) -> str:
    return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))


def _is_transient(exc: BaseException) -> bool:
    """Worth retrying: network/timeout errors and 5xx. 4xx are caller errors — don't retry."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


async def _request(path: str, params: dict[str, Any]) -> Any:
    """One upstream GET. Raises httpx errors (so the retry/breaker layer can react)."""
    resp = await _client.get(path, params=params)
    resp.raise_for_status()
    return resp.json() if resp.content else {}


async def get(path: str, params: dict[str, Any] | None = None) -> Any:
    cleaned = _clean_params(params)
    key = _cache_key(path, cleaned)

    if config.CACHE_ENABLED and key in _cache:
        return _cache[key]

    if not _breaker.allow():
        metrics.record_upstream(path, "circuit_open")
        return {"error": f"upstream unavailable (circuit open) for {path}"}

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(1 + config.API_RETRIES),
            wait=wait_exponential_jitter(
                initial=config.API_RETRY_BACKOFF_INITIAL, max=config.API_RETRY_BACKOFF_MAX
            ),
            retry=retry_if_exception(_is_transient),
            reraise=True,
        ):
            with attempt:
                result = await _request(path, cleaned)
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            _breaker.record_failure()  # exhausted retries on a server error
        metrics.record_upstream(path, str(e.response.status_code))
        return {"error": f"HTTP {e.response.status_code} from {path}", "body": e.response.text[:500]}
    except httpx.HTTPError as e:
        _breaker.record_failure()
        metrics.record_upstream(path, "error")
        return {"error": f"request to {path} failed: {e}"}
    except ValueError as e:  # JSON decode error
        metrics.record_upstream(path, "decode_error")
        return {"error": f"invalid JSON from {path}: {e}"}

    _breaker.record_success()
    metrics.record_upstream(path, "ok")
    if config.CACHE_ENABLED:
        _cache[key] = result
    return result


def reset_state() -> None:
    """Clear cache + breaker (used by tests)."""
    _cache.clear()
    _breaker.reset()


async def aclose() -> None:
    """Close the shared client (called on HTTP server shutdown)."""
    await _client.aclose()
