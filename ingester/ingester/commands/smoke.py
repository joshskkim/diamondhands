"""smoke-skills: Sanity-check batter_skill and pitcher_skill tables."""
from __future__ import annotations

import argparse

from ingester.db import get_connection

MIN_PA_L30 = 50   # minimum L30 PA for batter smoke check
MIN_BF     = 50   # minimum BF for pitcher smoke check


def cmd_smoke_skills(args: argparse.Namespace) -> None:
    conn = get_connection()

    # --- Top 10 batters by xwoba_l30 (min 50 PA in L30) -------------------
    batters = conn.execute(
        """
        SELECT
            p.full_name,
            bs.plate_appearances        AS pa_season,
            bs.pa_l30,
            bs.xwoba_l30,
            bs.xwoba                    AS xwoba_season,
            bs.k_rate,
            bs.bb_rate
        FROM batter_skill bs
        JOIN players p ON p.id = bs.player_id
        WHERE bs.pa_l30 >= %s
          AND bs.xwoba_l30 IS NOT NULL
        ORDER BY bs.xwoba_l30 DESC
        LIMIT 10
        """,
        (MIN_PA_L30,),
    ).fetchall()

    print("\n=== Top 10 Batters by xwOBA (last 30 days, min 50 PA) ===")
    print(f"{'Rank':<5} {'Player':<25} {'xwOBA_L30':>9} {'xwOBA_Ssn':>9} "
          f"{'K%':>6} {'BB%':>6} {'PA_L30':>7} {'PA_Ssn':>7}")
    print("-" * 75)
    for i, r in enumerate(batters, 1):
        name, pa_s, pa_l, xw_l, xw_s, k, bb = r
        print(
            f"{i:<5} {(name or '?'):<25} "
            f"{(xw_l or 0):>9.4f} {(xw_s or 0):>9.4f} "
            f"{(k or 0)*100:>5.1f}% {(bb or 0)*100:>5.1f}% "
            f"{(pa_l or 0):>7} {(pa_s or 0):>7}"
        )

    # --- Top 10 pitchers by K% vs RHB (min 50 BF) -------------------------
    pitchers = conn.execute(
        """
        SELECT
            p.full_name,
            ps.batters_faced,
            ps.k_rate,
            ps.bb_rate,
            ps.xwoba_against,
            ps.hr_per_pa
        FROM pitcher_skill ps
        JOIN players p ON p.id = ps.player_id
        WHERE ps.vs_handedness = 'R'
          AND ps.batters_faced >= %s
          AND ps.k_rate IS NOT NULL
        ORDER BY ps.k_rate DESC
        LIMIT 10
        """,
        (MIN_BF,),
    ).fetchall()

    print(f"\n=== Top 10 Pitchers by K% vs RHB (min {MIN_BF} BF) ===")
    print(f"{'Rank':<5} {'Player':<25} {'K%':>6} {'BB%':>6} "
          f"{'xwOBA_vs':>9} {'HR/PA':>7} {'BF':>6}")
    print("-" * 65)
    for i, r in enumerate(pitchers, 1):
        name, bf, k, bb, xw, hr_pa = r
        print(
            f"{i:<5} {(name or '?'):<25} "
            f"{(k or 0)*100:>5.1f}% {(bb or 0)*100:>5.1f}% "
            f"{(xw or 0):>9.4f} {(hr_pa or 0):>7.4f} {(bf or 0):>6}"
        )

    conn.close()
    print()
