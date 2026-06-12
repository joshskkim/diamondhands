"""refresh-bullpen: Aggregate relief-pitching skill per team into bullpen_skill.

A relief PA is any plate appearance charged to a pitcher who was NOT that
game-side's starting pitcher. Starters are identified from the Statcast
pitch-level cache (the pitcher who threw the first pitch of a given half-inning
side); everything else is relief. We then group by the pitching team and the
batter's effective handedness, mirroring the pitcher_skill aggregation but
team-level instead of pitcher-level.

The run/score projection model is a later consumer of this table; this command
is purely the data layer.
"""
from __future__ import annotations

import argparse

import psycopg

from ingester.db import build_team_abbrev_map, eastern_today, get_connection
from ingester.statcast import agg_bullpen_vs_handedness, require_valid_season
from ingester.commands.refresh_skills import load_all_statcast_pa

MIN_BF_BULLPEN = 50    # minimum relief BF vs a handedness for bullpen_skill


def compute_bullpen_skill_rows(
    season: int,
    all_pa: list,
    abbrev_to_id: dict[str, int],
) -> list[dict]:
    """
    Compute bullpen_skill rows from pre-loaded Statcast terminal-PA DataFrames.

    Returns a list of dicts (one per team×hand that clears MIN_BF_BULLPEN), each
    carrying a 'season' key, ready for upsert into bullpen_skill.
    """
    rows = agg_bullpen_vs_handedness(all_pa, abbrev_to_id)
    rows = [r for r in rows if r["bf"] >= MIN_BF_BULLPEN]
    for r in rows:
        r["season"] = season
    return rows


def _aggregate_bullpen_skill(conn: psycopg.Connection, season: int) -> int:
    """Re-aggregate bullpen_skill from pybaseball's disk cache (fast after backfill)."""
    print("  [bullpen] Reading Statcast cache for relief handedness splits…")
    all_pa = load_all_statcast_pa(season)
    abbrev_to_id = build_team_abbrev_map(conn)
    rows = compute_bullpen_skill_rows(season, all_pa, abbrev_to_id)
    if not rows:
        return 0

    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(rows), CHUNK):
            cur.executemany(
                """
                INSERT INTO bullpen_skill (
                    team_id, season, vs_hand,
                    bf, hits_per_pa, hr_per_pa, k_rate, updated_at
                )
                VALUES (
                    %(team_id)s, %(season)s, %(vs_hand)s,
                    %(bf)s, %(hits_per_pa)s, %(hr_per_pa)s, %(k_rate)s, NOW()
                )
                ON CONFLICT (team_id, season, vs_hand) DO UPDATE
                    SET bf          = EXCLUDED.bf,
                        hits_per_pa = EXCLUDED.hits_per_pa,
                        hr_per_pa   = EXCLUDED.hr_per_pa,
                        k_rate      = EXCLUDED.k_rate,
                        updated_at  = NOW()
                """,
                rows[i : i + CHUNK],
            )

    return len(rows)


def cmd_refresh_bullpen(args: argparse.Namespace) -> None:
    season: int = getattr(args, "season", None) or eastern_today().year

    require_valid_season(season, cmd="refresh-bullpen")

    conn = get_connection()
    print(f"[refresh-bullpen] Aggregating bullpen_skill for {season}…")
    n_rows = _aggregate_bullpen_skill(conn, season)
    conn.commit()
    print(f"  → {n_rows} team×hand rows written (min {MIN_BF_BULLPEN} relief BF)")
    conn.close()
    print("[refresh-bullpen] Done.")
