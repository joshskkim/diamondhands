"""pybaseball wrappers for Statcast data pulls and aggregation.

Switch-hitter assumption: the `stand` column in Statcast already reflects the
side a switch hitter actually batted from (always opposite the pitcher's hand),
so we use `stand` directly for pitcher handedness splits — no correction needed.
"""
from __future__ import annotations

import sys
import warnings
from datetime import date, timedelta
from typing import Iterator

import numpy as np
import pandas as pd
import pybaseball

pybaseball.cache.enable()

MIN_SEASON_YEAR = 2015


def season_boundaries(year: int) -> tuple[date, date]:
    """MLB regular season runs late March through early October.

    Use generous bounds; pybaseball will return empty for off-season days.
    """
    return date(year, 3, 15), date(year, 11, 5)


def require_valid_season(season: int, *, cmd: str = "") -> None:
    """Exit if season is outside 2015 through the current calendar year."""
    current_year = date.today().year
    if season < MIN_SEASON_YEAR or season > current_year:
        prefix = f"[{cmd}] " if cmd else ""
        sys.exit(
            f"{prefix}Season {season} not supported. "
            f"Use {MIN_SEASON_YEAR}–{current_year}."
        )

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
    """Yield weekly chunks of pitch-level Statcast data for a season.

    For the in-progress season we stop at today: the rest of the season hasn't
    been played, so iterating those weeks just makes empty pybaseball calls (for
    a June run that was ~21 of 34 weekly chunks). Past seasons are unaffected —
    their end date is already before today, so the clamp is a no-op.
    """
    from ingester.db import eastern_today

    start, end = season_boundaries(season)
    end = min(end, eastern_today())
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


def _to_float64(series: pd.Series | None) -> pd.Series:
    """Coerce Statcast columns to float64 (avoids Int64/float mix in combine)."""
    if series is None:
        return pd.Series(dtype=np.float64)
    return pd.to_numeric(series, errors="coerce").astype(np.float64)


def _xwoba_num(pa: pd.DataFrame) -> pd.Series:
    """
    Per-PA xwOBA numerator:
    - batted-ball events: use estimated_woba_using_speedangle
    - non-contact events (K, BB, HBP): fall back to woba_value
    """
    ew = _to_float64(pa.get("estimated_woba_using_speedangle"))
    wv = _to_float64(pa.get("woba_value"))
    return ew.combine_first(wv)


def agg_batter_game_stats(df: pd.DataFrame, abbrev_to_id: dict[str, int]) -> list[dict]:
    """Aggregate pitch-level data to one dict per (batter, game) — hitting rows."""
    pa = _terminal_pa(df)
    if pa.empty:
        return []

    pa = pa.copy()
    pa["xwoba_num"] = _xwoba_num(pa)
    pa["woba_value"] = _to_float64(pa.get("woba_value"))
    pa["woba_denom"] = _to_float64(pa.get("woba_denom"))

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
        is_home=("is_home", "first"),
        home_team=("home_team", "first"),
        away_team=("away_team", "first"),
    ).reset_index()

    # Divide by the PA count, NOT sum(woba_denom): Statcast's bulk feed populates
    # woba_denom on only ~1 of every ~9 PA-ending rows (NaN on the rest), so summing
    # it collapses the denominator and inflates xwOBA. Each PA-ending row is one PA,
    # so plate_appearances is the correct denominator (season xwOBA in refresh-skills
    # is PA-weighted, so sum(num)/sum(PA) stays exact). See statcast_pitch.py.
    agg["xwoba"] = (agg["xwoba_num"] / agg["plate_appearances"].replace(0, np.nan)).round(4)
    agg["woba"]  = (agg["woba_num"]  / agg["plate_appearances"].replace(0, np.nan)).round(4)

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


