"""pybaseball wrappers for Statcast data pulls and aggregation.

Switch-hitter assumption: the `stand` column in Statcast already reflects the
side a switch hitter actually batted from (always opposite the pitcher's hand),
so we use `stand` directly for pitcher handedness splits — no correction needed.
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta
from typing import Iterator

import numpy as np
import pandas as pd
import pybaseball

pybaseball.cache.enable()

# 2025 regular season includes the Seoul Series opener
SEASON_BOUNDARIES: dict[int, tuple[date, date]] = {
    2025: (date(2025, 3, 18), date(2025, 9, 28)),
}

# Terminal event classification (used on end-of-PA rows only)
HIT_EVENTS = frozenset({"single", "double", "triple", "home_run"})
BB_EVENTS   = frozenset({"walk", "intent_walk"})
AB_EVENTS   = frozenset({
    "single", "double", "triple", "home_run",
    "strikeout", "strikeout_double_play",
    "field_out", "grounded_into_double_play",
    "force_out", "double_play", "triple_play",
    "field_error", "fielders_choice", "fielders_choice_out",
    "other_out",
})

# Statcast team abbreviation → MLBAM abbreviation (for any known mismatches)
SC_TO_MLBAM: dict[str, str] = {
    "ANA": "LAA",
    "FLA": "MIA",
    "MON": "WSH",
}


def pull_statcast_chunks(season: int, chunk_days: int = 7) -> Iterator[pd.DataFrame]:
    """Yield weekly chunks of pitch-level Statcast data for a season."""
    start, end = SEASON_BOUNDARIES[season]
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        print(f"  Fetching Statcast {cur} → {chunk_end} …", flush=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = pybaseball.statcast(str(cur), str(chunk_end), verbose=False)
        if df is not None and not df.empty:
            yield df
        cur = chunk_end + timedelta(days=1)


def _remap(abbrev: str | None) -> str | None:
    if abbrev is None:
        return None
    s = str(abbrev).upper()
    return SC_TO_MLBAM.get(s, s)


def _terminal_pa(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to terminal-event rows (one per plate appearance)."""
    mask = df["events"].notna() & df["game_pk"].notna()
    pa = df[mask].copy()
    # Ensure numeric types
    pa["game_pk"] = pd.to_numeric(pa["game_pk"], errors="coerce")
    pa = pa[pa["game_pk"].notna()]
    pa["game_pk"] = pa["game_pk"].astype("int64")
    return pa


def _xwoba_num(pa: pd.DataFrame) -> pd.Series:
    """
    Per-PA xwOBA numerator:
    - batted-ball events: use estimated_woba_using_speedangle
    - non-contact events (K, BB, HBP): fall back to woba_value
    """
    ew = pd.to_numeric(pa.get("estimated_woba_using_speedangle", pd.Series(dtype=float)), errors="coerce")
    wv = pd.to_numeric(pa.get("woba_value", pd.Series(dtype=float)), errors="coerce")
    return ew.where(ew.notna(), wv)


