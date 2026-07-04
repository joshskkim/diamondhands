"""refresh-batted-ball: aggregate per-batter batted-ball / spray profiles from Statcast.

Reads pitch-level Statcast (cached by pybaseball) and writes one batter_batted_ball row
per batter: spray split (pull/center/oppo), batted-ball mix (GB/LD/FB/PU), and contact
quality (avg EV / LA, hard-hit, barrels). Foundation for a batter-specific park / HR model.
"""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.statcast import (
    agg_batter_batted_ball,
    agg_batter_hr_distance,
    agg_batter_spray_bins,
    agg_pitcher_batted_ball,
    pull_statcast_chunks,
)

# Below this many balls in play, the spray/quality split is too noisy to store.
MIN_BIP = 50
# Below this many measured home runs, the distance average/percentile is too thin to store.
MIN_HR = 3
# Per (pitcher, hand) BIP floor for contact-quality-allowed (Lever 1). The split is
# thinner than a batter's season total, so this is a floor we may raise; the prior
# loader's heavier regression (PITCHER_BARREL_REGRESSION_BIP) is the real guard.
MIN_PITCHER_BIP = 50


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

        # Spray-direction bins (hot-zone visual). Same per-player BIP gate as the
        # profile: a player's bins are written only when his season total clears
        # MIN_BIP, so the heatmap never renders a 12-ball sample.
        bin_rows = agg_batter_spray_bins(chunks)
        eligible = {r["player_id"] for r in rows if r["bip"] >= MIN_BIP} & known
        bins_written = 0
        for b in bin_rows:
            if b["player_id"] not in eligible:
                continue
            conn.execute(
                """
                INSERT INTO batter_spray_bins (
                    player_id, season, bin, bip, hr, avg_distance_ft, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season, bin) DO UPDATE SET
                    bip = EXCLUDED.bip,
                    hr = EXCLUDED.hr,
                    avg_distance_ft = EXCLUDED.avg_distance_ft,
                    updated_at = NOW()
                """,
                (b["player_id"], season, b["bin"], b["bip"], b["hr"],
                 b["avg_distance_ft"]),
            )
            bins_written += 1

        # Per-batter HR distance (long-ball-upside tiebreaker on HR picks). HR-only, so it
        # has its own min-sample gate (MIN_HR measured HRs) rather than the BIP gate above.
        hr_rows = agg_batter_hr_distance(chunks)
        hr_written = 0
        for h in hr_rows:
            if h["hr_n"] < MIN_HR or h["player_id"] not in known:
                continue
            conn.execute(
                """
                INSERT INTO batter_hr_distance (
                    player_id, season, hr_n, avg_distance_ft, p90_distance_ft, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    hr_n = EXCLUDED.hr_n,
                    avg_distance_ft = EXCLUDED.avg_distance_ft,
                    p90_distance_ft = EXCLUDED.p90_distance_ft,
                    updated_at = NOW()
                """,
                (h["player_id"], season, h["hr_n"], h["avg_distance_ft"],
                 h["p90_distance_ft"]),
            )
            hr_written += 1

        # Pitcher contact-quality allowed (Lever 1), handedness-split. Same cached
        # chunks; gated per (pitcher, hand) on MIN_PITCHER_BIP.
        pitcher_rows = agg_pitcher_batted_ball(chunks)
        pitcher_written = 0
        for p in pitcher_rows:
            if p["bip"] < MIN_PITCHER_BIP or p["player_id"] not in known:
                continue
            conn.execute(
                """
                INSERT INTO pitcher_batted_ball (
                    player_id, season, vs_handedness, bip,
                    fb_pct, hard_hit_pct, barrel_pct, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season, vs_handedness) DO UPDATE SET
                    bip = EXCLUDED.bip,
                    fb_pct = EXCLUDED.fb_pct,
                    hard_hit_pct = EXCLUDED.hard_hit_pct,
                    barrel_pct = EXCLUDED.barrel_pct,
                    updated_at = NOW()
                """,
                (p["player_id"], season, p["vs_handedness"], p["bip"],
                 p["fb_pct"], p["hard_hit_pct"], p["barrel_pct"]),
            )
            pitcher_written += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[refresh-batted-ball] {written} batter row(s) written (min {MIN_BIP} BIP); "
          f"{skipped} below threshold / unknown; {bins_written} spray-bin row(s); "
          f"{hr_written} HR-distance row(s); "
          f"{pitcher_written} pitcher contact-quality row(s) (min {MIN_PITCHER_BIP} BIP).")
