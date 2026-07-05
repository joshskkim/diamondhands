"""daily-slate: Fetch today's games + probable pitchers from MLB Stats API."""
from __future__ import annotations

import argparse
from datetime import date, datetime

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.mlb_api import (
    SLATE_GAME_TYPES,
    fetch_pitcher_season_stats,
    fetch_schedule,
)


def parse_schedule_status(g: dict) -> tuple[str, str | None, datetime]:
    """Pull (status, detailed_status, start_time_utc) out of a raw MLB schedule game.

    Single source of truth for how the Stats API payload maps to those columns, shared
    by daily-slate (full upsert) and refresh-lineups (in-day status refresh):
      · status          — abstractGameState: Scheduled / Live / Final
      · detailed_status — detailedState (Postponed / Suspended / Cancelled / Delayed …),
                          which abstractGameState never reports; the projector reads this
                          to skip games that won't be played as scheduled.
      · start_time_utc  — gameDate, ISO 8601 (e.g. "2025-05-28T17:10:00Z").
    """
    status: str = g.get("status", {}).get("abstractGameState", "Scheduled")
    detailed_status: str | None = g.get("status", {}).get("detailedState")
    start_utc = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
    return status, detailed_status, start_utc


def update_game_status(conn: psycopg.Connection, game_pk: int, g: dict) -> None:
    """Refresh status/detailed_status/start_time_utc for an already-tracked game.

    Used by the afternoon quick loop (via refresh-lineups) so a game postponed after the
    morning slate build is detected the same day — the projector then skips it and clears
    its rows. No-ops if the game row doesn't exist yet (daily-slate inserts it first)."""
    status, detailed_status, start_utc = parse_schedule_status(g)
    conn.execute(
        """
        UPDATE games
           SET status          = %s,
               detailed_status = %s,
               start_time_utc  = %s
         WHERE id = %s
        """,
        (status, detailed_status, start_utc, game_pk),
    )


def _ensure_player(conn: psycopg.Connection, player: dict) -> int:
    """Stub-insert a player if they don't exist in players yet; return their MLBAM ID."""
    pid = player["id"]
    name = player.get("fullName") or f"Unknown#{pid}"
    conn.execute(
        """
        INSERT INTO players (id, full_name)
        VALUES (%s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (pid, name),
    )
    return pid


def _refresh_season_role(conn: psycopg.Connection, player_id: int, season: int) -> bool:
    """Fetch + upsert a probable pitcher's season role stats. Returns True if stored."""
    role = fetch_pitcher_season_stats(player_id, season)
    if role is None:
        return False
    conn.execute(
        """
        INSERT INTO pitcher_season_role (
            player_id, season, games_started, games_pitched,
            innings_pitched, games_finished, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (player_id, season) DO UPDATE SET
            games_started   = EXCLUDED.games_started,
            games_pitched   = EXCLUDED.games_pitched,
            innings_pitched = EXCLUDED.innings_pitched,
            games_finished  = EXCLUDED.games_finished,
            updated_at      = NOW()
        """,
        (
            player_id,
            season,
            role["games_started"],
            role["games_pitched"],
            role["innings_pitched"],
            role["games_finished"],
        ),
    )
    return True


def cmd_daily_slate(args: argparse.Namespace) -> None:
    today = args.date if args.date is not None else eastern_today()
    print(f"[daily-slate] Fetching schedule for {today}…")

    raw_games = fetch_schedule(today)
    if not raw_games:
        print("[daily-slate] No games returned by MLB Stats API.")
        return

    conn = get_connection()

    # team_id → home_stadium_id (populated by load-static)
    team_to_stadium: dict[int, int] = dict(
        conn.execute(
            "SELECT id, home_stadium_id FROM teams WHERE home_stadium_id IS NOT NULL"
        ).fetchall()
    )

    upserted = 0
    confirmed = 0
    roles = 0

    for g in raw_games:
        if g.get("gameType") not in SLATE_GAME_TYPES:
            continue

        game_pk: int = g["gamePk"]

        # Local calendar date (handles edge case where UTC rolls to next day)
        game_date = date.fromisoformat(
            g.get("officialDate") or g["gameDate"][:10]
        )

        # status / detailed_status / UTC start time — see parse_schedule_status.
        status, detailed_status, start_utc = parse_schedule_status(g)

        home_team_id: int = g["teams"]["home"]["team"]["id"]
        away_team_id: int = g["teams"]["away"]["team"]["id"]

        stadium_id = team_to_stadium.get(home_team_id)
        if stadium_id is None:
            print(
                f"[daily-slate] WARNING: no stadium for home team {home_team_id}"
                f" — skipping game {game_pk}"
            )
            continue

        # Probable pitchers (absent until ~24 h before first pitch)
        home_pp = g["teams"]["home"].get("probablePitcher")
        away_pp = g["teams"]["away"].get("probablePitcher")

        home_pitcher_id: int | None = _ensure_player(conn, home_pp) if home_pp else None
        away_pitcher_id: int | None = _ensure_player(conn, away_pp) if away_pp else None

        # Cache each probable's season role (GS/GP/IP) so the projector can spot a
        # reliever opening a bullpen game and skip projecting him as a starter.
        for pid in (home_pitcher_id, away_pitcher_id):
            if pid is not None and _refresh_season_role(conn, pid, game_date.year):
                roles += 1

        conn.execute(
            """
            INSERT INTO games (
                id, game_date, home_team_id, away_team_id, stadium_id,
                start_time_utc, status, detailed_status,
                home_probable_pitcher_id, away_probable_pitcher_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status                   = EXCLUDED.status,
                    detailed_status          = EXCLUDED.detailed_status,
                    start_time_utc           = EXCLUDED.start_time_utc,
                    -- Keep a probable once known: a transient schedule fetch that omits
                    -- probablePitcher would otherwise NULL it out and un-project the game
                    -- on the next tick (the quick loop re-upserts every 30 min). Probables
                    -- don't revert to "unknown" same-day, so COALESCE only guards against
                    -- API flakiness — a *changed* probable still arrives non-null and wins.
                    home_probable_pitcher_id = COALESCE(EXCLUDED.home_probable_pitcher_id,
                                                        games.home_probable_pitcher_id),
                    away_probable_pitcher_id = COALESCE(EXCLUDED.away_probable_pitcher_id,
                                                        games.away_probable_pitcher_id)
            """,
            (
                game_pk,
                game_date,
                home_team_id,
                away_team_id,
                stadium_id,
                start_utc,
                status,
                detailed_status,
                home_pitcher_id,
                away_pitcher_id,
            ),
        )
        upserted += 1
        if home_pitcher_id and away_pitcher_id:
            confirmed += 1

    conn.commit()
    conn.close()
    print(
        f"Slate: {upserted} games, {confirmed} with confirmed probables, "
        f"{roles} pitcher roles cached."
    )
