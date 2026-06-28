"""live-refresh: high-cadence in-game state (running score + current inning) into the
games.live_* columns, for the home board's real-time bet trackers.

Mirrors backfill-scores' single-fetch-then-UPDATE shape, but:
  - writes the live_* columns, NOT the Final home_score/away_score (those stay the
    grading source of truth — see V60__live_game_state.sql);
  - does NOT gate on Final, so in-progress games update every tick;
  - is meant to run frequently. To get a ~30s cadence without paying `docker compose
    run` container startup each tick, it can loop internally (--loop) for a bounded
    window (--for-minutes), then exit — cron tiles back-to-back loops across the game
    window (see deploy/crontab.example).
"""
from __future__ import annotations

import argparse
import time
from datetime import date

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.mlb_api import fetch_schedule, parse_game_linescore_live
from ingester.projection.constants import DEAD_GAME_STATUSES

# Hydrate the linescore so we get currentInning / inningState / running runs in one call.
_LIVE_HYDRATE = "linescore"


def _update_live(conn: psycopg.Connection, raw_games: list[dict]) -> int:
    """Write live_* state for every in-progress game. Returns rows updated."""
    n = 0
    for g in raw_games:
        game_pk = g.get("gamePk")
        if game_pk is None:
            continue
        if (g.get("status") or {}).get("detailedState") in DEAD_GAME_STATUSES:
            continue
        live = parse_game_linescore_live(g)
        if live is None:
            continue
        n += conn.execute(
            "UPDATE games SET live_home_score = %s, live_away_score = %s,"
            " live_current_inning = %s, live_inning_state = %s, live_is_top = %s,"
            " live_updated_at = NOW() WHERE id = %s",
            (
                live["home"], live["away"], live["inning"],
                live["inning_state"], live["is_top"], game_pk,
            ),
        ).rowcount
    return n


def _tick(conn: psycopg.Connection, game_date: date) -> int:
    raw = fetch_schedule(game_date, hydrate=_LIVE_HYDRATE)
    n = _update_live(conn, raw)
    conn.commit()
    return n


def cmd_live_refresh(args: argparse.Namespace) -> None:
    game_date = getattr(args, "date", None) or eastern_today()
    loop: bool = getattr(args, "loop", False)
    interval: int = getattr(args, "interval_seconds", 30)
    for_minutes: int = getattr(args, "for_minutes", 30)

    conn = get_connection()
    try:
        if not loop:
            n = _tick(conn, game_date)
            print(f"[live-refresh] updated {n} in-progress game(s).")
            return

        deadline = time.monotonic() + for_minutes * 60
        ticks = 0
        while True:
            try:
                n = _tick(conn, game_date)
                ticks += 1
                print(f"[live-refresh] tick {ticks}: {n} in-progress game(s).", flush=True)
            except Exception as exc:  # noqa: BLE001 — one bad poll shouldn't kill the loop
                conn.rollback()
                print(f"[live-refresh] tick failed: {exc}", flush=True)
            if time.monotonic() + interval >= deadline:
                break
            time.sleep(interval)
        print(f"[live-refresh] done after {ticks} tick(s) over ~{for_minutes}m.")
    finally:
        conn.close()
