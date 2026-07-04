"""refresh-batted-ball-events: build the per-batted-ball xHR training corpus.

Reads pitch-level Statcast (cached by pybaseball) and writes ONE ROW PER BATTED
BALL into batted_ball_events — the training data for the learned xHR model (Phase 2).
Rebuilds a season in place (delete-then-insert), so it's idempotent. Uses COPY
because a season is ~120k rows.
"""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.statcast import batted_ball_events, pull_statcast_chunks

_COLS = [
    "season", "player_id", "game_pk", "park", "launch_speed", "launch_angle",
    "spray_deg", "bb_type", "estimated_woba", "hit_distance", "is_hr",
]


def cmd_refresh_batted_ball_events(args: argparse.Namespace) -> None:
    season = getattr(args, "season", None) or eastern_today().year
    print(f"[refresh-batted-ball-events] Building per-BB xHR corpus for {season}…")
    chunks = list(pull_statcast_chunks(season))
    rows = batted_ball_events(chunks, season)

    conn = get_connection()
    try:
        # Rebuild the season in place so re-runs are idempotent (no natural key).
        conn.execute("DELETE FROM batted_ball_events WHERE season = %s", (season,))
        with conn.cursor() as cur:
            with cur.copy(
                f"COPY batted_ball_events ({', '.join(_COLS)}) FROM STDIN"
            ) as cp:
                for r in rows:
                    cp.write_row([r[c] for c in _COLS])
        conn.commit()
        n_hr = sum(1 for r in rows if r["is_hr"])
        print(
            f"[refresh-batted-ball-events] wrote {len(rows):,} batted balls "
            f"({n_hr:,} HR, {n_hr / len(rows) * 100:.1f}%) for {season}"
            if rows else
            f"[refresh-batted-ball-events] no batted balls found for {season}"
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
