"""Diamond MCP server.

Exposes Diamond's read-only projection / odds / accuracy data as MCP tools. Each tool is a
thin async wrapper over one Diamond REST endpoint (see :mod:`client`). The first ten tools
mirror the in-app "Ask Diamond" surface (names + descriptions ported from ``AskToolRegistry``);
the rest expose the richer read endpoints the REST API already serves.

Transport is selected by ``MCP_TRANSPORT``:
- ``stdio`` (default) — the trusted local path Claude Desktop launches as a subprocess.
- ``http``  — networked Streamable-HTTP with auth + rate limiting (see :mod:`app`).

The Diamond API must be reachable at ``DIAMOND_API_URL`` (default http://localhost:8080).
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import client, config

mcp = FastMCP("diamond", host=config.HTTP_HOST, port=config.HTTP_PORT)

# Caps matching the in-app Ask Diamond tools so this surface behaves identically.
_BEST_PLAYS_CAP = 15
_PLAYER_SEARCH_CAP = 8
_PLAYER_RECENT_GAMES = 15


# ── Health (unauthenticated probe) ──────────────────────────────────────────────


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ── MLB: slate, projections, picks ──────────────────────────────────────────────


@mcp.tool()
async def get_today_games() -> Any:
    """List today's MLB games (matchup, teams, start time, probable starters)."""
    return await client.get("/api/games/today")


@mcp.tool()
async def get_game_projections(game_id: int) -> Any:
    """Per-batter projections for one MLB game: hit/HR/TB probabilities, expected PA,
    matchup quality, and pitch-arsenal edges. Needs a gameId from get_today_games."""
    return await client.get(f"/api/games/{game_id}/projections")


@mcp.tool()
async def get_best_plays(date: str | None = None) -> Any:
    """Top sportsbook bets on the slate ranked by the model's edge over the de-vigged
    fair line (game markets + batter props), with EV%, best book, and price.

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/odds/best", {"date": date, "limit": _BEST_PLAYS_CAP})


@mcp.tool()
async def get_prop_board(date: str | None = None) -> Any:
    """The model's single most-likely batter per market (hit / HR / total bases /
    strikeout) plus top pitcher prop picks, with the reasoning behind each.

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/props/board", {"date": date})


@mcp.tool()
async def get_most_likely(date: str | None = None) -> Any:
    """Game-simulator board: full-game totals vs the line (edge, P(over)), NRFI/YRFI,
    first-five-innings markets, and the top player props.

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/most-likely", {"date": date})


@mcp.tool()
async def search_player(name: str) -> Any:
    """Find MLB players by (partial) name. Returns up to 8 matches with their numeric
    playerId, team, and position. Use this to resolve a name before get_player."""
    return await client.get("/api/players/search", {"name": name, "limit": _PLAYER_SEARCH_CAP})


@mcp.tool()
async def get_player(player_id: int) -> Any:
    """One MLB player's details plus their recent game log (PA, hits, HR, K, xwOBA).
    Needs a playerId from search_player."""
    detail, recent = await asyncio.gather(
        client.get(f"/api/players/{player_id}"),
        client.get(f"/api/players/{player_id}/recent", {"limit": _PLAYER_RECENT_GAMES}),
    )
    return {"player": detail, "recent": recent}


@mcp.tool()
async def get_model_accuracy(days: int | None = None) -> Any:
    """How the projection model has performed lately: per-market Brier vs baseline and
    calibration over a recent window.

    days: look-back window, 7-180 (default 30)."""
    return await client.get("/api/accuracy", {"days": days})


# ── Tennis ──────────────────────────────────────────────────────────────────────


@mcp.tool()
async def get_tennis_matches_today() -> Any:
    """Today's scheduled ATP matches with surface-blended win probabilities and best-line EV."""
    return await client.get("/api/tennis/matches/today")


@mcp.tool()
async def get_tennis_match(match_id: int) -> Any:
    """One tennis match's detail: players, surface, win probabilities, total-games and
    ace/double-fault markets. Needs a matchId from get_tennis_matches_today."""
    return await client.get(f"/api/tennis/matches/{match_id}")


# ── Richer read surface (beyond the Ask Diamond set) ────────────────────────────


@mcp.tool()
async def get_game_odds(game_id: int) -> Any:
    """All sportsbook odds for one MLB game: game markets plus batter props, per book."""
    return await client.get(f"/api/games/{game_id}/odds")


@mcp.tool()
async def get_prop_odds(date: str | None = None) -> Any:
    """Batter prop over-prices for the slate (best available price per selection).

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/odds/props", {"date": date})


@mcp.tool()
async def get_hit_rates(date: str | None = None) -> Any:
    """Hit-rate 'traffic light' per batter prop market — last 5/10/20 games and season.

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/odds/hit-rates", {"date": date})


@mcp.tool()
async def get_line_shop(date: str | None = None) -> Any:
    """Multi-book price ladder per prop selection (line shopping across books).

    date: slate date as YYYY-MM-DD; omit for today."""
    return await client.get("/api/odds/line-shop", {"date": date})


@mcp.tool()
async def get_player_spray(player_id: int, season: int | None = None) -> Any:
    """Spray-direction bins for a batter (pull/center/oppo distribution and HR by zone).

    season: 4-digit year; omit for the current season."""
    return await client.get(f"/api/players/{player_id}/spray", {"season": season})


@mcp.tool()
async def get_pitcher_skill(pitcher_id: int) -> Any:
    """A pitcher's skill metrics (e.g. K%/whiff by batter handedness)."""
    return await client.get(f"/api/pitchers/{pitcher_id}/skill")


@mcp.tool()
async def list_pitch_types() -> Any:
    """Supported pitch types (code + friendly name) for the pitch-type leaderboard."""
    return await client.get("/api/leaderboards/pitch-types")


@mcp.tool()
async def get_pitch_type_leaderboard(
    pitch: str, date: str | None = None, limit: int | None = None
) -> Any:
    """Top batters today versus a given pitch type, ranked by regressed xwOBA edge.

    pitch: pitch-type code from list_pitch_types (e.g. 'FF', 'SL').
    date: slate date as YYYY-MM-DD; omit for today.
    limit: max rows."""
    return await client.get(
        "/api/leaderboards/pitch-type", {"pitch": pitch, "date": date, "limit": limit}
    )


@mcp.tool()
async def get_tennis_rankings(surface: str | None = None, limit: int | None = None) -> Any:
    """Tennis (ATP) Elo rankings, optionally by surface.

    surface: one of all / hard / clay / grass (default all).
    limit: max rows (capped at 200 server-side)."""
    return await client.get("/api/tennis/rankings", {"surface": surface, "limit": limit})


@mcp.tool()
async def get_tennis_accuracy() -> Any:
    """Tennis model accuracy broken down by surface."""
    return await client.get("/api/tennis/accuracy")


def main() -> None:
    """Console-script entry point. stdio by default; HTTP when MCP_TRANSPORT=http."""
    if config.TRANSPORT == "http":
        import uvicorn

        from .app import build_app

        uvicorn.run(build_app(), host=config.HTTP_HOST, port=config.HTTP_PORT)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