def agg_batter_game_stats(df: pd.DataFrame, abbrev_to_id: dict[str, int]) -> list[dict]:
    """Aggregate pitch-level data to one dict per (batter, game) — hitting rows."""
    pa = _terminal_pa(df)
    if pa.empty:
        return []

    pa = pa.copy()
    pa["xwoba_num"] = _xwoba_num(pa)
    pa["woba_value"]  = pd.to_numeric(pa.get("woba_value",  pd.Series(dtype=float)), errors="coerce")
    pa["woba_denom"]  = pd.to_numeric(pa.get("woba_denom",  pd.Series(dtype=float)), errors="coerce")

    pa["is_hit"] = pa["events"].isin(HIT_EVENTS).astype(int)
    pa["is_hr"]  = (pa["events"] == "home_run").astype(int)
    pa["is_k"]   = pa["events"].isin({"strikeout", "strikeout_double_play"}).astype(int)
    pa["is_bb"]  = pa["events"].isin(BB_EVENTS).astype(int)
    pa["is_ab"]  = pa["events"].isin(AB_EVENTS).astype(int)
    pa["tb"] = (
        (pa["events"] == "single").astype(int)
        + (pa["events"] == "double").astype(int) * 2
        + (pa["events"] == "triple").astype(int) * 3
        + (pa["events"] == "home_run").astype(int) * 4
    )
    # Bot = home team bats
    pa["is_home"] = (pa.get("inning_topbot", pd.Series(dtype=str)) == "Bot")

    grp = pa.groupby(["batter", "game_pk", "game_date"])
    agg = grp.agg(
        plate_appearances=("events", "count"),
        at_bats=("is_ab", "sum"),
        hits=("is_hit", "sum"),
        home_runs=("is_hr", "sum"),
        total_bases=("tb", "sum"),
        strikeouts=("is_k", "sum"),
        walks=("is_bb", "sum"),
        xwoba_num=("xwoba_num", "sum"),
        woba_num=("woba_value", "sum"),
        woba_denom=("woba_denom", "sum"),
        is_home=("is_home", "first"),
        home_team=("home_team", "first"),
        away_team=("away_team", "first"),
    ).reset_index()

    # Safe division
    agg["xwoba"] = (agg["xwoba_num"] / agg["woba_denom"].replace(0, np.nan)).round(4)
    agg["woba"]  = (agg["woba_num"]  / agg["woba_denom"].replace(0, np.nan)).round(4)

    rows: list[dict] = []
    for _, r in agg.iterrows():
        opp_abbrev = _remap(r["away_team"] if r["is_home"] else r["home_team"])
        rows.append({
            "player_id":          int(r["batter"]),
            "game_date":          str(r["game_date"])[:10],
            "game_id":            int(r["game_pk"]),
            "opponent_team_id":   abbrev_to_id.get(opp_abbrev) if opp_abbrev else None,
            "is_home":            bool(r["is_home"]),
            "plate_appearances":  int(r["plate_appearances"]),
            "at_bats":            int(r["at_bats"]),
            "hits":               int(r["hits"]),
            "home_runs":          int(r["home_runs"]),
            "total_bases":        int(r["total_bases"]),
            "strikeouts":         int(r["strikeouts"]),
            "walks":              int(r["walks"]),
            "xwoba":              None if pd.isna(r["xwoba"]) else float(r["xwoba"]),
            "woba":               None if pd.isna(r["woba"])  else float(r["woba"]),
            "batters_faced":      None,
            "pitcher_strikeouts": None,
            "hits_allowed":       None,
            "hr_allowed":         None,
        })
    return rows


def agg_pitcher_game_stats(df: pd.DataFrame, abbrev_to_id: dict[str, int]) -> list[dict]:
    """Aggregate pitch-level data to one dict per (pitcher, game) — pitching rows."""
    pa = _terminal_pa(df)
    if pa.empty:
        return []

    pa = pa.copy()
    pa["is_k"]   = pa["events"].isin({"strikeout", "strikeout_double_play"}).astype(int)
    pa["is_hit"] = pa["events"].isin(HIT_EVENTS).astype(int)
    pa["is_hr"]  = (pa["events"] == "home_run").astype(int)
    # Top of inning = away bats = home pitcher is pitching
    pa["is_home_pitcher"] = (pa.get("inning_topbot", pd.Series(dtype=str)) == "Top")

    grp = pa.groupby(["pitcher", "game_pk", "game_date"])
    agg = grp.agg(
        batters_faced=("events", "count"),
        pitcher_strikeouts=("is_k", "sum"),
        hits_allowed=("is_hit", "sum"),
        hr_allowed=("is_hr", "sum"),
        is_home=("is_home_pitcher", "first"),
        home_team=("home_team", "first"),
        away_team=("away_team", "first"),
    ).reset_index()

    rows: list[dict] = []
    for _, r in agg.iterrows():
        opp_abbrev = _remap(r["away_team"] if r["is_home"] else r["home_team"])
        rows.append({
            "player_id":          int(r["pitcher"]),
            "game_date":          str(r["game_date"])[:10],
            "game_id":            int(r["game_pk"]),
            "opponent_team_id":   abbrev_to_id.get(opp_abbrev) if opp_abbrev else None,
            "is_home":            bool(r["is_home"]),
            "plate_appearances":  None,
            "at_bats":            None,
            "hits":               None,
            "home_runs":          None,
            "total_bases":        None,
            "strikeouts":         None,
            "walks":              None,
            "xwoba":              None,
            "woba":               None,
            "batters_faced":      int(r["batters_faced"]),
            "pitcher_strikeouts": int(r["pitcher_strikeouts"]),
            "hits_allowed":       int(r["hits_allowed"]),
            "hr_allowed":         int(r["hr_allowed"]),
        })
    return rows


