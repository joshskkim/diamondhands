"""Environment-driven configuration for the Diamond MCP server.

Kept in one place so the HTTP app, middleware, and client read the same settings. All values
have dev-friendly defaults; production overrides come from the container environment.
"""

from __future__ import annotations

import hashlib
import os

# ── Upstream API ────────────────────────────────────────────────────────────────
API_BASE_URL = os.environ.get("DIAMOND_API_URL", "http://localhost:8080").rstrip("/")
API_TIMEOUT_SECONDS = float(os.environ.get("DIAMOND_API_TIMEOUT", "10"))

# ── Resilience ──────────────────────────────────────────────────────────────────
# Extra retries on transient upstream failures (timeouts, connect errors, 5xx).
API_RETRIES = int(os.environ.get("DIAMOND_API_RETRIES", "2"))
API_RETRY_BACKOFF_INITIAL = float(os.environ.get("DIAMOND_API_RETRY_BACKOFF_INITIAL", "0.1"))
API_RETRY_BACKOFF_MAX = float(os.environ.get("DIAMOND_API_RETRY_BACKOFF_MAX", "2.0"))
# Circuit breaker: open after N consecutive failures, probe again after the cooldown.
BREAKER_FAIL_MAX = int(os.environ.get("MCP_BREAKER_FAIL_MAX", "5"))
BREAKER_RESET_SECONDS = float(os.environ.get("MCP_BREAKER_RESET_SECONDS", "30"))
# Short-TTL response cache. The API already Redis-caches ~5 min, so this mainly cuts
# repeat round-trips within a conversation + shields against brief upstream blips.
CACHE_ENABLED = os.environ.get("MCP_CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL_SECONDS = float(os.environ.get("MCP_CACHE_TTL_SECONDS", "45"))
CACHE_MAXSIZE = int(os.environ.get("MCP_CACHE_MAXSIZE", "512"))

# ── Transport ───────────────────────────────────────────────────────────────────
# "stdio" (default, trusted local path for Claude Desktop) or "http" (networked,
# hardened path with auth + rate limiting + metrics).
TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio").lower()
HTTP_HOST = os.environ.get("MCP_HOST", "127.0.0.1")
HTTP_PORT = int(os.environ.get("MCP_PORT", "8090"))

# ── Auth ────────────────────────────────────────────────────────────────────────
# Comma-separated API keys accepted on the HTTP transport. Empty set => auth is OFF
# (handy for local dev); set MCP_API_KEYS in any networked/shared deployment.
def _load_api_key_hashes() -> set[str]:
    raw = os.environ.get("MCP_API_KEYS", "")
    return {_hash_key(k.strip()) for k in raw.split(",") if k.strip()}


def _hash_key(key: str) -> str:
    """SHA-256 of a key so we compare digests, never raw secrets, in memory/logs."""
    return hashlib.sha256(key.encode()).hexdigest()


API_KEY_HASHES: set[str] = _load_api_key_hashes()
AUTH_ENABLED: bool = bool(API_KEY_HASHES)

# ── Rate limiting (token bucket, per client) ─────────────────────────────────────
# Sustained requests/second and burst capacity. Generous defaults; tune per deployment.
RATE_LIMIT_RPS = float(os.environ.get("MCP_RATE_LIMIT_RPS", "5"))
RATE_LIMIT_BURST = int(os.environ.get("MCP_RATE_LIMIT_BURST", "20"))
RATE_LIMIT_ENABLED = os.environ.get("MCP_RATE_LIMIT_ENABLED", "true").lower() == "true"

# Paths exempt from auth + rate limiting (liveness probes, metrics scraping).
EXEMPT_PATHS = ("/healthz", "/metrics")

# ── Observability ─────────────────────────────────────────────────────────────
# OTLP HTTP traces endpoint — same collector the Java API uses, so a single Claude
# request becomes one distributed trace spanning diamond-mcp -> diamond-api -> JDBC.
OTLP_TRACING_ENDPOINT = os.environ.get(
    "OTLP_TRACING_ENDPOINT", "http://localhost:4318/v1/traces"
)
OTEL_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "diamond-mcp")
# Tracing is part of the networked path; off by default on stdio to keep Claude Desktop quiet.
TRACING_ENABLED = os.environ.get("MCP_TRACING_ENABLED", "true").lower() == "true"
