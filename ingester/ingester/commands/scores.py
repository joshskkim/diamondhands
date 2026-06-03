"""backfill-scores: actual final scores from the MLB schedule into games.{home,away}_score.

Parallelizes the per-date schedule fetches like backfill-lineups; DB writes stay on the
main thread (psycopg isn't thread-safe). Updates only games we already track (the UPDATE
no-ops for untracked gamePks).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import psycopg

from ingester.db import get_connection
from ingester.mlb_api import fetch_schedule, parse_game_score

MAX_WORKERS = 8


def _update_scores(conn: psycopg.Connection, raw_games: list[dict]) -> int:
    n = 0
    for g in raw_games:
        game_pk = g.get("gamePk")
        score = parse_game_score(g)
        if game_pk is None or score is None:
            continue
        home, away = score
        n += conn.execute(
            "UPDATE games SET home_score = %s, away_score = %s WHERE id = %s",
            (home, away, game_pk),
        ).rowcount
    return n


def cmd_backfill_scores(args: argparse.Namespace) -> None:
    start: date = args.start
    end: date = args.end
    if end < start:
        raise SystemExit(f"[backfill-scores] --end {end} before --start {start}")
    dates = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    print(f"[backfill-scores] {len(dates)} dates ({start} → {end}) with {MAX_WORKERS} workers…")

    conn = get_connection()
    total = 0
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for raw in pool.map(fetch_schedule, dates):
                total += _update_scores(conn, raw)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Backfilled scores for {total} games across {len(dates)} dates.")
