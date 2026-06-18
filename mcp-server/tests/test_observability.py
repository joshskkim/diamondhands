"""Metrics: tool instrumentation records RED series, the schema survives the decorator,
and upstream-endpoint labels are normalized."""

import httpx
import respx

from diamond_mcp import client, metrics, server

BASE = client.config.API_BASE_URL


def _counter_value(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


async def test_decorator_preserves_input_schema():
    tools = {t.name: t for t in await server.mcp.list_tools()}
    schema = tools["get_game_projections"].inputSchema
    assert "game_id" in schema["properties"]
    assert schema["properties"]["game_id"]["type"] == "integer"


@respx.mock
async def test_tool_call_records_ok_metric():
    respx.get(f"{BASE}/api/games/today").mock(return_value=httpx.Response(200, json=[]))
    before = _counter_value(metrics.TOOL_CALLS, tool="get_today_games", status="ok")
    await server.get_today_games()
    after = _counter_value(metrics.TOOL_CALLS, tool="get_today_games", status="ok")
    assert after == before + 1


@respx.mock
async def test_tool_error_records_error_status():
    respx.get(f"{BASE}/api/games/today").mock(return_value=httpx.Response(503))
    before = _counter_value(metrics.TOOL_CALLS, tool="get_today_games", status="error")
    await server.get_today_games()  # returns {"error": ...} -> error status
    after = _counter_value(metrics.TOOL_CALLS, tool="get_today_games", status="error")
    assert after == before + 1


@respx.mock
async def test_upstream_endpoint_label_is_normalized():
    respx.get(f"{BASE}/api/games/42/projections").mock(
        return_value=httpx.Response(200, json={})
    )
    await server.get_game_projections(game_id=42)
    # numeric id collapsed to {id} so label cardinality stays bounded
    assert _counter_value(
        metrics.UPSTREAM_REQUESTS, endpoint="/api/games/{id}/projections", status="ok"
    ) >= 1


@respx.mock
async def test_traceparent_injected_on_upstream_when_tracing_on():
    """The mechanism behind cross-service tracing: with httpx instrumented, outbound calls
    carry a W3C traceparent, which the Java API continues. Uses a bare in-memory provider
    (no OTLP exporter) so the test does no network I/O."""
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.trace import TracerProvider

    HTTPXClientInstrumentor().instrument(tracer_provider=TracerProvider())
    try:
        route = respx.get(f"{BASE}/api/games/today").mock(
            return_value=httpx.Response(200, json=[])
        )
        await client.get("/api/games/today")
        assert "traceparent" in route.calls.last.request.headers
    finally:
        HTTPXClientInstrumentor().uninstrument()
