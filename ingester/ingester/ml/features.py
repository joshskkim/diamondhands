"""Shared per-batter-game feature builder (v3 spike).

The SAME ``build_feature_row`` is used by the training-dataset builder and (in Stage B)
by inference, so there is no train/serve skew. Every feature is read point-in-time from
the snapshot tables — the most recent snapshot with ``as_of_date <= as_of_date`` — which
is what makes the dataset leakage-safe. Returns ``None`` when the batter has no skill
snapshot as of the date (the same sub-threshold fallback the mechanistic path uses).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from ingester.projection.batter_model import BatterSkillInput, blend_batter_skills
from ingester.projection.constants import EXPECTED_PA_PER_STARTER, PA_BY_ORDER
from ingester.projection.matchup import compute_matchup
from ingester.projection.park_adj import ParkFactors

# Canonical feature column order (also persisted to feature_spec.json in Stage B).
FEATURE_COLUMNS: tuple[str, ...] = (
    # batter skill (point-in-time)
    "b_xwoba", "b_xwoba_l30", "b_k_rate", "b_k_rate_l30", "b_iso", "b_iso_l30",
    "b_pa_l30", "b_woba", "b_bb_rate", "b_babip", "b_barrel_rate", "b_hard_hit_rate",
    "b_season_pa",
    # opposing pitcher vs the batter's hand (point-in-time)
    "p_woba_against", "p_xwoba_against", "p_k_rate", "p_bb_rate", "p_hr_per_pa",
    "p_hits_per_pa", "p_bf",
    # pitch-mix matchup
    "m_xwoba", "m_k_rate", "m_iso", "m_covered", "m_quality",
    # context
    "lineup_position", "expected_pa", "is_home", "platoon_same", "park_hits", "park_hr",
)


def effective_bat_side(bats: str, pitcher_throws: str) -> str:
    """Side the batter actually hits from (switch hitters bat opposite the pitcher).

    Mirrors runner._effective_bat_side; duplicated here to keep this module import-light.
    """
    if bats == "S":
        return "L" if pitcher_throws == "R" else "R"
    return bats if bats in ("L", "R") else "R"


def _f(v) -> float | None:
    return None if v is None else float(v)


@dataclass(frozen=True)
class _BatterSnap:
    xwoba: float
    xwoba_l30: float
    k_rate: float
    k_rate_l30: float
    iso: float
    iso_l30: float
    pa_l30: int
    woba: float | None
    bb_rate: float | None
    babip: float | None
    barrel_rate: float | None
    hard_hit_rate: float | None
    season_pa: int | None


def _read_batter_snapshot(
    conn: psycopg.Connection, player_id: int, as_of_date: date
) -> _BatterSnap | None:
    """Most recent batter_skill_snapshots row with as_of_date <= as_of_date (all features)."""
    row = conn.execute(
        """
        SELECT xwoba, xwoba_l30, k_rate, k_rate_l30, iso, iso_l30, pa_l30,
               woba, bb_rate, babip, barrel_rate, hard_hit_rate, plate_appearances
        FROM batter_skill_snapshots
        WHERE player_id = %s AND as_of_date <= %s
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        (player_id, as_of_date),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    xwoba = float(row[0])
    k_rate = float(row[2]) if row[2] is not None else 0.0
    iso = float(row[4]) if row[4] is not None else 0.0
    return _BatterSnap(
        xwoba=xwoba,
        xwoba_l30=float(row[1]) if row[1] is not None else xwoba,
        k_rate=k_rate,
        k_rate_l30=float(row[3]) if row[3] is not None else k_rate,
        iso=iso,
        iso_l30=float(row[5]) if row[5] is not None else iso,
        pa_l30=int(row[6] or 0),
        woba=_f(row[7]),
        bb_rate=_f(row[8]),
        babip=_f(row[9]),
        barrel_rate=_f(row[10]),
        hard_hit_rate=_f(row[11]),
        season_pa=int(row[12]) if row[12] is not None else None,
    )


