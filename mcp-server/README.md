# Diamond MCP Server

An [MCP](https://modelcontextprotocol.io) server that exposes Diamond's read-only
projection / odds / accuracy data to **Claude Desktop** (and any MCP client). It is a thin
HTTP wrapper over the Diamond REST API — the API stays the single source of truth.

The tool surface mirrors the in-app "Ask Diamond" tools (`AskToolRegistry`) and adds the
richer read endpoints the REST API already serves (line shopping, hit rates, spray, pitcher
skill, pitch-type leaderboard, tennis rankings, …).

## Prerequisites

- The Diamond API running and reachable (default `http://localhost:8080`).
- [`uv`](https://docs.astral.sh/uv/).

## Transports

The server runs over one of two transports, selected by `MCP_TRANSPORT`:

- **`stdio`** (default) — the trusted local path Claude Desktop launches as a subprocess. No
  auth/rate limiting (the only client is you, locally).
- **`http`** — networked Streamable-HTTP, with **API-key auth**, **per-client rate limiting**,
  and a `/healthz` probe. This is the hardened path meant for shared/remote use.

```bash
cd mcp-server
uv run diamond-mcp                       # stdio (Claude Desktop)
MCP_TRANSPORT=http uv run diamond-mcp    # networked HTTP on :8090
```

## Configuration (environment)

| Var | Default | Purpose |
|---|---|---|
| `DIAMOND_API_URL` | `http://localhost:8080` | Base URL of the Diamond API |
| `DIAMOND_API_TIMEOUT` | `10` | Upstream request timeout (seconds) |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8090` | HTTP bind address |
| `MCP_API_KEYS` | _(empty)_ | Comma-separated API keys for the HTTP transport. **Empty ⇒ auth OFF** (dev only); set it for any networked deployment. Keys are compared by SHA-256. |
| `MCP_RATE_LIMIT_RPS` / `MCP_RATE_LIMIT_BURST` | `5` / `20` | Token-bucket sustained rate + burst, per client |
| `MCP_RATE_LIMIT_ENABLED` | `true` | Toggle rate limiting |

On the HTTP transport, send the key as `Authorization: Bearer <key>` or `X-API-Key: <key>`.
`/healthz` and `/metrics` are always exempt. Rate-limit state is in-memory per process; a
Redis-backed limiter (Redis is already in the stack) is the multi-instance upgrade.

## Develop

```bash
uv run pytest                          # unit tests (HTTP mocked)
uv run mcp dev diamond_mcp/server.py   # MCP Inspector — list & invoke tools against a live API
```

## Claude Desktop

Add to `claude_desktop_config.json`
(`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS), then restart
Claude Desktop:

```json
{
  "mcpServers": {
    "diamond": {
      "command": "uv",
      "args": ["--directory", "/Users/joshuakim/projects/diamond/mcp-server", "run", "diamond-mcp"],
      "env": { "DIAMOND_API_URL": "http://localhost:8080" }
    }
  }
}
```

Then ask, e.g., *"What are tonight's best MLB plays?"* or *"How has the hit model been
calibrated lately?"* and Claude will call the `diamond` tools.

## Tools

Mirror of the Ask Diamond set: `get_today_games`, `get_game_projections`, `get_best_plays`,
`get_prop_board`, `get_most_likely`, `search_player`, `get_player`, `get_model_accuracy`,
`get_tennis_matches_today`, `get_tennis_match`.

Richer surface: `get_game_odds`, `get_prop_odds`, `get_hit_rates`, `get_line_shop`,
`get_player_spray`, `get_pitcher_skill`, `list_pitch_types`, `get_pitch_type_leaderboard`,
`get_tennis_rankings`, `get_tennis_accuracy`.
