"""refresh-skills: Aggregate player_game_stats into batter_skill and pitcher_skill."""
from __future__ import annotations

import argparse
from datetime import timedelta

import psycopg

from ingester.db import get_connection
from ingester.statcast import (
    SEASON_BOUNDARIES,
    _terminal_pa,
    agg_pitcher_vs_handedness,
    pull_statcast_chunks,
)

MIN_PA_BATTER  = 100   # minimum full-season PA for batter_skill
MIN_BF_PITCHER = 50    # minimum BF vs a handedness for pitcher_skill


# ---------------------------------------------------------------------------
# Batter skill
# ---------------------------------------------------------------------------

def _aggregate_batter_skill(conn: psycopg.Connection, season: int) -> int:
    """
    Read player_game_stats, compute season + L30 aggregates, upsert batter_skill.
    Returns number of rows written.
    """
    start, end = SEASON_BOUNDARIES[season]
    l30_start = end - timedelta(days=30)

    # Full-season aggregation
    season_rows = conn.execute(
        """
        SELECT
            player_id,
            SUM(plate_appearances)                                             AS pa,
            SUM(at_bats)                                                       AS ab,
            SUM(hits)                                                          AS hits,
            SUM(home_runs)                                                     AS hr,
            SUM(total_bases)                                                   AS tb,
            SUM(strikeouts)                                                    AS k,
            SUM(walks)                                                         AS bb,
            SUM(xwoba * plate_appearances) / NULLIF(SUM(plate_appearances), 0) AS xwoba,
            SUM(woba  * plate_appearances) / NULLIF(SUM(plate_appearances), 0) AS woba
        FROM player_game_stats
        WHERE game_date BETWEEN %s AND %s
          AND plate_appearances IS NOT NULL
        GROUP BY player_id
        HAVING SUM(plate_appearances) >= %s
        """,
        (start, end, MIN_PA_BATTER),
    ).fetchall()

    # L30 aggregation (no min-PA floor so every player who had recent games appears)
    l30_rows = conn.execute(
        """
        SELECT
            player_id,
            SUM(plate_appearances)                                                  AS pa_l30,
            SUM(xwoba * plate_appearances) / NULLIF(SUM(plate_appearances), 0)      AS xwoba_l30,
            SUM(strikeouts)::numeric / NULLIF(SUM(plate_appearances), 0)            AS k_rate_l30,
            SUM(total_bases - hits)::numeric / NULLIF(SUM(at_bats), 0)             AS iso_l30
        FROM player_game_stats
        WHERE game_date BETWEEN %s AND %s
          AND plate_appearances IS NOT NULL
        GROUP BY player_id
        """,
        (l30_start, end),
    ).fetchall()

    l30_by_pid: dict[int, tuple] = {r[0]: r for r in l30_rows}

    rows_written = 0
    with conn.cursor() as cur:
        for r in season_rows:
            pid, pa, ab, hits, hr, tb, k, bb, xwoba, woba = r
            ab   = int(ab   or 0)
            hits = int(hits or 0)
            hr   = int(hr   or 0)
            tb   = int(tb   or 0)
            k    = int(k    or 0)
            bb   = int(bb   or 0)
            pa   = int(pa   or 0)

            k_rate  = round(k / pa, 4)  if pa > 0 else None
            bb_rate = round(bb / pa, 4) if pa > 0 else None
            iso     = round((tb - hits) / ab, 4) if ab > 0 else None
            babip_d = ab - k - hr
            babip   = round((hits - hr) / babip_d, 4) if babip_d > 0 else None

            l30 = l30_by_pid.get(pid)
            pa_l30     = int(l30[1])        if l30 and l30[1] is not None else None
            xwoba_l30  = round(float(l30[2]), 4) if l30 and l30[2] is not None else None
            k_rate_l30 = round(float(l30[3]), 4) if l30 and l30[3] is not None else None
            iso_l30    = round(float(l30[4]), 4) if l30 and l30[4] is not None else None

            cur.execute(
                """
                INSERT INTO batter_skill (
                    player_id, season, plate_appearances,
                    xwoba, woba, k_rate, bb_rate, iso, babip,
                    xwoba_l30, k_rate_l30, iso_l30, pa_l30,
                    updated_at
                )
                VALUES (
                    %s, %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    NOW()
                )
                ON CONFLICT (player_id) DO UPDATE
                    SET season            = EXCLUDED.season,
                        plate_appearances = EXCLUDED.plate_appearances,
                        xwoba             = EXCLUDED.xwoba,
                        woba              = EXCLUDED.woba,
                        k_rate            = EXCLUDED.k_rate,
                        bb_rate           = EXCLUDED.bb_rate,
                        iso               = EXCLUDED.iso,
                        babip             = EXCLUDED.babip,
                        xwoba_l30         = EXCLUDED.xwoba_l30,
                        k_rate_l30        = EXCLUDED.k_rate_l30,
                        iso_l30           = EXCLUDED.iso_l30,
                        pa_l30            = EXCLUDED.pa_l30,
                        updated_at        = NOW()
                """,
                (
                    pid, season, pa,
                    float(xwoba) if xwoba is not None else None,
                    float(woba)  if woba  is not None else None,
                    k_rate, bb_rate, iso, babip,
                    xwoba_l30, k_rate_l30, iso_l30, pa_l30,
                ),
            )
            rows_written += 1

    return rows_written


