"""Pitch-level Statcast aggregation for the pitch-mix matchup model (v2.1).

Produces three things from raw pybaseball pitch-level data:
  * batter_pitch_type_stats — a batter's xwOBA / K / ISO / whiff by pitch type,
    split by the opposing pitcher's handedness.
  * pitcher_arsenal — a pitcher's pitch-type usage and results, split by the
    batter's handedness.
  * pitch_type_league_baselines — league means per pitch type, the regression
    target applied at query time in the projection.

All stored rates are RAW (unregressed) season-to-date values; empirical-Bayes
regression toward the league baseline happens in projection (matchup.py), not
here, so the aggregates stay reusable when the regression constants change.

Switch-hitter note (same as statcast.py): Statcast `stand` already reflects the
side the batter actually hit from, so it is used directly for handedness splits.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ingester.statcast import (
    AB_EVENTS,
    HIT_EVENTS,
    _to_float64,
    _xwoba_num,
    pull_statcast_chunks,
)

# ---------------------------------------------------------------------------
# Pitch-type normalization
# ---------------------------------------------------------------------------

# Map raw Statcast pitch_type codes to our 7 buckets. Anything not listed
# (knuckleball KN, eephus EP, screwball SC, pitch-out PO, unknown UN/"") is
# dropped — those are too rare / non-comparable to model.
_PITCH_TYPE_MAP: dict[str, str] = {
    "FF": "FF", "FA": "FF",          # 4-seam / generic fastball
    "SI": "SI", "FT": "SI",          # sinker / 2-seam
    "FC": "FC",                       # cutter
    "SL": "SL", "ST": "SL",          # slider / sweeper
    "CU": "CU", "KC": "CU",          # curve / knuckle-curve
    "CH": "CH",                       # changeup
    "FS": "FS",                       # splitter
}

# The 7 buckets we model, in a stable display order.
PITCH_TYPES: tuple[str, ...] = ("FF", "SI", "FC", "SL", "CU", "CH", "FS")

PITCH_TYPE_NAMES: dict[str, str] = {
    "FF": "4-Seam Fastball",
    "SI": "Sinker",
    "FC": "Cutter",
    "SL": "Slider",
    "CU": "Curveball",
    "CH": "Changeup",
    "FS": "Splitter",
}

# Minimum sample to write a row (per pitch_type per handedness).
MIN_PITCHES_BATTER = 30
MIN_PITCHES_PITCHER = 50

# Pitch-result (`description`) classification.
_WHIFF_DESCRIPTIONS = frozenset({"swinging_strike", "swinging_strike_blocked", "missed_bunt"})
_SWING_DESCRIPTIONS = _WHIFF_DESCRIPTIONS | frozenset({
    "foul", "foul_tip", "hit_into_play", "hit_into_play_no_out",
    "hit_into_play_score", "foul_bunt", "bunt_foul_tip",
})


def normalize_pitch_type(raw) -> str | None:
    """Map a raw Statcast pitch_type code to one of the 7 buckets, or None to skip."""
    if raw is None:
        return None
    code = str(raw).strip().upper()
    return _PITCH_TYPE_MAP.get(code)


# ---------------------------------------------------------------------------
# Shared pitch-level preparation
# ---------------------------------------------------------------------------

def _prepare_pitches(df: pd.DataFrame, as_of_date: date, season: int) -> pd.DataFrame:
    """
    Filter to in-season pitches on/before as_of_date with a known handedness and a
    mappable pitch type, and attach the per-pitch boolean/numeric columns the
    aggregations need. Returns an empty frame if nothing qualifies.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    cols = df.columns
    out = df.copy()
    out["pt"] = out["pitch_type"].map(normalize_pitch_type) if "pitch_type" in cols else None
    out = out[out["pt"].notna()]
    if out.empty:
        return out

    out["game_date"] = pd.to_datetime(out["game_date"], errors="coerce")
    out = out[
        out["game_date"].notna()
        & (out["game_date"].dt.year == season)
        & (out["game_date"].dt.date <= as_of_date)
    ]
    out = out[out["stand"].isin(["L", "R"]) & out["p_throws"].isin(["L", "R"])]
    if out.empty:
        return out

    desc = out.get("description", pd.Series(index=out.index, dtype=object))
    out["is_swing"] = desc.isin(_SWING_DESCRIPTIONS).astype(int)
    out["is_whiff"] = desc.isin(_WHIFF_DESCRIPTIONS).astype(int)
    out["velo"] = _to_float64(out.get("release_speed"))

    is_terminal = out["events"].notna() if "events" in cols else pd.Series(False, index=out.index)
    out["is_terminal"] = is_terminal.astype(int)

    # Terminal-only outcome columns; zeroed on non-terminal pitches so group sums
    # only ever count PA-ending pitches.
    ev = out["events"].where(is_terminal, other="")
    out["xwoba_num"] = _xwoba_num(out).where(is_terminal, other=0.0).fillna(0.0)
    out["woba_denom"] = _to_float64(out.get("woba_denom")).where(is_terminal, other=0.0).fillna(0.0)
    out["woba_value"] = _to_float64(out.get("woba_value")).where(is_terminal, other=0.0).fillna(0.0)
    out["is_hit"] = ev.isin(HIT_EVENTS).astype(int)
    out["is_hr"] = (ev == "home_run").astype(int)
    out["is_k"] = ev.isin({"strikeout", "strikeout_double_play"}).astype(int)
    out["is_ab"] = ev.isin(AB_EVENTS).astype(int)
    out["tb"] = (
        (ev == "single").astype(int)
        + (ev == "double").astype(int) * 2
        + (ev == "triple").astype(int) * 3
        + (ev == "home_run").astype(int) * 4
    )
    return out


