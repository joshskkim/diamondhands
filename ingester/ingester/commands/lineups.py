"""Ingest confirmed batting orders from the MLB Stats API.

Two entry points share the same per-date upsert logic:

    refresh-lineups   — pull today's posted lineups; idempotent, cron-friendly.
                        Run repeatedly through the day: early calls get nothing,
                        ~2-3 h before first pitch most games are posted.
    backfill-lineups  — pull a historical date range (Option B for backtesting),
                        parallelizing the network fetches like backfill-games.

Both fetch the schedule hydrated with lineups+probablePitcher, then for every game
already present in our games table whose lineup is posted, upsert game_lineups rows
and stamp games.{home,away}_lineup_confirmed_at. Lineups for games we don't track
(FK requires the games row to exist) are ignored.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.mlb_api import fetch_schedule, parse_game_lineups

MAX_WORKERS = 8
PROGRESS_EVERY = 25


def _fetch_with_lineups(game_date: date) -> list[dict]:
    return fetch_schedule(game_date, hydrate="lineups,probablePitcher")


def _ensure_player(conn: psycopg.Connection, player_id: int, name: str) -> None:
    """Stub-insert a lineup batter if absent; game_lineups FK-references players(id)."""
    conn.execute(
        "INSERT INTO players (id, full_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
        (player_id, name),
    )


def _upsert_side_lineup(
    conn: psycopg.Connection,
    game_id: int,
    is_home: bool,
    slots: list[tuple[int, str]],
) -> None:
    """Replace the confirmed batting order for one side and stamp confirmed_at.

    Called only with a full nine-man lineup, so a transient empty API response can
    never wipe a side we already confirmed. Clearing first keeps the table clean if
    the order ever changes before first pitch.
    """
    conn.execute(
        "DELETE FROM game_lineups WHERE game_id = %s AND is_home = %s",
        (game_id, is_home),
    )
    for batting_order, (player_id, name) in enumerate(slots, start=1):
        _ensure_player(conn, player_id, name)
        conn.execute(
            """
            INSERT INTO game_lineups (game_id, is_home, batting_order, player_id)
            VALUES (%s, %s, %s, %s)
            """,
            (game_id, is_home, batting_order, player_id),
        )
    # Column name is a fixed literal (not user input). COALESCE preserves the first
    # confirmation time across re-runs.
    col = "home_lineup_confirmed_at" if is_home else "away_lineup_confirmed_at"
    conn.execute(
        f"UPDATE games SET {col} = COALESCE({col}, NOW()) WHERE id = %s",
        (game_id,),
    )


def _process_date(
    conn: psycopg.Connection,
    game_date: date,
    raw_games: list[dict],
) -> tuple[int, int]:
    """Upsert lineups for all tracked games on game_date.

    Returns (sides_confirmed, games_touched).
    """
    tracked: set[int] = {
        int(row[0])
        for row in conn.execute(
            "SELECT id FROM games WHERE game_date = %s", (game_date,)
        ).fetchall()
    }

    sides = 0
    games_touched = 0
    for g in raw_games:
        game_pk = g.get("gamePk")
        if game_pk not in tracked:
            continue
        by_side = parse_game_lineups(g)
        if not by_side:
            continue
        for is_home, slots in by_side.items():
            _upsert_side_lineup(conn, game_pk, is_home, slots)
            sides += 1
        games_touched += 1
    return sides, games_touched


def cmd_refresh_lineups(args: argparse.Namespace) -> None:
    game_date = args.date if args.date is not None else eastern_today()
    print(f"[refresh-lineups] Fetching posted lineups for {game_date}…")

    raw = _fetch_with_lineups(game_date)
    conn = get_connection()
    try:
        sides, games_touched = _process_date(conn, game_date, raw)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[refresh-lineups] {games_touched} game(s) with confirmed lineups "
        f"({sides} side(s) upserted)."
    )


def cmd_backfill_lineups(args: argparse.Namespace) -> None:
    start: date = args.start
    end: date = args.end
    if end < start:
        raise SystemExit(f"[backfill-lineups] --end {end} is before --start {start}")

    dates = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    print(
        f"[backfill-lineups] Fetching lineups for {len(dates)} dates "
        f"({start} → {end}) with {MAX_WORKERS} workers…"
    )

    conn = get_connection()
    total_sides = 0
    total_games = 0
    dates_done = 0
    try:
        # Parallelize network fetches; psycopg is not thread-safe, so all DB writes
        # stay in the main thread. map() preserves input (chronological) order.
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for d, raw in zip(dates, pool.map(_fetch_with_lineups, dates)):
                sides, games_touched = _process_date(conn, d, raw)
                total_sides += sides
                total_games += games_touched
                dates_done += 1
                if dates_done % PROGRESS_EVERY == 0 or dates_done == len(dates):
                    conn.commit()
                    print(
                        f"[backfill-lineups] {dates_done}/{len(dates)} dates — "
                        f"{total_games} games, {total_sides} sides so far…"
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"Backfilled lineups for {total_games} games "
        f"({total_sides} sides) across {len(dates)} dates."
    )