def agg_batter_vs_pitcher_hand(pa_chunks: list[pd.DataFrame]) -> list[dict]:
    """
    Aggregate across all season PA data to (batter, p_throws) for platoon splits.

    Mirrors agg_pitcher_vs_handedness but groups by the OPPOSING PITCHER's throwing
    hand (`p_throws`), producing one dict per (batter, vs_hand) with raw pa, xwoba,
    k_rate, and iso. vs_hand ∈ {'L','R'} is the pitcher's hand.

    Switch hitters need no correction: `stand` (and thus the matchup) already
    reflects the effective side, but we key purely on p_throws here.
    """
    needed_cols = [
        "batter", "p_throws", "events",
        "estimated_woba_using_speedangle", "woba_value",
    ]

    acc: dict[tuple[int, str], dict] = {}

    for pa in pa_chunks:
        if pa.empty:
            continue
        sub = pa[[c for c in needed_cols if c in pa.columns]].copy()
        sub = sub[sub["p_throws"].isin(["L", "R"])]
        if sub.empty:
            continue

        sub["xwoba_num"] = _xwoba_num(sub)
        sub["is_k"]   = sub["events"].isin({"strikeout", "strikeout_double_play"}).astype(int)
        sub["is_hit"] = sub["events"].isin(HIT_EVENTS).astype(int)
        sub["is_ab"]  = sub["events"].isin(AB_EVENTS).astype(int)
        sub["tb"] = (
            (sub["events"] == "single").astype(int)
            + (sub["events"] == "double").astype(int) * 2
            + (sub["events"] == "triple").astype(int) * 3
            + (sub["events"] == "home_run").astype(int) * 4
        )

        grp = sub.groupby(["batter", "p_throws"])
        chunk_agg = grp.agg(
            pa=("events", "count"),
            k=("is_k", "sum"),
            hits=("is_hit", "sum"),
            ab=("is_ab", "sum"),
            tb=("tb", "sum"),
            xwoba_num=("xwoba_num", "sum"),
        )

        for (batter, p_throws), row in chunk_agg.iterrows():
            key = (int(batter), str(p_throws))
            if key not in acc:
                acc[key] = {"pa": 0, "k": 0, "hits": 0, "ab": 0, "tb": 0,
                            "xwoba_num": 0.0}
            d = acc[key]
            d["pa"]        += int(row["pa"])
            d["k"]         += int(row["k"])
            d["hits"]      += int(row["hits"])
            d["ab"]        += int(row["ab"])
            d["tb"]        += int(row["tb"])
            d["xwoba_num"] += float(row["xwoba_num"]) if not pd.isna(row["xwoba_num"]) else 0.0

    rows: list[dict] = []
    for (batter_id, p_throws), d in acc.items():
        pa = d["pa"]
        ab = d["ab"]
        # xwOBA divides by PA count (not sparse woba_denom) — see agg_batter_game_stats.
        rows.append({
            "player_id": batter_id,
            "vs_hand":   p_throws,
            "pa":        pa,
            "xwoba":     round(d["xwoba_num"] / pa, 4) if pa > 0 else None,
            "k_rate":    round(d["k"] / pa, 4) if pa > 0 else None,
            "iso":       round((d["tb"] - d["hits"]) / ab, 4) if ab > 0 else None,
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
        sub["woba_value"] = _to_float64(sub.get("woba_value"))
        sub["woba_denom"] = _to_float64(sub.get("woba_denom")).fillna(0)
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
        # Denominator is batters faced (PA count), NOT sum(woba_denom) — the latter is
        # sparsely populated in the bulk feed and collapses the ratio. See agg_batter_game_stats.
        rows.append({
            "player_id":     pitcher_id,
            "vs_handedness": stand,
            "batters_faced": bf,
            "xwoba_against": round(d["xwoba_num"] / bf, 4) if bf > 0 else None,
            "woba_against":  round(d["woba_num"]  / bf, 4) if bf > 0 else None,
            "k_rate":        round(d["k"]    / bf, 4) if bf > 0 else None,
            "bb_rate":       round(d["bb"]   / bf, 4) if bf > 0 else None,
            "hr_per_pa":     round(d["hr"]   / bf, 4) if bf > 0 else None,
            "hits_per_pa":   round(d["hits"] / bf, 4) if bf > 0 else None,
        })
    return rows


def _mark_reliever_pa(pa: pd.DataFrame) -> pd.DataFrame:
    """
    Flag each terminal-PA row as a relief appearance and tag the pitching team.

    Starter identification: within each (game_pk, inning_topbot) side, the
    starting pitcher is the one who recorded the earliest at_bat_number — i.e.
    threw the first pitch of that side.  Every PA charged to any *other* pitcher
    on that side is a relief PA.

    Pitching team: when the away team is batting (inning_topbot == 'Top') the
    HOME team is on the mound, so the pitching team is `home_team`; in the
    bottom of an inning the AWAY team pitches.  Statcast abbreviations are
    remapped to MLBAM via _remap.

    Returns the subset of rows that are relief PAs, with two added columns:
    `is_reliever` (always True in the result) and `pitch_team` (remapped abbrev).
    """
    if pa.empty:
        return pa.iloc[0:0]

    sub = pa.copy()
    sub["at_bat_number"] = pd.to_numeric(sub.get("at_bat_number"), errors="coerce")
    sub = sub[sub["at_bat_number"].notna() & sub["inning_topbot"].isin(["Top", "Bot"])]
    if sub.empty:
        return sub

    # Earliest at_bat_number per (game, side) belongs to the starter of that side.
    starter_idx = sub.groupby(["game_pk", "inning_topbot"])["at_bat_number"].idxmin()
    starter_lookup = (
        sub.loc[starter_idx, ["game_pk", "inning_topbot", "pitcher"]]
        .rename(columns={"pitcher": "_starter"})
    )
    merged = sub.merge(starter_lookup, on=["game_pk", "inning_topbot"], how="left")
    relievers = merged[merged["pitcher"] != merged["_starter"]].copy()
    if relievers.empty:
        return relievers

    # Top = away bats => home team pitches; Bot = home bats => away team pitches.
    pitch_team_raw = relievers["home_team"].where(
        relievers["inning_topbot"] == "Top", relievers["away_team"]
    )
    relievers["pitch_team"] = pitch_team_raw.map(_remap)
    relievers["is_reliever"] = True
    return relievers


def agg_bullpen_vs_handedness(
    pa_chunks: list[pd.DataFrame],
    abbrev_to_id: dict[str, int],
) -> list[dict]:
    """
    Aggregate season relief PAs to (team_id, stand) for bullpen_skill.

    Mirrors agg_pitcher_vs_handedness, but (a) drops each game-side's starting
    pitcher and (b) groups by the pitching TEAM rather than by individual
    pitcher.  Accepts a list of per-chunk terminal-PA DataFrames so the full
    season never has to be resident at once.  Returns one dict per
    (team_id, vs_handedness).
    """
    needed_cols = [
        "pitcher", "stand", "events", "game_pk", "inning_topbot",
        "at_bat_number", "home_team", "away_team",
        "estimated_woba_using_speedangle", "woba_value",
    ]

    acc: dict[tuple[int, str], dict] = {}

    for pa in pa_chunks:
        if pa.empty:
            continue
        sub = pa[[c for c in needed_cols if c in pa.columns]].copy()
        sub = sub[sub["stand"].isin(["L", "R"])]
        if sub.empty:
            continue

        relievers = _mark_reliever_pa(sub)
        if relievers.empty:
            continue

        # Resolve pitching team abbreviation to team_id; drop unmapped teams.
        relievers["team_id"] = relievers["pitch_team"].map(
            lambda a: abbrev_to_id.get(a) if a else None
        )
        relievers = relievers[relievers["team_id"].notna()]
        if relievers.empty:
            continue
        relievers["team_id"] = relievers["team_id"].astype("int64")

        relievers["xwoba_num"] = _xwoba_num(relievers)
        relievers["woba_value"] = _to_float64(relievers.get("woba_value"))
        relievers["is_k"]   = relievers["events"].isin({"strikeout", "strikeout_double_play"}).astype(int)
        relievers["is_hit"] = relievers["events"].isin(HIT_EVENTS).astype(int)
        relievers["is_hr"]  = (relievers["events"] == "home_run").astype(int)

        grp = relievers.groupby(["team_id", "stand"])
        chunk_agg = grp.agg(
            bf=("events", "count"),
            k=("is_k", "sum"),
            hits=("is_hit", "sum"),
            hr=("is_hr", "sum"),
            xwoba_num=("xwoba_num", "sum"),
        )

        for (team_id, stand), row in chunk_agg.iterrows():
            key = (int(team_id), str(stand))
            if key not in acc:
                acc[key] = {"bf": 0, "k": 0, "hits": 0, "hr": 0, "xwoba_num": 0.0}
            d = acc[key]
            d["bf"]        += int(row["bf"])
            d["k"]         += int(row["k"])
            d["hits"]      += int(row["hits"])
            d["hr"]        += int(row["hr"])
            d["xwoba_num"] += float(row["xwoba_num"]) if not pd.isna(row["xwoba_num"]) else 0.0

    rows: list[dict] = []
    for (team_id, stand), d in acc.items():
        bf = d["bf"]
        rows.append({
            "team_id":     team_id,
            "vs_hand":     stand,
            "bf":          bf,
            "k_rate":      round(d["k"]    / bf, 4) if bf > 0 else None,
            "hr_per_pa":   round(d["hr"]   / bf, 4) if bf > 0 else None,
            "hits_per_pa": round(d["hits"] / bf, 4) if bf > 0 else None,
        })
    return rows


# ── Batter batted-ball / spray profile (BallparkPal-style batter inputs) ───────

# Statcast hit-coordinate origin (home plate) for the spray-angle conversion.
_HC_X_HOME = 125.42
_HC_Y_HOME = 198.27
# Balls within this many degrees of dead center count as "center", not pull/oppo.
_SPRAY_CENTER_BAND_DEG = 15.0


def _spray_angle_deg(hc_x: pd.Series, hc_y: pd.Series) -> pd.Series:
    """Spray angle (deg), catcher's view: negative = left-field side, positive = right-field."""
    return np.degrees(np.arctan2(hc_x - _HC_X_HOME, _HC_Y_HOME - hc_y))


def agg_batter_batted_ball(chunks: list[pd.DataFrame]) -> list[dict]:
    """
    Aggregate a season's batted-ball / spray profile per batter from Statcast chunks.

    Uses balls in play (rows with launch_speed + hit coordinates). Spray angle is
    handedness-adjusted into pull/center/oppo (pull = LHB→RF / RHB→LF), bb_type into
    GB/LD/FB/PU, and contact quality via avg EV / launch angle, hard-hit (EV≥95) and
    Statcast barrels (launch_speed_angle == 6). One dict per batter.
    """
    needed = ["batter", "stand", "launch_speed", "launch_angle",
              "hc_x", "hc_y", "bb_type", "launch_speed_angle"]
    acc: dict[int, dict] = {}
    sum_keys = ("bip", "pull", "center", "oppo", "gb", "ld", "fb", "pu",
                "ev_sum", "la_sum", "ev_cnt", "la_cnt", "hard", "barrel")

    for df in chunks:
        if df is None or df.empty:
            continue
        sub = df[[c for c in needed if c in df.columns]].copy()
        for col in ("launch_speed", "launch_angle", "hc_x", "hc_y", "launch_speed_angle"):
            if col not in sub.columns:
                sub[col] = np.nan
        if "stand" not in sub.columns or "bb_type" not in sub.columns:
            continue
        sub = sub[sub["stand"].isin(["L", "R"])]
        ev = _to_float64(sub["launch_speed"])
        hx = _to_float64(sub["hc_x"])
        hy = _to_float64(sub["hc_y"])
        keep = ev.notna() & hx.notna() & hy.notna() & sub["bb_type"].notna()
        sub = sub[keep]
        if sub.empty:
            continue
        sub["batter"] = pd.to_numeric(sub["batter"], errors="coerce")
        sub = sub[sub["batter"].notna()]
        if sub.empty:
            continue

        ev = _to_float64(sub["launch_speed"])
        la = _to_float64(sub["launch_angle"])
        spray = _spray_angle_deg(_to_float64(sub["hc_x"]), _to_float64(sub["hc_y"]))
        is_r = sub["stand"].eq("R").to_numpy()
        band = _SPRAY_CENTER_BAND_DEG
        pull = (is_r & (spray < -band)) | (~is_r & (spray > band))
        oppo = (is_r & (spray > band)) | (~is_r & (spray < -band))
        center = ~(pull | oppo)
        bb = sub["bb_type"].astype(str)
        lsa = _to_float64(sub["launch_speed_angle"])

        per = pd.DataFrame({
            "batter": sub["batter"].astype("int64").to_numpy(),
            "pull": pull.astype(int), "center": center.astype(int), "oppo": oppo.astype(int),
            "gb": bb.eq("ground_ball").astype(int).to_numpy(),
            "ld": bb.eq("line_drive").astype(int).to_numpy(),
            "fb": bb.eq("fly_ball").astype(int).to_numpy(),
            "pu": bb.eq("popup").astype(int).to_numpy(),
            "ev_sum": ev.fillna(0.0).to_numpy(), "ev_cnt": ev.notna().astype(int).to_numpy(),
            "la_sum": la.fillna(0.0).to_numpy(), "la_cnt": la.notna().astype(int).to_numpy(),
            "hard": (ev >= 95).fillna(False).astype(int).to_numpy(),
            "barrel": (lsa == 6).fillna(False).astype(int).to_numpy(),
        })
        per["bip"] = 1
        grp = per.groupby("batter").sum()
        for bid, row in grp.iterrows():
            d = acc.setdefault(int(bid), {k: 0.0 for k in sum_keys})
            for k in sum_keys:
                d[k] += float(row[k])

    def _pct(num: float, den: float) -> float | None:
        return round(num / den, 4) if den > 0 else None

    rows: list[dict] = []
    for bid, d in acc.items():
        bip = int(d["bip"])
        rows.append({
            "player_id": bid,
            "bip": bip,
            "pull_pct": _pct(d["pull"], bip),
            "center_pct": _pct(d["center"], bip),
            "oppo_pct": _pct(d["oppo"], bip),
            "gb_pct": _pct(d["gb"], bip),
            "ld_pct": _pct(d["ld"], bip),
            "fb_pct": _pct(d["fb"], bip),
            "pu_pct": _pct(d["pu"], bip),
            "avg_launch_speed": round(d["ev_sum"] / d["ev_cnt"], 2) if d["ev_cnt"] > 0 else None,
            "avg_launch_angle": round(d["la_sum"] / d["la_cnt"], 2) if d["la_cnt"] > 0 else None,
            "hard_hit_pct": _pct(d["hard"], bip),
            "barrel_pct": _pct(d["barrel"], bip),
        })
    return rows