def _read_pitcher_snapshot(
    conn: psycopg.Connection, pitcher_id: int, vs_hand: str, as_of_date: date
) -> dict[str, float | None]:
    """Most recent pitcher_skill_snapshots row vs the given hand; all-None if absent."""
    row = conn.execute(
        """
        SELECT woba_against, xwoba_against, k_rate, bb_rate, hr_per_pa, hits_per_pa, batters_faced
        FROM pitcher_skill_snapshots
        WHERE player_id = %s AND vs_handedness = %s AND as_of_date <= %s
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        (pitcher_id, vs_hand, as_of_date),
    ).fetchone()
    keys = ["p_woba_against", "p_xwoba_against", "p_k_rate", "p_bb_rate",
            "p_hr_per_pa", "p_hits_per_pa", "p_bf"]
    if row is None:
        return {k: None for k in keys}
    return {k: _f(v) for k, v in zip(keys, row)}


def build_feature_row(
    conn: psycopg.Connection,
    *,
    batter_id: int,
    bats: str,
    opposing_pitcher_id: int,
    pitcher_throws: str,
    lineup_position: int | None,
    is_home: bool,
    park: ParkFactors,
    as_of_date: date,
    season: int,
) -> dict | None:
    """Build the feature dict for one (batter, game). None => caller skips the row.

    Identical for training and inference. Missing pitcher / pitch-mix values are left as
    None (NaN downstream) — XGBoost handles missing natively.
    """
    b = _read_batter_snapshot(conn, batter_id, as_of_date)
    if b is None:
        return None

    skill = BatterSkillInput(
        xwoba=b.xwoba, xwoba_l30=b.xwoba_l30, k_rate=b.k_rate, k_rate_l30=b.k_rate_l30,
        iso=b.iso, iso_l30=b.iso_l30, pa_l30=b.pa_l30,
    )
    blends = blend_batter_skills(skill)
    eff_hand = effective_bat_side(bats, pitcher_throws)

    pitcher = _read_pitcher_snapshot(conn, opposing_pitcher_id, eff_hand, as_of_date)
    matchup = compute_matchup(
        conn,
        batter_id=batter_id, pitcher_id=opposing_pitcher_id,
        batter_hand=eff_hand, pitcher_hand=pitcher_throws,
        as_of_date=as_of_date, season=season,
        overall_xwoba=blends.xwoba, overall_k_rate=blends.k_rate, overall_iso=blends.iso,
    )

    expected_pa = (
        PA_BY_ORDER.get(int(lineup_position), EXPECTED_PA_PER_STARTER)
        if lineup_position is not None else EXPECTED_PA_PER_STARTER
    )
    park_hr = park.park_factor_hr_lhb if eff_hand == "L" else park.park_factor_hr_rhb

    return {
        "b_xwoba": b.xwoba, "b_xwoba_l30": b.xwoba_l30, "b_k_rate": b.k_rate,
        "b_k_rate_l30": b.k_rate_l30, "b_iso": b.iso, "b_iso_l30": b.iso_l30,
        "b_pa_l30": b.pa_l30, "b_woba": b.woba, "b_bb_rate": b.bb_rate, "b_babip": b.babip,
        "b_barrel_rate": b.barrel_rate, "b_hard_hit_rate": b.hard_hit_rate,
        "b_season_pa": b.season_pa,
        **pitcher,
        "m_xwoba": matchup.xwoba, "m_k_rate": matchup.k_rate, "m_iso": matchup.iso,
        "m_covered": matchup.covered_usage,
        "m_quality": 1 if matchup.quality == "matchup" else 0,
        "lineup_position": (int(lineup_position) if lineup_position is not None else None),
        "expected_pa": expected_pa,
        "is_home": 1 if is_home else 0,
        "platoon_same": 1 if eff_hand == pitcher_throws else 0,
        "park_hits": park.park_factor_hits,
        "park_hr": park_hr,
    }
