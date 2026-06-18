"""Auth + rate-limit middleware tests, driven through an in-memory ASGI transport."""

import httpx
from starlette.responses import JSONResponse

from diamond_mcp import config
from diamond_mcp.auth import AuthMiddleware
from diamond_mcp.ratelimit import RateLimitMiddleware


async def _ok_app(scope, receive, send):
    # Echo the client id the auth middleware stamped, so tests can assert it.
    client_id = scope.get("state", {}).get("client_id")
    await JSONResponse({"ok": True, "client_id": client_id})(scope, receive, send)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── Auth ──────────────────────────────────────────────────────────────────────


async def test_auth_disabled_allows_and_keys_by_ip(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    async with _client(AuthMiddleware(_ok_app)) as ac:
        r = await ac.get("/x")
    assert r.status_code == 200
    assert r.json()["client_id"]  # an IP, not None


async def test_auth_enabled_rejects_missing_and_wrong_key(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_KEY_HASHES", {config._hash_key("secret")})
    async with _client(AuthMiddleware(_ok_app)) as ac:
        assert (await ac.get("/x")).status_code == 401
        assert (await ac.get("/x", headers={"Authorization": "Bearer nope"})).status_code == 401


async def test_auth_enabled_accepts_bearer_and_x_api_key(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_KEY_HASHES", {config._hash_key("secret")})
    async with _client(AuthMiddleware(_ok_app)) as ac:
        bearer = await ac.get("/x", headers={"Authorization": "Bearer secret"})
        header = await ac.get("/x", headers={"X-API-Key": "secret"})
    assert bearer.status_code == 200
    assert header.status_code == 200
    # client id is a stable, non-secret digest prefix (not the raw key)
    assert bearer.json()["client_id"] == config._hash_key("secret")[:12]


async def test_auth_exempts_healthz(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_KEY_HASHES", {config._hash_key("secret")})
    async with _client(AuthMiddleware(_ok_app)) as ac:
        assert (await ac.get("/healthz")).status_code == 200


# ── Rate limiting ───────────────────────────────────────────────────────────────


async def test_rate_limit_429_after_burst():
    app = RateLimitMiddleware(_ok_app, rps=1, burst=2)
    async with _client(app) as ac:
        assert (await ac.get("/x")).status_code == 200
        assert (await ac.get("/x")).status_code == 200
        blocked = await ac.get("/x")
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


async def test_rate_limit_exempts_healthz():
    app = RateLimitMiddleware(_ok_app, rps=1, burst=1)
    async with _client(app) as ac:
        for _ in range(5):
            assert (await ac.get("/healthz")).status_code == 200