# ---------------------------------------------------------------------------
# Pitcher skill (re-reads cached Statcast for handedness splits)
# ---------------------------------------------------------------------------

def _aggregate_pitcher_skill(conn: psycopg.Connection, season: int) -> int:
    """
    Re-aggregate pitcher_skill from pybaseball's disk cache (fast after backfill).
    Returns number of rows written.
    """
    print("  [pitcher] Reading Statcast cache for handedness splits…")
    pa_chunks = []
    for chunk_df in pull_statcast_chunks(season):
        pa_chunks.append(_terminal_pa(chunk_df))

    ph_rows = agg_pitcher_vs_handedness(pa_chunks)
    ph_rows = [r for r in ph_rows if r["batters_faced"] >= MIN_BF_PITCHER]
    if not ph_rows:
        return 0

    for r in ph_rows:
        r["season"] = season

    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(ph_rows), CHUNK):
            cur.executemany(
                """
                INSERT INTO pitcher_skill (
                    player_id, season, vs_handedness,
                    batters_faced, woba_against, xwoba_against,
                    k_rate, bb_rate, hr_per_pa, hits_per_pa, updated_at
                )
                VALUES (
                    %(player_id)s, %(season)s, %(vs_handedness)s,
                    %(batters_faced)s, %(woba_against)s, %(xwoba_against)s,
                    %(k_rate)s, %(bb_rate)s, %(hr_per_pa)s, %(hits_per_pa)s, NOW()
                )
                ON CONFLICT (player_id, season, vs_handedness) DO UPDATE
                    SET batters_faced  = EXCLUDED.batters_faced,
                        woba_against   = EXCLUDED.woba_against,
                        xwoba_against  = EXCLUDED.xwoba_against,
                        k_rate         = EXCLUDED.k_rate,
                        bb_rate        = EXCLUDED.bb_rate,
                        hr_per_pa      = EXCLUDED.hr_per_pa,
                        hits_per_pa    = EXCLUDED.hits_per_pa,
                        updated_at     = NOW()
                """,
                ph_rows[i : i + CHUNK],
            )

    return len(ph_rows)


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def cmd_refresh_skills(args: argparse.Namespace) -> None:
    season: int = getattr(args, "season", 2025)

    if season not in SEASON_BOUNDARIES:
        import sys
        sys.exit(f"[refresh-skills] Season {season} not supported.")

    conn = get_connection()

    # Batter skill
    print(f"[refresh-skills] Aggregating batter_skill for {season}…")
    n_batters = _aggregate_batter_skill(conn, season)
    conn.commit()
    print(f"  → {n_batters} batters written (min {MIN_PA_BATTER} PA)")

    # Pitcher skill (reads from pybaseball cache)
    print(f"[refresh-skills] Aggregating pitcher_skill for {season}…")
    n_pitchers = _aggregate_pitcher_skill(conn, season)
    conn.commit()
    print(f"  → {n_pitchers} pitcher×hand rows written (min {MIN_BF_PITCHER} BF)")

    conn.close()
    print("[refresh-skills] Done.")
