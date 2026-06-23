"""refresh-priors: compute a Marcel-style multi-year true-talent prior per batter.

Aggregates each player's prior three seasons from player_game_stats (recency
weights 5/4/3, PA-weighted, regressed to league) into batter_projection_prior.
refresh-skills then regresses in-season rates toward this prior instead of the
flat league mean (see compute_batter_skill_rows). Priors are static within a
season, so this only needs to run when a new season's prior years are settled
(or after a historical-stat backfill), not in the daily pipeline.
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection
from ingester.projection.constants import (
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_XWOBA,
    MARCEL_REGRESSION_PA_ISO,
    MARCEL_REGRESSION_PA_K,
    MARCEL_REGRESSION_PA_XWOBA,
    MARCEL_SEASON_WEIGHTS,
)
from ingester.projection.prior import (
    SeasonLine,
    bat_speed_iso_anchor,
    compute_marcel_prior,
    whiff_k_anchor,
)


def _load_prior_seasons(conn, target_season: int) -> dict[int, dict[int, SeasonLine]]:
    """Per-player, per-year counting totals for the target season's prior years."""
    lo = target_season - len(MARCEL_SEASON_WEIGHTS)
    hi = target_season - 1
    rows = conn.execute(
        """
        SELECT
            player_id,
            EXTRACT(YEAR FROM game_date)::int                                   AS yr,
            SUM(plate_appearances)                                             AS pa,
            SUM(at_bats)                                                       AS ab,
            SUM(hits)                                                          AS hits,
            SUM(home_runs)                                                     AS hr,
            SUM(total_bases)                                                   AS tb,
            SUM(strikeouts)                                                    AS k,
            SUM(xwoba * plate_appearances) / NULLIF(SUM(plate_appearances), 0) AS xwoba
        FROM player_game_stats
        WHERE EXTRACT(YEAR FROM game_date) BETWEEN %s AND %s
          AND plate_appearances IS NOT NULL
        GROUP BY player_id, yr
        HAVING SUM(plate_appearances) > 0
        """,
        (lo, hi),
    ).fetchall()

    out: dict[int, dict[int, SeasonLine]] = {}
    for pid, yr, pa, ab, hits, hr, tb, k, xwoba in rows:
        out.setdefault(pid, {})[int(yr)] = SeasonLine(
            pa=int(pa),
            ab=int(ab or 0),
            hits=int(hits or 0),
            hr=int(hr or 0),
            tb=int(tb or 0),
            k=int(k or 0),
            xwoba=float(xwoba) if xwoba is not None else None,
        )
    return out


def _load_iso_anchors(conn, target_season: int) -> dict[int, float]:
    """Bat-speed-implied ISO anchors from the PRIOR season's tracking (leak-free).

    Empty for pre-2025 targets (tracking starts 2024) — callers just fall back to
    the league anchor, i.e. pre-v2.7 behaviour.
    """
    rows = conn.execute(
        """
        SELECT player_id, avg_bat_speed, fast_swing_rate
        FROM batter_bat_tracking WHERE season = %s
        """,
        (target_season - 1,),
    ).fetchall()
    out: dict[int, float] = {}
    for pid, bs, fast in rows:
        anchor = bat_speed_iso_anchor(
            float(bs) if bs is not None else None,
            float(fast) if fast is not None else None,
            LEAGUE_ISO,
        )
        if anchor is not None:
            out[int(pid)] = anchor
    return out


