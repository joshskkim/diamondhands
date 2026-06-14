"""refresh-bat-tracking: aggregate per-batter bat-tracking metrics from Statcast.

Bat speed / swing length / attack angle exist from 2024 on (earlier seasons simply
produce zero rows). Reads the cached pitch chunks — no new API pulls. Feeds the
power (ISO) prior and, later, the whiff side of the K model.
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection
from ingester.statcast import agg_batter_bat_tracking, pull_statcast_chunks

# Below this many measured swings the averages are too noisy to store.
MIN_SWINGS = 50


def cmd_refresh_bat_tracking(args: argparse.Namespace) -> None:
    season = getattr(args, "season", 2025)
    print(f"[refresh-bat-tracking] Aggregating bat-tracking for {season}…")
    chunks = list(pull_statcast_chunks(season))
    rows = agg_batter_bat_tracking(chunks)

    conn = get_connection()
    written = skipped = 0
    try:
        known = {r[0] for r in conn.execute("SELECT id FROM players").fetchall()}
        for r in rows:
            if r["swings"] < MIN_SWINGS or r["player_id"] not in known:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO batter_bat_tracking (
                    player_id, season, swings, avg_bat_speed, fast_swing_rate,
                    avg_swing_length, avg_attack_angle, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    swings = EXCLUDED.swings,
                    avg_bat_speed = EXCLUDED.avg_bat_speed,
                    fast_swing_rate = EXCLUDED.fast_swing_rate,
                    avg_swing_length = EXCLUDED.avg_swing_length,
                    avg_attack_angle = EXCLUDED.avg_attack_angle,
                    updated_at = NOW()
                """,
                (
                    r["player_id"], season, r["swings"], r["avg_bat_speed"],
                    r["fast_swing_rate"], r["avg_swing_length"], r["avg_attack_angle"],
                ),
            )
            written += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[refresh-bat-tracking] {written} batter row(s) written (min {MIN_SWINGS} "
          f"swings); {skipped} below threshold / unknown.")
