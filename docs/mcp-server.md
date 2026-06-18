# MCP server

A [Model Context Protocol](https://modelcontextprotocol.io) server (`mcp-server/`) that exposes
Diamond's read-only projection / odds / accuracy data to MCP clients (Claude Desktop, etc.). It
is a thin, decoupled layer over the existing REST API — the API stays the single source of
truth; no model/business logic is duplicated.

## Architecture

```
┌────────────────┐   MCP (stdio | Streamable-HTTP)   ┌──────────────┐   HTTP   ┌──────────┐   JDBC   ┌──────────┐
│ Claude Desktop │ ────────────────────────────────▶ │ diamond-mcp  │ ───────▶ │ diamond  │ ───────▶ │ Postgres │
│  (MCP client)  │      tools/call get_best_plays     │  (Python)    │  +trace  │   -api   │  spans   │          │
└────────────────┘                                    └──────────────┘ parent   └──────────┘          └──────────┘
```

Two transports, selected by `MCP_TRANSPORT`:

- **`stdio`** (default) — the trusted local path Claude Desktop launches as a subprocess.
- **`http`** — networked Streamable-HTTP with API-key auth, per-client rate limiting, a
  `/healthz` probe, a `/metrics` endpoint, and distributed tracing.

## Tools

22 read tools. The first 10 mirror the in-app "Ask Diamond" surface (names + descriptions ported
from `AskToolRegistry`); the next 10 expose the richer read endpoints (game/prop odds, hit-rates,
line-shop, spray, pitcher skill, pitch-type leaderboard, tennis rankings/accuracy). Most are thin
async wrappers over one REST endpoint; `client.get()` returns parsed JSON or an `{"error": ...}`
payload on failure (never raises), so the model can recover gracefully.

The last two are **composite tools** that fan out concurrent upstream calls and merge the
results, saving the model multi-call round trips:

- `get_game_briefing(game_id)` → batter projections + full odds for a game (2 calls in parallel).
- `get_slate_summary(date?)` → today's games + best-EV plays + prop-board headline (3 in parallel).

## Resilience

`client.get()` layers three protections around every upstream call:

- **Retry** with exponential backoff + jitter on *transient* failures only (timeouts, connect
  errors, 5xx); 4xx are caller errors and are not retried.
- **Circuit breaker** — after `MCP_BREAKER_FAIL_MAX` consecutive failures it opens and fails
  fast (`{"error": "upstream unavailable (circuit open)"}`) for `MCP_BREAKER_RESET_SECONDS`,
  then half-opens to probe. Keeps the model from hanging on a dead API.
- **Short-TTL cache** (`MCP_CACHE_TTL_SECONDS`, default 45s) on successful responses. The API
  already Redis-caches ~5 min, so this mainly cuts repeat round-trips within a conversation and
  shields against brief blips (measured cache hit ~0.005ms vs ~5ms miss).

## Security (HTTP transport)

- **Auth** — `Authorization: Bearer <key>` or `X-API-Key: <key>`, compared by SHA-256 against
  `MCP_API_KEYS`. Empty key set ⇒ auth off (dev only). The authenticated key's hash prefix
  becomes the client id used for rate-limiting + metrics labels.
- **Rate limiting** — per-client token bucket (`MCP_RATE_LIMIT_RPS` / `_BURST`); 429 +
  `Retry-After` on exceed. In-memory per process; a Redis-backed limiter (Redis is already in
  the stack) is the multi-instance upgrade.
- Both are pure-ASGI middleware so they don't buffer MCP's streaming responses. `/healthz` and
  `/metrics` are always exempt.

## Observability

- **Distributed tracing.** With tracing on, the OTLP-HTTP exporter ships spans to the same
  collector the API uses (`OTLP_TRACING_ENDPOINT`, default `:4318`), and httpx instrumentation
  stamps a W3C `traceparent` on every upstream call. Because the Spring API already continues
  incoming traceparent (micrometer-tracing-bridge-otel), a single Claude request appears in
  Jaeger as **one trace**: `diamond-mcp` (server span) → httpx (client span) → `diamond-api`
  request → JDBC query spans.
- **Metrics (RED).** Prometheus at `GET /metrics`, scraped by the `diamond-mcp` job
  (`monitoring/prometheus.yml`): `mcp_tool_calls_total{tool,status}`,
  `mcp_tool_latency_seconds{tool}`, and `mcp_upstream_requests_total{endpoint,status}` (endpoint
  labels normalized — numeric ids → `{id}` — to bound cardinality).

## Load test

`loadtest/driver.py` opens N concurrent real MCP sessions (full Streamable-HTTP + JSON-RPC
handshake) and fires `tools/call` requests, reporting latency percentiles + throughput.

```bash
MCP_RATE_LIMIT_ENABLED=false MCP_TRACING_ENABLED=false MCP_TRANSPORT=http uv run diamond-mcp &
uv run python loadtest/driver.py --concurrency 20 --requests 50 --tool get_today_games
```

Measured locally, end-to-end through the MCP server into the live API (Redis cache warm),
`get_today_games`:

| Concurrency | Requests | Throughput | p50 | p95 | p99 |
|---|---|---|---|---|---|
| 20 | 1,000 | ~421 req/s | 39 ms | 73 ms | 102 ms |
| 50 | 2,000 | ~398 req/s | 81 ms | 208 ms | 308 ms |

Throughput plateaus ~400 req/s with a clean latency knee past the upstream API's effective
concurrency — i.e. the MCP layer is not the bottleneck; it tracks the API it fronts.