def _load_k_anchors(conn, target_season: int) -> dict[int, float]:
    """Whiff-implied K anchors from the PRIOR season's pitch-level whiff (leak-free).

    Overall whiff rate = swing-weighted mean of the per-pitch-type whiff rates from
    the latest snapshot of season target-1 (vs_handedness 'A' = both sides). A min
    pitch threshold keeps thin, noisy whiff samples out of the anchor. Empty for
    pre-2024 targets (pitch-type stats start 2023) — callers fall back to the flat
    league anchor, i.e. pre-v2.8 behaviour.
    """
    rows = conn.execute(
        """
        WITH latest AS (
            SELECT MAX(as_of_date) AS d
            FROM batter_pitch_type_stats
            WHERE season = %s AND vs_handedness = 'A'
        )
        SELECT player_id,
               SUM(whiff_rate * swing_rate * pitches_seen)
                   / NULLIF(SUM(swing_rate * pitches_seen), 0) AS whiff,
               SUM(pitches_seen) AS pitches
        FROM batter_pitch_type_stats, latest
        WHERE season = %s AND vs_handedness = 'A' AND as_of_date = latest.d
        GROUP BY player_id
        HAVING SUM(pitches_seen) >= 300
        """,
        (target_season - 1, target_season - 1),
    ).fetchall()
    out: dict[int, float] = {}
    for pid, whiff, _pitches in rows:
        anchor = whiff_k_anchor(float(whiff) if whiff is not None else None, LEAGUE_K_PER_PA)
        if anchor is not None:
            out[int(pid)] = anchor
    return out


def _load_ages(conn, target_season: int) -> dict[int, float]:
    """Player age as of July 1 of the target season (the standard 'baseball age')."""
    from datetime import date

    ref = date(target_season, 7, 1)
    rows = conn.execute(
        "SELECT id, birth_date FROM players WHERE birth_date IS NOT NULL"
    ).fetchall()
    return {int(pid): (ref - bd).days / 365.25 for pid, bd in rows}


def cmd_refresh_priors(args: argparse.Namespace) -> None:
    target: int = getattr(args, "season", 2026)

    conn = get_connection()
    by_player = _load_prior_seasons(conn, target)
    iso_anchors = _load_iso_anchors(conn, target)
    k_anchors = _load_k_anchors(conn, target)
    ages = _load_ages(conn, target)  # passed through; only applied when DIAMOND_AGING_ENABLED

    rows: list[dict] = []
    for pid, seasons in by_player.items():
        prior = compute_marcel_prior(
            seasons,
            target,
            league_xwoba=LEAGUE_XWOBA,
            league_k_rate=LEAGUE_K_PER_PA,
            league_iso=LEAGUE_ISO,
            iso_anchor=iso_anchors.get(pid),
            k_rate_anchor=k_anchors.get(pid),
            age=ages.get(pid),
        )
        if prior is None:
            continue
        rows.append({
            "player_id": pid,
            "season": target,
            "proj_xwoba": prior.xwoba,
            "proj_k_rate": prior.k_rate,
            "proj_iso": prior.iso,
            "proj_pa": prior.proj_pa,
        })

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO batter_projection_prior (
                    player_id, season, proj_xwoba, proj_k_rate, proj_iso,
                    proj_pa, method, updated_at
                )
                VALUES (
                    %(player_id)s, %(season)s, %(proj_xwoba)s, %(proj_k_rate)s,
                    %(proj_iso)s, %(proj_pa)s, 'marcel', NOW()
                )
                ON CONFLICT (player_id, season) DO UPDATE
                    SET proj_xwoba  = EXCLUDED.proj_xwoba,
                        proj_k_rate = EXCLUDED.proj_k_rate,
                        proj_iso    = EXCLUDED.proj_iso,
                        proj_pa     = EXCLUDED.proj_pa,
                        method      = EXCLUDED.method,
                        updated_at  = NOW()
                """,
                row,
            )
    conn.commit()
    conn.close()
    print(
        f"[refresh-priors] Wrote {len(rows)} batter priors for {target} "
        f"(Marcel {MARCEL_SEASON_WEIGHTS}, regression xwOBA/K/ISO="
        f"{MARCEL_REGRESSION_PA_XWOBA}/{MARCEL_REGRESSION_PA_K}/{MARCEL_REGRESSION_PA_ISO} PA; "
        f"{len(iso_anchors)} bat-speed ISO anchors, {len(k_anchors)} whiff K anchors)."
    )
