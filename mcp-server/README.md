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

## Run

```bash
cd mcp-server
uv run diamond-mcp           # stdio server (what Claude Desktop launches)
```

Configuration via environment:

- `DIAMOND_API_URL` — base URL of the Diamond API (default `http://localhost:8080`).

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