def agg_pitcher_vs_handedness(pa_chunks: list[pd.DataFrame]) -> list[dict]:
    """
    Aggregate across all season PA data to (pitcher, stand) for pitcher_skill.

    Accepts a list of per-chunk terminal-PA DataFrames to avoid loading the full
    season into memory at once.  Returns one dict per (pitcher, vs_handedness).
    """
    needed_cols = [
        "pitcher", "stand", "events",
        "estimated_woba_using_speedangle", "woba_value", "woba_denom",
    ]

    # Build incremental aggregation: accumulate numeric totals per (pitcher, stand)
    acc: dict[tuple[int, str], dict] = {}

    for pa in pa_chunks:
        if pa.empty:
            continue
        sub = pa[[c for c in needed_cols if c in pa.columns]].copy()
        sub = sub[sub["stand"].isin(["L", "R"])]
        if sub.empty:
            continue

        sub["xwoba_num"] = _xwoba_num(sub)
        sub["woba_value"] = pd.to_numeric(sub.get("woba_value", pd.Series(dtype=float)), errors="coerce")
        sub["woba_denom"] = pd.to_numeric(sub.get("woba_denom", pd.Series(dtype=float)), errors="coerce").fillna(0)
        sub["is_k"]   = sub["events"].isin({"strikeout", "strikeout_double_play"}).astype(int)
        sub["is_bb"]  = sub["events"].isin(BB_EVENTS).astype(int)
        sub["is_hit"] = sub["events"].isin(HIT_EVENTS).astype(int)
        sub["is_hr"]  = (sub["events"] == "home_run").astype(int)

        grp = sub.groupby(["pitcher", "stand"])
        chunk_agg = grp.agg(
            bf=("events", "count"),
            k=("is_k", "sum"),
            bb=("is_bb", "sum"),
            hits=("is_hit", "sum"),
            hr=("is_hr", "sum"),
            xwoba_num=("xwoba_num", "sum"),
            woba_num=("woba_value", "sum"),
            woba_denom=("woba_denom", "sum"),
        )

        for (pitcher, stand), row in chunk_agg.iterrows():
            key = (int(pitcher), str(stand))
            if key not in acc:
                acc[key] = {"bf": 0, "k": 0, "bb": 0, "hits": 0, "hr": 0,
                            "xwoba_num": 0.0, "woba_num": 0.0, "woba_denom": 0.0}
            d = acc[key]
            d["bf"]         += int(row["bf"])
            d["k"]          += int(row["k"])
            d["bb"]         += int(row["bb"])
            d["hits"]       += int(row["hits"])
            d["hr"]         += int(row["hr"])
            d["xwoba_num"]  += float(row["xwoba_num"]) if not pd.isna(row["xwoba_num"]) else 0.0
            d["woba_num"]   += float(row["woba_num"])  if not pd.isna(row["woba_num"])  else 0.0
            d["woba_denom"] += float(row["woba_denom"])

    rows: list[dict] = []
    for (pitcher_id, stand), d in acc.items():
        bf    = d["bf"]
        denom = d["woba_denom"] or np.nan
        rows.append({
            "player_id":     pitcher_id,
            "vs_handedness": stand,
            "batters_faced": bf,
            "xwoba_against": None if np.isnan(denom) else round(d["xwoba_num"] / denom, 4),
            "woba_against":  None if np.isnan(denom) else round(d["woba_num"]  / denom, 4),
            "k_rate":        round(d["k"]    / bf, 4) if bf > 0 else None,
            "bb_rate":       round(d["bb"]   / bf, 4) if bf > 0 else None,
            "hr_per_pa":     round(d["hr"]   / bf, 4) if bf > 0 else None,
            "hits_per_pa":   round(d["hits"] / bf, 4) if bf > 0 else None,
        })
    return rows
