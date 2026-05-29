"""daily-slate: Fetch today's games + probable pitchers from MLB Stats API."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.mlb_api import SLATE_GAME_TYPES, fetch_schedule


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

    for g in raw_games:
        if g.get("gameType") not in SLATE_GAME_TYPES:
            continue

        game_pk: int = g["gamePk"]

        # Local calendar date (handles edge case where UTC rolls to next day)
        game_date = date.fromisoformat(
            g.get("officialDate") or g["gameDate"][:10]
        )

        # UTC start time — gameDate is ISO 8601, e.g. "2025-05-28T17:10:00Z"
        start_utc = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))

        # MLB uses 'abstractGameState': Scheduled / Live / Final
        status: str = g.get("status", {}).get("abstractGameState", "Scheduled")

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

        conn.execute(
            """
            INSERT INTO games (
                id, game_date, home_team_id, away_team_id, stadium_id,
                start_time_utc, status,
                home_probable_pitcher_id, away_probable_pitcher_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE
                SET status                   = EXCLUDED.status,
                    start_time_utc           = EXCLUDED.start_time_utc,
                    home_probable_pitcher_id = EXCLUDED.home_probable_pitcher_id,
                    away_probable_pitcher_id = EXCLUDED.away_probable_pitcher_id
            """,
            (
                game_pk,
                game_date,
                home_team_id,
                away_team_id,
                stadium_id,
                start_utc,
                status,
                home_pitcher_id,
                away_pitcher_id,
            ),
        )
        upserted += 1
        if home_pitcher_id and away_pitcher_id:
            confirmed += 1

    conn.commit()
    conn.close()
    print(f"Slate: {upserted} games, {confirmed} with confirmed probables.")
