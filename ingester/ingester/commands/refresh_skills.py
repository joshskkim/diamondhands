"""refresh-skills: Aggregate player_game_stats into batter_skill and pitcher_skill.

Public functions compute_batter_skill_rows and compute_pitcher_skill_rows are
imported by refresh-skill-snapshots for point-in-time snapshot generation.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd
import psycopg

from ingester.db import eastern_today, get_connection
from ingester.projection.constants import (
    LEAGUE_BB_PER_PA,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_WOBA,
    LEAGUE_XWOBA,
    L30_MIN_PA,
    MIN_PA_BATTER_SEASON,
    REGRESSION_K_BF,
    REGRESSION_K_PA,
    REGRESSION_K_PA_L30,
)
from ingester.projection.prior import ProjectionPrior
from ingester.statcast import (
    _terminal_pa,
    agg_batter_vs_pitcher_hand,
    agg_pitcher_vs_handedness,
    pull_statcast_chunks,
    require_valid_season,
    season_boundaries,
)

MIN_BF_PITCHER = 50    # minimum BF vs a handedness for pitcher_skill
MIN_PA_PLATOON = 25    # minimum PA vs a pitcher hand for batter_platoon_skill


def _regress(raw: float | None, league: float, weight_player: float) -> float:
    """
    Empirical-Bayes blend of a raw rate toward the league mean by sample weight.

    weight_player = n / (n + K); weight_league is the complement. A None raw rate
    (couldn't be computed from the sample) collapses to the full league mean.
    """
    if raw is None:
        return round(league, 4)
    return round(weight_player * raw + (1.0 - weight_player) * league, 4)


def _load_priors(
    conn: psycopg.Connection, season: int
) -> dict[int, ProjectionPrior]:
    """Marcel true-talent priors for the target season, keyed by player_id.

    Empty when refresh-priors hasn't run for this season; callers then fall back
    to the league mean (identical to pre-v2.4.0 behaviour).
    """
    rows = conn.execute(
        """
        SELECT player_id, proj_xwoba, proj_k_rate, proj_iso, proj_pa
        FROM batter_projection_prior
        WHERE season = %s
        """,
        (season,),
    ).fetchall()
    out: dict[int, ProjectionPrior] = {}
    for pid, xwoba, k_rate, iso, proj_pa in rows:
        if xwoba is None or k_rate is None or iso is None:
            continue
        out[int(pid)] = ProjectionPrior(
            xwoba=float(xwoba),
            k_rate=float(k_rate),
            iso=float(iso),
            proj_pa=int(proj_pa or 0),
        )
    return out


def _resolve_l30_fields(
    l30_row: tuple | None,
) -> tuple[int | None, float | None, float | None, float | None]:
    """
    Return (pa_l30, xwoba_l30, k_rate_l30, iso_l30) for batter_skill, regressed.

    If pa_l30 < L30_MIN_PA, all L30 fields are NULL (insufficient recent sample).
    Otherwise each metric is regressed toward its league mean using the smaller
    L30 regression constant (recent form should move faster than season).
    """
    if l30_row is None:
        return None, None, None, None

    pa_l30 = int(l30_row[1] or 0)
    if pa_l30 < L30_MIN_PA:
        return None, None, None, None

    weight = pa_l30 / (pa_l30 + REGRESSION_K_PA_L30)
    raw_xwoba_l30 = float(l30_row[2]) if l30_row[2] is not None else None
    raw_k_rate_l30 = float(l30_row[3]) if l30_row[3] is not None else None
    raw_iso_l30 = float(l30_row[4]) if l30_row[4] is not None else None

    return (
        pa_l30,
        _regress(raw_xwoba_l30, LEAGUE_XWOBA, weight),
        _regress(raw_k_rate_l30, LEAGUE_K_PER_PA, weight),
        _regress(raw_iso_l30, LEAGUE_ISO, weight),
    )


# ---------------------------------------------------------------------------
# Shared batter skill computation
# ---------------------------------------------------------------------------

def compute_batter_skill_rows(
    conn: psycopg.Connection,
    season: int,
    cutoff_date: date,
) -> list[dict]:
    """
    Compute batter skill rows using only game_date < cutoff_date (exclusive).

    For the live daily refresh, pass cutoff_date = eastern_today() + 1 day
    (so today's games are included).  For a weekly Monday snapshot, pass
    cutoff_date = that Monday (so games on Monday itself are excluded).

    Returns a list of dicts ready for upsert into batter_skill or
    batter_skill_snapshots.
    """
    start, end = season_boundaries(season)
    as_of = min(cutoff_date - timedelta(days=1), end)
    as_of = max(as_of, start)

    l30_start = max(start, as_of - timedelta(days=30))
    l30_end = as_of

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
        (start, as_of, MIN_PA_BATTER_SEASON),
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

    # v2.4.0: regress each player's season rates toward their Marcel true-talent
    # prior rather than the flat league mean. Falls back to league per-metric
    # when no prior exists (debutants) or refresh-priors hasn't run this season.
    priors = _load_priors(conn, season)

    rows: list[dict] = []
    for r in season_rows:
        pid, pa, ab, hits, hr, tb, k, bb, xwoba, woba = r
        ab = int(ab or 0)
        hits = int(hits or 0)
        hr = int(hr or 0)
        tb = int(tb or 0)
        k = int(k or 0)
        bb = int(bb or 0)
        pa = int(pa or 0)

        # Empirical-Bayes regression: blend each raw rate toward the league mean
        # by sample size. No more hard league-average fallback — a 50-PA player
        # lands ~80% league / 20% own, a 600-PA player ~25% league / 75% own.
        weight = pa / (pa + REGRESSION_K_PA)

        raw_xwoba = float(xwoba) if xwoba is not None else None
        raw_woba = float(woba) if woba is not None else None
        raw_k_rate = k / pa if pa > 0 else None
        raw_bb_rate = bb / pa if pa > 0 else None
        raw_iso = (tb - hits) / ab if ab > 0 else None

        # Regress the three model-driving metrics toward the player's prior;
        # woba/bb_rate have no prior modeled, so they stay anchored to league.
        prior = priors.get(pid)
        tgt_xwoba = prior.xwoba if prior else LEAGUE_XWOBA
        tgt_k = prior.k_rate if prior else LEAGUE_K_PER_PA
        tgt_iso = prior.iso if prior else LEAGUE_ISO

        xwoba_f = _regress(raw_xwoba, tgt_xwoba, weight)
        woba_f = _regress(raw_woba, LEAGUE_WOBA, weight)
        k_rate = _regress(raw_k_rate, tgt_k, weight)
        bb_rate = _regress(raw_bb_rate, LEAGUE_BB_PER_PA, weight)
        iso = _regress(raw_iso, tgt_iso, weight)

        # babip is stored for reference only (not a model input); leave it raw.
        babip_d = ab - k - hr
        babip = round((hits - hr) / babip_d, 4) if babip_d > 0 else None

        pa_l30, xwoba_l30, k_rate_l30, iso_l30 = _resolve_l30_fields(
            l30_by_pid.get(pid),
        )

        rows.append({
            "player_id": pid,
            "season": season,
            "plate_appearances": pa,
            "xwoba": xwoba_f,
            "woba": woba_f,
            "k_rate": k_rate,
            "bb_rate": bb_rate,
            "iso": iso,
            "babip": babip,
            "barrel_rate": None,
            "hard_hit_rate": None,
            "xwoba_l30": xwoba_l30,
            "k_rate_l30": k_rate_l30,
            "iso_l30": iso_l30,
            "pa_l30": pa_l30,
        })

    return rows


# ---------------------------------------------------------------------------
# Shared pitcher skill computation
# ---------------------------------------------------------------------------

def load_all_statcast_pa(season: int) -> list[pd.DataFrame]:
    """Pull all season Statcast terminal-PA DataFrames from the disk cache."""
    pa_chunks: list[pd.DataFrame] = []
    for chunk_df in pull_statcast_chunks(season):
        pa_chunks.append(_terminal_pa(chunk_df))
    return pa_chunks


def compute_pitcher_skill_rows(
    season: int,
    all_pa: list[pd.DataFrame],
    cutoff_date: date | None = None,
) -> list[dict]:
    """
    Compute pitcher_skill rows from pre-loaded Statcast PA DataFrames.

    When cutoff_date is given, only PAs with game_date < cutoff_date are used
    (point-in-time semantics).  When None, all provided data is used.

    Returns a list of dicts (one per pitcher×hand) ready for upsert, each
    containing a 'season' key.
    """
    if cutoff_date is not None:
        filtered: list[pd.DataFrame] = []
        for pa in all_pa:
            if pa.empty:
                continue
            mask = pd.to_datetime(pa["game_date"]).dt.date < cutoff_date
            sub = pa[mask]
            if not sub.empty:
                filtered.append(sub)
    else:
        filtered = [pa for pa in all_pa if not pa.empty]

    ph_rows = agg_pitcher_vs_handedness(filtered)
    ph_rows = [r for r in ph_rows if r["batters_faced"] >= MIN_BF_PITCHER]
    for r in ph_rows:
        # Regress each pitcher×hand rate toward the league mean by batters faced.
        weight = r["batters_faced"] / (r["batters_faced"] + REGRESSION_K_BF)
        r["xwoba_against"] = _regress(r["xwoba_against"], LEAGUE_XWOBA, weight)
        r["woba_against"] = _regress(r["woba_against"], LEAGUE_WOBA, weight)
        r["k_rate"] = _regress(r["k_rate"], LEAGUE_K_PER_PA, weight)
        r["bb_rate"] = _regress(r["bb_rate"], LEAGUE_BB_PER_PA, weight)
        r["hr_per_pa"] = _regress(r["hr_per_pa"], LEAGUE_HR_PER_PA, weight)
        r["hits_per_pa"] = _regress(r["hits_per_pa"], LEAGUE_HIT_PER_PA, weight)
        r["season"] = season
    return ph_rows


# ---------------------------------------------------------------------------
# Shared batter platoon-split computation
# ---------------------------------------------------------------------------

def compute_batter_platoon_rows(
    season: int,
    all_pa: list[pd.DataFrame],
    cutoff_date: date | None = None,
) -> list[dict]:
    """
    Compute batter_platoon_skill rows from pre-loaded Statcast PA DataFrames.

    Splits each batter by the opposing pitcher's throwing hand (p_throws).
    When cutoff_date is given, only PAs with game_date < cutoff_date are used
    (point-in-time semantics).  Splits with fewer than MIN_PA_PLATOON plate
    appearances are dropped (too noisy even after regression).

    Each surviving raw rate is regressed toward its league mean by PA count, the
    same empirical-Bayes blend used for batter_skill / pitcher_skill.

    Returns a list of dicts (one per batter×hand) ready for upsert, each
    containing a 'season' key.
    """
    if cutoff_date is not None:
        filtered: list[pd.DataFrame] = []
        for pa in all_pa:
            if pa.empty:
                continue
            mask = pd.to_datetime(pa["game_date"]).dt.date < cutoff_date
            sub = pa[mask]
            if not sub.empty:
                filtered.append(sub)
    else:
        filtered = [pa for pa in all_pa if not pa.empty]

    pl_rows = agg_batter_vs_pitcher_hand(filtered)
    pl_rows = [r for r in pl_rows if r["pa"] >= MIN_PA_PLATOON]
    for r in pl_rows:
        weight = r["pa"] / (r["pa"] + REGRESSION_K_PA)
        r["xwoba"] = _regress(r["xwoba"], LEAGUE_XWOBA, weight)
        r["k_rate"] = _regress(r["k_rate"], LEAGUE_K_PER_PA, weight)
        r["iso"] = _regress(r["iso"], LEAGUE_ISO, weight)
        r["season"] = season
    return pl_rows


# ---------------------------------------------------------------------------
# Live batter_skill upsert (refresh-skills writes to the non-snapshot table)
# ---------------------------------------------------------------------------

def _aggregate_batter_skill(conn: psycopg.Connection, season: int) -> int:
    """Recompute batter_skill from player_game_stats as of today."""
    cutoff = eastern_today() + timedelta(days=1)  # include today's games
    rows = compute_batter_skill_rows(conn, season, cutoff)

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO batter_skill (
                    player_id, season, plate_appearances,
                    xwoba, woba, k_rate, bb_rate, iso, babip,
                    xwoba_l30, k_rate_l30, iso_l30, pa_l30,
                    updated_at
                )
                VALUES (
                    %(player_id)s, %(season)s, %(plate_appearances)s,
                    %(xwoba)s, %(woba)s, %(k_rate)s, %(bb_rate)s,
                    %(iso)s, %(babip)s,
                    %(xwoba_l30)s, %(k_rate_l30)s, %(iso_l30)s, %(pa_l30)s,
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
                row,
            )

    return len(rows)


# ---------------------------------------------------------------------------
# Live pitcher_skill upsert
# ---------------------------------------------------------------------------

def _aggregate_pitcher_skill(
    conn: psycopg.Connection, season: int, all_pa: list[pd.DataFrame]
) -> int:
    """Re-aggregate pitcher_skill from pre-loaded Statcast PA frames."""
    ph_rows = compute_pitcher_skill_rows(season, all_pa)
    if not ph_rows:
        return 0

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
# Live batter_platoon_skill upsert
# ---------------------------------------------------------------------------

def _aggregate_batter_platoon_skill(
    conn: psycopg.Connection, season: int, all_pa: list[pd.DataFrame]
) -> int:
    """Re-aggregate batter_platoon_skill (vs LHP/RHP) from pre-loaded PA frames."""
    pl_rows = compute_batter_platoon_rows(season, all_pa)
    if not pl_rows:
        return 0

    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(pl_rows), CHUNK):
            cur.executemany(
                """
                INSERT INTO batter_platoon_skill (
                    player_id, season, vs_hand,
                    pa, xwoba, k_rate, iso, updated_at
                )
                VALUES (
                    %(player_id)s, %(season)s, %(vs_hand)s,
                    %(pa)s, %(xwoba)s, %(k_rate)s, %(iso)s, NOW()
                )
                ON CONFLICT (player_id, season, vs_hand) DO UPDATE
                    SET pa         = EXCLUDED.pa,
                        xwoba      = EXCLUDED.xwoba,
                        k_rate     = EXCLUDED.k_rate,
                        iso        = EXCLUDED.iso,
                        updated_at = NOW()
                """,
                pl_rows[i : i + CHUNK],
            )

    return len(pl_rows)


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def cmd_refresh_skills(args: argparse.Namespace) -> None:
    season: int = getattr(args, "season", None) or eastern_today().year

    require_valid_season(season, cmd="refresh-skills")

    cutoff = eastern_today() + timedelta(days=1)
    start, end = season_boundaries(season)
    as_of = min(cutoff - timedelta(days=1), end)
    l30_start = max(start, as_of - timedelta(days=30))
    print(
        f"[refresh-skills] L30 window: {l30_start} → {as_of} "
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
        f"(min {MIN_PA_BATTER_SEASON} PA, regressed to mean; {with_l30} with L30)"
    )

    # Load the Statcast PA cache once; both pitcher splits and batter platoon
    # splits derive from it (avoids reading the weekly cache twice).
    print("[refresh-skills] Reading Statcast cache for handedness splits…")
    all_pa = load_all_statcast_pa(season)

    print(f"[refresh-skills] Aggregating pitcher_skill for {season}…")
    n_pitchers = _aggregate_pitcher_skill(conn, season, all_pa)
    conn.commit()
    print(f"  → {n_pitchers} pitcher×hand rows written (min {MIN_BF_PITCHER} BF)")

    print(f"[refresh-skills] Aggregating batter_platoon_skill for {season}…")
    n_platoon = _aggregate_batter_platoon_skill(conn, season, all_pa)
    conn.commit()
    print(f"  → {n_platoon} batter×hand rows written (min {MIN_PA_PLATOON} PA)")

    conn.close()
    print("[refresh-skills] Done.")
