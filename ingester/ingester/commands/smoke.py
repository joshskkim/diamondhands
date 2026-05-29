"""smoke commands: smoke-skills and smoke-slate sanity checks."""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection

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


def cmd_smoke_slate(args: argparse.Namespace) -> None:
    """Print the slate for a given date: matchup, stadium, dome, weather, and both probable SPs."""
    conn = get_connection()
    today = args.date if args.date is not None else eastern_today()

    rows = conn.execute(
        """
        SELECT
            t_home.abbreviation   AS home,
            t_away.abbreviation   AS away,
            s.name                AS stadium,
            s.is_dome,
            g.temperature_f,
            g.wind_speed_mph,
            g.wind_direction_degrees,
            p_home.full_name      AS home_sp,
            p_away.full_name      AS away_sp,
            g.start_time_utc,
            g.status
        FROM games g
        JOIN teams   t_home ON t_home.id = g.home_team_id
        JOIN teams   t_away ON t_away.id = g.away_team_id
        JOIN stadiums s     ON s.id      = g.stadium_id
        LEFT JOIN players p_home ON p_home.id = g.home_probable_pitcher_id
        LEFT JOIN players p_away ON p_away.id = g.away_probable_pitcher_id
        WHERE g.game_date = %s
        ORDER BY g.start_time_utc
        """,
        (today,),
    ).fetchall()

    conn.close()

    if not rows:
        print(f"\n[smoke-slate] No games found for {today}.")
        return

    print(f"\n=== Slate for {today} — {len(rows)} game(s) ===")
    hdr = (
        f"{'Matchup':<12} {'Stadium':<30} {'Dome':<5} "
        f"{'Temp':>6} {'Wind':>11}  {'Home SP':<24} {'Away SP':<24}"
    )
    print(hdr)
    print("-" * len(hdr))

    for home, away, stadium, is_dome, temp, wind_spd, wind_dir, home_sp, away_sp, start, status in rows:
        matchup  = f"{away}@{home}"
        dome_str = "YES" if is_dome else "no"
        temp_str = f"{temp}°F"  if temp      is not None else "—"
        wind_str = f"{wind_spd}/{wind_dir}°" if wind_spd is not None else "—"
        print(
            f"{matchup:<12} {(stadium or '?'):<30} {dome_str:<5} "
            f"{temp_str:>6} {wind_str:>11}  "
            f"{(home_sp or 'TBA'):<24} {(away_sp or 'TBA'):<24}"
        )
    print()
