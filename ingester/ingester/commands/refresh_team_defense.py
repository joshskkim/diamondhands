"""refresh-team-defense: aggregate per-team, per-day defensive hit suppression from Statcast.

For every in-park ball in play a team's defense faced, compares the actual non-HR hits
allowed to the sum of Statcast xBA (estimated_ba_using_speedangle) on those balls — a
team that allows fewer hits than xBA expects is suppressing hits with defense (contact
quality held constant by xBA). Writes one team_defense_daily row per (team, game date);
the projector sums season-to-date rows BEFORE a slate (leak-free) and shrinks toward
league average to scale opposing batters' non-HR hit rate. HR is excluded (not fielded).
"""
from __future__ import annotations

import argparse

from ingester.db import build_team_abbrev_map, eastern_today, get_connection
from ingester.statcast import agg_team_defense_daily, pull_statcast_chunks


def cmd_refresh_team_defense(args: argparse.Namespace) -> None:
    season = getattr(args, "season", None) or eastern_today().year
    print(f"[refresh-team-defense] Aggregating team defense for {season}…")
    chunks = list(pull_statcast_chunks(season))

    conn = get_connection()
    written = 0
    try:
        abbrev_to_id = build_team_abbrev_map(conn)
        rows = agg_team_defense_daily(chunks, abbrev_to_id)
        for r in rows:
            conn.execute(
                """
                INSERT INTO team_defense_daily (
                    team_id, game_date, bip, act_hits, exp_hits, computed_at
                )
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (team_id, game_date) DO UPDATE SET
                    bip = EXCLUDED.bip,
                    act_hits = EXCLUDED.act_hits,
                    exp_hits = EXCLUDED.exp_hits,
                    computed_at = NOW()
                """,
                (r["team_id"], r["game_date"], r["bip"], r["act_hits"], r["exp_hits"]),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()

    print(f"[refresh-team-defense] Wrote {written} (team, day) rows for {season}.")