def _safe_div(num: float, den: float) -> float | None:
    return round(float(num) / float(den), 4) if den else None


# Physical ceiling on an aggregated xwOBA: a single PA tops out at a home run
# (~2.0 on the wOBA scale), so the per-PA mean can never exceed it. Anything above
# means the denominator collapsed (the woba_denom-sparsity bug); fail fast.
_XWOBA_MAX = 2.0


def _assert_xwoba_sane(rows: list[dict], field: str) -> None:
    vals = [r[field] for r in rows if r.get(field) is not None]
    if not vals:
        return
    mx = max(vals)
    assert mx <= _XWOBA_MAX, (
        f"Impossible {field}={mx} (>{_XWOBA_MAX}); denominator bug? "
        f"offending row: {next(r for r in rows if r.get(field) == mx)}"
    )


# ---------------------------------------------------------------------------
# Batter pitch-type stats
# ---------------------------------------------------------------------------

def _batter_rows_for_hand(
    prepared: pd.DataFrame, vs_hand: str, as_of_date: date, season: int
) -> list[dict]:
    """Aggregate prepared pitches (already filtered to one pitcher-hand, or all) to
    one row per (batter, pitch_type) for the given vs_handedness label."""
    if prepared.empty:
        return []
    grp = prepared.groupby(["batter", "pt"], sort=False)
    agg = grp.agg(
        pitches_seen=("pt", "size"),
        pa_ended=("is_terminal", "sum"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        xwoba_num=("xwoba_num", "sum"),
        woba_num=("woba_value", "sum"),
        hits=("is_hit", "sum"),
        hr=("is_hr", "sum"),
        k=("is_k", "sum"),
        ab=("is_ab", "sum"),
        tb=("tb", "sum"),
    ).reset_index()

    rows: list[dict] = []
    for _, r in agg.iterrows():
        pitches_seen = int(r["pitches_seen"])
        if pitches_seen < MIN_PITCHES_BATTER:
            continue
        pa_ended = int(r["pa_ended"])
        swings = int(r["swings"])
        ab = int(r["ab"])
        # Divide by the PA count, NOT sum(woba_denom): the Statcast woba_denom column
        # is populated on only ~1 of every ~9 PA-ending rows in the bulk feed, so
        # summing it collapses the denominator and inflates xwOBA (observed up to 6.45).
        # Each PA-ending row is one PA, so pa_ended is the correct denominator.
        rows.append({
            "player_id": int(r["batter"]),
            "season": season,
            "as_of_date": as_of_date,
            "pitch_type": str(r["pt"]),
            "vs_handedness": vs_hand,
            "pitches_seen": pitches_seen,
            "pa_ended_on_type": pa_ended,
            "xwoba": _safe_div(r["xwoba_num"], pa_ended),
            "woba": _safe_div(r["woba_num"], pa_ended),
            "k_rate": _safe_div(r["k"], pa_ended),
            "iso": _safe_div(r["tb"] - r["hits"], ab),
            "hr_rate": _safe_div(r["hr"], pa_ended),
            "swing_rate": _safe_div(swings, pitches_seen),
            "whiff_rate": _safe_div(r["whiffs"], swings),
        })
    return rows


def aggregate_batter_pitch_stats(
    df: pd.DataFrame, as_of_date: date, season: int
) -> list[dict]:
    """Produce batter_pitch_type_stats rows for vs_handedness L, R and A (any)."""
    prepared = _prepare_pitches(df, as_of_date, season)
    if prepared.empty:
        return []
    rows: list[dict] = []
    rows += _batter_rows_for_hand(prepared[prepared["p_throws"] == "L"], "L", as_of_date, season)
    rows += _batter_rows_for_hand(prepared[prepared["p_throws"] == "R"], "R", as_of_date, season)
    rows += _batter_rows_for_hand(prepared, "A", as_of_date, season)
    _assert_xwoba_sane(rows, "xwoba")
    return rows


# ---------------------------------------------------------------------------
# Pitcher arsenal
# ---------------------------------------------------------------------------

def _arsenal_rows_for_hand(
    prepared: pd.DataFrame,
    vs_hand: str,
    as_of_date: date,
    season: int,
    *,
    min_pitches: int = MIN_PITCHES_PITCHER,
    qualifying: set[tuple[int, str]] | None = None,
) -> list[dict]:
    """Aggregate prepared pitches (already filtered to one batter-stand, or all) to
    one row per (pitcher, pitch_type), with usage_rate within the pitcher's total
    pitches vs that hand.

    ``min_pitches`` gates how many pitches of a type are needed to emit a row;
    ``qualifying`` (when given) restricts emission to (pitcher, pitch_type) pairs that
    cleared the overall threshold. Per-handedness rows use min_pitches=1 + qualifying
    so a pitch type that qualifies overall always gets L/R rows (however thin) and
    query-time empirical-Bayes regression handles the small samples.
    """
    if prepared.empty:
        return []
    totals = prepared.groupby("pitcher", sort=False).size()  # pitches vs this hand
    grp = prepared.groupby(["pitcher", "pt"], sort=False)
    agg = grp.agg(
        pitches_thrown=("pt", "size"),
        pa_ended=("is_terminal", "sum"),
        swings=("is_swing", "sum"),
        whiffs=("is_whiff", "sum"),
        xwoba_num=("xwoba_num", "sum"),
        velo_sum=("velo", "sum"),
        velo_n=("velo", "count"),
    ).reset_index()

    rows: list[dict] = []
    for _, r in agg.iterrows():
        pitches_thrown = int(r["pitches_thrown"])
        if pitches_thrown < min_pitches:
            continue
        pitcher_id = int(r["pitcher"])
        pt = str(r["pt"])
        if qualifying is not None and (pitcher_id, pt) not in qualifying:
            continue
        total = int(totals.get(pitcher_id, 0))
        swings = int(r["swings"])
        velo_n = int(r["velo_n"])
        rows.append({
            "player_id": pitcher_id,
            "season": season,
            "as_of_date": as_of_date,
            "pitch_type": pt,
            "vs_handedness": vs_hand,
            "pitches_thrown": pitches_thrown,
            "usage_rate": _safe_div(pitches_thrown, total),
            # Denominator is PA count, not sum(woba_denom) — see _batter_rows_for_hand.
            "xwoba_against": _safe_div(r["xwoba_num"], int(r["pa_ended"])),
            "whiff_rate": _safe_div(r["whiffs"], swings),
            "avg_velocity": round(float(r["velo_sum"]) / velo_n, 1) if velo_n else None,
        })
    return rows


def aggregate_pitcher_arsenal(
    df: pd.DataFrame, as_of_date: date, season: int
) -> list[dict]:
    """Produce pitcher_arsenal rows for vs_handedness A, L and R.

    A pitch type qualifies on its OVERALL count (>= MIN_PITCHES_PITCHER); the 'A' rows
    define that qualifying set. For every qualifying (pitcher, pitch_type) we then emit
    L and R rows from whatever pitches exist vs that hand (no per-hand minimum), so
    low-volume / spot starters still get handedness splits and the matchup lookup —
    which is keyed by the batter's hand, never 'A' — finds them. Thin L/R samples are
    handled by empirical-Bayes regression at query time (matchup.py).
    """
    prepared = _prepare_pitches(df, as_of_date, season)
    if prepared.empty:
        return []
    a_rows = _arsenal_rows_for_hand(prepared, "A", as_of_date, season)
    qualifying = {(r["player_id"], r["pitch_type"]) for r in a_rows}
    rows: list[dict] = list(a_rows)
    rows += _arsenal_rows_for_hand(
        prepared[prepared["stand"] == "L"], "L", as_of_date, season,
        min_pitches=1, qualifying=qualifying,
    )
    rows += _arsenal_rows_for_hand(
        prepared[prepared["stand"] == "R"], "R", as_of_date, season,
        min_pitches=1, qualifying=qualifying,
    )
    _assert_xwoba_sane(rows, "xwoba_against")
    return rows


# ---------------------------------------------------------------------------
# League baselines
# ---------------------------------------------------------------------------

def _baseline_rows_for_hand(prepared: pd.DataFrame, vs_hand: str, season: int) -> list[dict]:
    if prepared.empty:
        return []
    total_pitches = len(prepared)
    grp = prepared.groupby("pt", sort=False)
    agg = grp.agg(
        pitches=("pt", "size"),
        xwoba_num=("xwoba_num", "sum"),
        hits=("is_hit", "sum"),
        k=("is_k", "sum"),
        ab=("is_ab", "sum"),
        tb=("tb", "sum"),
        pa_ended=("is_terminal", "sum"),
    ).reset_index()

    rows: list[dict] = []
    for _, r in agg.iterrows():
        rows.append({
            "season": season,
            "pitch_type": str(r["pt"]),
            "vs_handedness": vs_hand,
            # Denominator is PA count, not sum(woba_denom) — see _batter_rows_for_hand.
            "league_xwoba": _safe_div(r["xwoba_num"], int(r["pa_ended"])),
            "league_iso": _safe_div(r["tb"] - r["hits"], r["ab"]),
            "league_k_rate": _safe_div(r["k"], r["pa_ended"]),
            "league_usage_rate": _safe_div(r["pitches"], total_pitches),
        })
    return rows


def compute_league_baselines(df: pd.DataFrame, season: int, as_of_date: date) -> list[dict]:
    """Produce pitch_type_league_baselines rows for vs_handedness L, R and A."""
    prepared = _prepare_pitches(df, as_of_date, season)
    if prepared.empty:
        return []
    # Keyed by the PITCHER's hand to match batter_pitch_type_stats.vs_handedness
    # (a batter's xwOBA vs a pitch type is regressed toward the league mean for
    # that pitch type thrown by that-handed pitchers), not the batter's stand.
    rows: list[dict] = []
    rows += _baseline_rows_for_hand(prepared[prepared["p_throws"] == "L"], "L", season)
    rows += _baseline_rows_for_hand(prepared[prepared["p_throws"] == "R"], "R", season)
    rows += _baseline_rows_for_hand(prepared, "A", season)
    _assert_xwoba_sane(rows, "league_xwoba")
    return rows


# ---------------------------------------------------------------------------
# Pull (slow path; pybaseball cache makes re-runs fast)
# ---------------------------------------------------------------------------

def fetch_pitch_level(season: int) -> pd.DataFrame:
    """Load all pitch-level Statcast rows for a season (concatenated weekly chunks).

    Reads from the pybaseball cache after the first cold pull. Callers filter by
    as_of_date themselves (via the aggregation functions), so the full season is
    loaded once and reused across snapshot dates.
    """
    chunks = list(pull_statcast_chunks(season))
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)
