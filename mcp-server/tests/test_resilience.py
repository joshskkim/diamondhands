"""Resilience: TTL cache, retry-on-transient, no-retry-on-4xx, and circuit breaker."""

import httpx
import respx

from diamond_mcp import client, config, metrics

BASE = client.config.API_BASE_URL


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


@respx.mock
async def test_cache_serves_second_call_without_upstream():
    route = respx.get(f"{BASE}/api/games/today").mock(
        return_value=httpx.Response(200, json=[{"g": 1}])
    )
    hits0 = _counter_value(metrics.CACHE_EVENTS, result="hit")
    miss0 = _counter_value(metrics.CACHE_EVENTS, result="miss")

    first = await client.get("/api/games/today")
    second = await client.get("/api/games/today")

    assert first == second == [{"g": 1}]
    assert route.call_count == 1  # second served from cache
    # one miss (first call) then one hit (second call)
    assert _counter_value(metrics.CACHE_EVENTS, result="miss") == miss0 + 1
    assert _counter_value(metrics.CACHE_EVENTS, result="hit") == hits0 + 1


@respx.mock
async def test_retry_then_success_on_transient(monkeypatch):
    monkeypatch.setattr(config, "API_RETRIES", 2)
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_INITIAL", 0.0)
    monkeypatch.setattr(config, "API_RETRY_BACKOFF_MAX", 0.0)
    route = respx.get(f"{BASE}/api/odds/best").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json=[{"ok": True}]),
        ]
    )
    result = await client.get("/api/odds/best")
    assert result == [{"ok": True}]
    assert route.call_count == 3


@respx.mock
async def test_no_retry_on_4xx(monkeypatch):
    monkeypatch.setattr(config, "API_RETRIES", 2)
    route = respx.get(f"{BASE}/api/players/1").mock(return_value=httpx.Response(404))
    result = await client.get("/api/players/1")
    assert "error" in result and "404" in result["error"]
    assert route.call_count == 1  # 4xx is not transient


@respx.mock
async def test_circuit_breaker_opens_and_fails_fast(monkeypatch):
    monkeypatch.setattr(config, "API_RETRIES", 0)
    monkeypatch.setattr(client._breaker, "fail_max", 2)
    client._breaker.reset()
    route = respx.get(f"{BASE}/api/most-likely").mock(return_value=httpx.Response(503))

    await client.get("/api/most-likely")  # failure 1
    await client.get("/api/most-likely")  # failure 2 -> opens
    assert client._breaker.state == "open"

    blocked = await client.get("/api/most-likely")  # short-circuited
    assert "circuit open" in blocked["error"]
    assert route.call_count == 2  # third call never hit upstream
