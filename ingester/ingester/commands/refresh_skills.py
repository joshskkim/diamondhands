"""refresh-skills: Aggregate player_game_stats into batter_skill and pitcher_skill."""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.projection.constants import (
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_XWOBA,
    L30_MIN_PA,
    MIN_PA_BATTER_SEASON,
)
from ingester.statcast import (
    _terminal_pa,
    agg_pitcher_vs_handedness,
    pull_statcast_chunks,
    require_valid_season,
    season_boundaries,
)

MIN_BF_PITCHER = 50    # minimum BF vs a handedness for pitcher_skill


def _rolling_l30_window(season: int) -> tuple[date, date]:
    """Last 30 calendar days ending today (clamped to the season schedule)."""
    start, end = season_boundaries(season)
    as_of = min(eastern_today(), end)
    as_of = max(as_of, start)
    l30_end = as_of
    l30_start = max(start, as_of - timedelta(days=30))
    return l30_start, l30_end


def _resolve_l30_fields(
    l30_row: tuple | None,
    *,
    season_xwoba: float | None,
    season_k_rate: float | None,
    season_iso: float | None,
) -> tuple[int | None, float | None, float | None, float | None, float | None]:
    """
    Return (pa_l30, xwoba_l30, k_rate_l30, iso_l30) for batter_skill.

    If pa_l30 < L30_MIN_PA, all L30 fields are NULL (insufficient recent sample).
    If pa_l30 >= L30_MIN_PA, every L30 metric is populated (season fallback if needed).
    """
    if l30_row is None:
        return None, None, None, None

    pa_l30 = int(l30_row[1] or 0)
    if pa_l30 < L30_MIN_PA:
        return None, None, None, None

    xwoba_l30 = float(l30_row[2]) if l30_row[2] is not None else season_xwoba
    k_rate_l30 = float(l30_row[3]) if l30_row[3] is not None else season_k_rate
    iso_l30 = float(l30_row[4]) if l30_row[4] is not None else season_iso

    if xwoba_l30 is not None:
        xwoba_l30 = round(xwoba_l30, 4)
    if k_rate_l30 is not None:
        k_rate_l30 = round(k_rate_l30, 4)
    if iso_l30 is not None:
        iso_l30 = round(iso_l30, 4)

    return pa_l30, xwoba_l30, k_rate_l30, iso_l30


# ---------------------------------------------------------------------------
# Batter skill
# ---------------------------------------------------------------------------

def _aggregate_batter_skill(conn: psycopg.Connection, season: int) -> int:
    """
    Read player_game_stats, compute season + L30 aggregates, upsert batter_skill.

    Season: players with any PA in the season window. Below MIN_PA_BATTER_SEASON PA,
    season rate stats are set to league averages (still projected for callups).

    L30: rolling 30 days ending today (not season end). Requires L30_MIN_PA to store
    L30 columns; otherwise they are NULL.
    """
    start, end = season_boundaries(season)
    l30_start, l30_end = _rolling_l30_window(season)

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
        HAVING SUM(plate_appearances) >= 1
        """,
        (start, end),
    ).fetchall()

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
        (l30_start, l30_end),
    ).fetchall()

    l30_by_pid: dict[int, tuple] = {r[0]: r for r in l30_rows}

    rows_written = 0
    with conn.cursor() as cur:
        for r in season_rows:
            pid, pa, ab, hits, hr, tb, k, bb, xwoba, woba = r
            ab = int(ab or 0)
            hits = int(hits or 0)
            hr = int(hr or 0)
            tb = int(tb or 0)
            k = int(k or 0)
            bb = int(bb or 0)
            pa = int(pa or 0)

            use_league = pa < MIN_PA_BATTER_SEASON
            if use_league:
                xwoba_f = LEAGUE_XWOBA
                woba_f = LEAGUE_XWOBA
                k_rate = round(LEAGUE_K_PER_PA, 4)
                bb_rate = round(0.085, 4)  # ~league BB%
                iso = round(LEAGUE_ISO, 4)
                babip = None
            else:
                xwoba_f = float(xwoba) if xwoba is not None else LEAGUE_XWOBA
                woba_f = float(woba) if woba is not None else LEAGUE_XWOBA
                k_rate = round(k / pa, 4) if pa > 0 else None
                bb_rate = round(bb / pa, 4) if pa > 0 else None
                iso = round((tb - hits) / ab, 4) if ab > 0 else round(LEAGUE_ISO, 4)
                babip_d = ab - k - hr
                babip = round((hits - hr) / babip_d, 4) if babip_d > 0 else None

            pa_l30, xwoba_l30, k_rate_l30, iso_l30 = _resolve_l30_fields(
                l30_by_pid.get(pid),
                season_xwoba=xwoba_f,
                season_k_rate=k_rate,
                season_iso=iso,
            )

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
                    pid,
                    season,
                    pa,
                    xwoba_f,
                    woba_f,
                    k_rate,
                    bb_rate,
                    iso,
                    babip,
                    xwoba_l30,
                    k_rate_l30,
                    iso_l30,
                    pa_l30,
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

    require_valid_season(season, cmd="refresh-skills")

    l30_start, l30_end = _rolling_l30_window(season)
    print(
        f"[refresh-skills] L30 window: {l30_start} → {l30_end} "
        f"(NULL L30 if pa_l30 < {L30_MIN_PA})"
    )

    conn = get_connection()

    print(f"[refresh-skills] Aggregating batter_skill for {season}…")
    n_batters = _aggregate_batter_skill(conn, season)
    conn.commit()

    with_l30 = conn.execute(
        "SELECT COUNT(*) FROM batter_skill WHERE pa_l30 IS NOT NULL"
    ).fetchone()[0]
    print(
        f"  → {n_batters} batters written "
        f"(min {MIN_PA_BATTER_SEASON} PA for season rates; {with_l30} with L30)"
    )

    print(f"[refresh-skills] Aggregating pitcher_skill for {season}…")
    n_pitchers = _aggregate_pitcher_skill(conn, season)
    conn.commit()
    print(f"  → {n_pitchers} pitcher×hand rows written (min {MIN_BF_PITCHER} BF)")

    conn.close()
    print("[refresh-skills] Done.")
