"""backfill-games: Populate historical games for a date range from the MLB Stats API.

Backtesting needs the games table seeded with past slates (the daily-slate command
only ever fills today). This walks every date in [--start, --end], fetches each day's
schedule (hydrated with probablePitcher), and upserts the games.

API fetches are parallelized with a thread pool (network-bound); all DB writes happen
serially in the main thread because the psycopg connection is not thread-safe.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import psycopg

from ingester.db import get_connection
from ingester.mlb_api import SLATE_GAME_TYPES, fetch_schedule

MAX_WORKERS = 8
PROGRESS_EVERY = 25


def _date_range(start: date, end: date) -> list[date]:
    """Inclusive list of dates from start to end."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def _ensure_player(conn: psycopg.Connection, player: dict) -> int:
    """Stub-insert a probable pitcher if absent; return their MLBAM ID.

    The games table FK-references players(id), so a probable pitcher must exist
    before we can store the game referencing it.
    """
    pid = player["id"]
    name = player.get("fullName") or f"Unknown#{pid}"
    conn.execute(
        "INSERT INTO players (id, full_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (pid, name),
    )
    return pid


def cmd_backfill_games(args: argparse.Namespace) -> None:
    start: date = args.start
    end: date = args.end
    if end < start:
        raise SystemExit(f"[backfill-games] --end {end} is before --start {start}")

    dates = _date_range(start, end)
    print(
        f"[backfill-games] Fetching schedules for {len(dates)} dates "
        f"({start} → {end}) with {MAX_WORKERS} workers…"
    )

    conn = get_connection()

    # team_id → home_stadium_id (populated by load-static)
    team_to_stadium: dict[int, int] = dict(
        conn.execute(
            "SELECT id, home_stadium_id FROM teams WHERE home_stadium_id IS NOT NULL"
        ).fetchall()
    )

    total_games = 0
    dates_done = 0

    # Parallelize the network fetches; ThreadPoolExecutor.map preserves input order
    # so progress reporting reflects chronological dates.
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for d, raw_games in zip(dates, pool.map(fetch_schedule, dates)):
            for g in raw_games:
                # sportId=1 already excludes non-MLB leagues; gameType filter drops
                # spring training ('S'), exhibition ('E'), and All-Star ('A') games.
                if g.get("gameType") not in SLATE_GAME_TYPES:
                    continue

                game_pk: int = g["gamePk"]
                game_date = date.fromisoformat(g.get("officialDate") or g["gameDate"][:10])
                start_utc = datetime.fromisoformat(g["gameDate"].replace("Z", "+00:00"))
                status: str = g.get("status", {}).get("abstractGameState", "Scheduled")

                home_team_id: int = g["teams"]["home"]["team"]["id"]
                away_team_id: int = g["teams"]["away"]["team"]["id"]

                stadium_id = team_to_stadium.get(home_team_id)
                if stadium_id is None:
                    print(
                        f"[backfill-games] WARNING: no stadium for home team "
                        f"{home_team_id} — skipping game {game_pk}"
                    )
                    continue

                home_pp = g["teams"]["home"].get("probablePitcher")
                away_pp = g["teams"]["away"].get("probablePitcher")
                home_pitcher_id = _ensure_player(conn, home_pp) if home_pp else None
                away_pitcher_id = _ensure_player(conn, away_pp) if away_pp else None

                conn.execute(
                    """
                    INSERT INTO games (
                        id, game_date, home_team_id, away_team_id, stadium_id,
                        start_time_utc, status,
                        home_probable_pitcher_id, away_probable_pitcher_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET game_date                = EXCLUDED.game_date,
                            home_team_id             = EXCLUDED.home_team_id,
                            away_team_id             = EXCLUDED.away_team_id,
                            stadium_id               = EXCLUDED.stadium_id,
                            start_time_utc           = EXCLUDED.start_time_utc,
                            status                   = EXCLUDED.status,
                            home_probable_pitcher_id = EXCLUDED.home_probable_pitcher_id,
                            away_probable_pitcher_id = EXCLUDED.away_probable_pitcher_id
                    """,
                    (
                        game_pk, game_date, home_team_id, away_team_id, stadium_id,
                        start_utc, status, home_pitcher_id, away_pitcher_id,
                    ),
                )
                total_games += 1

            dates_done += 1
            if dates_done % PROGRESS_EVERY == 0 or dates_done == len(dates):
                conn.commit()
                print(
                    f"[backfill-games] {dates_done}/{len(dates)} dates — "
                    f"{total_games} games so far…"
                )

    conn.commit()
    conn.close()
    print(f"Backfilled {total_games} games across {len(dates)} dates.")
