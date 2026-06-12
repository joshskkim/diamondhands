"""refresh-batted-ball: aggregate per-batter batted-ball / spray profiles from Statcast.

Reads pitch-level Statcast (cached by pybaseball) and writes one batter_batted_ball row
per batter: spray split (pull/center/oppo), batted-ball mix (GB/LD/FB/PU), and contact
quality (avg EV / LA, hard-hit, barrels). Foundation for a batter-specific park / HR model.
"""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.statcast import agg_batter_batted_ball, pull_statcast_chunks

# Below this many balls in play, the spray/quality split is too noisy to store.
MIN_BIP = 50


def cmd_refresh_batted_ball(args: argparse.Namespace) -> None:
    season = getattr(args, "season", None) or eastern_today().year
    print(f"[refresh-batted-ball] Aggregating batted-ball profiles for {season}…")
    chunks = list(pull_statcast_chunks(season))
    rows = agg_batter_batted_ball(chunks)

    conn = get_connection()
    written = 0
    skipped = 0
    try:
        known = {r[0] for r in conn.execute("SELECT id FROM players").fetchall()}
        for r in rows:
            if r["bip"] < MIN_BIP or r["player_id"] not in known:
                skipped += 1
                continue
            conn.execute(
                """
                INSERT INTO batter_batted_ball (
                    player_id, season, bip, pull_pct, center_pct, oppo_pct,
                    gb_pct, ld_pct, fb_pct, pu_pct,
                    avg_launch_speed, avg_launch_angle, hard_hit_pct, barrel_pct, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    bip = EXCLUDED.bip,
                    pull_pct = EXCLUDED.pull_pct, center_pct = EXCLUDED.center_pct,
                    oppo_pct = EXCLUDED.oppo_pct,
                    gb_pct = EXCLUDED.gb_pct, ld_pct = EXCLUDED.ld_pct,
                    fb_pct = EXCLUDED.fb_pct, pu_pct = EXCLUDED.pu_pct,
                    avg_launch_speed = EXCLUDED.avg_launch_speed,
                    avg_launch_angle = EXCLUDED.avg_launch_angle,
                    hard_hit_pct = EXCLUDED.hard_hit_pct, barrel_pct = EXCLUDED.barrel_pct,
                    updated_at = NOW()
                """,
                (
                    r["player_id"], season, r["bip"], r["pull_pct"], r["center_pct"],
                    r["oppo_pct"], r["gb_pct"], r["ld_pct"], r["fb_pct"], r["pu_pct"],
                    r["avg_launch_speed"], r["avg_launch_angle"], r["hard_hit_pct"],
                    r["barrel_pct"],
                ),
            )
            written += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[refresh-batted-ball] {written} batter row(s) written (min {MIN_BIP} BIP); "
          f"{skipped} below threshold / unknown.")
