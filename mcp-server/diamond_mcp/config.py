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
