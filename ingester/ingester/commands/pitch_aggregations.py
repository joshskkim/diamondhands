"""refresh-pitch-aggregations / refresh-pitch-snapshots: pitch-mix data layer (v2.1).

    refresh-pitch-aggregations --season 2025 [--as-of YYYY-MM-DD]
        Pull pitch-level Statcast for the season up to as_of_date (default today),
        aggregate batter pitch-type stats, pitcher arsenals, and league baselines,
        and upsert them for that as_of_date. First run is slow (cold pybaseball
        cache); later runs read the cache.

    refresh-pitch-snapshots --season 2025 --start ... --end ... --interval weekly
        Call the same aggregation as-of each Monday in the range to backfill the
        point-in-time history the backtest reads. The season is pulled once and
        re-aggregated per Monday from the cached frame, so this is one slow pull
        followed by cheap re-aggregation.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import pandas as pd
import psycopg

from ingester.commands.skill_snapshots import _iter_mondays
from ingester.db import eastern_today, get_connection
from ingester.statcast import require_valid_season
from ingester.statcast_pitch import (
    aggregate_batter_pitch_stats,
    aggregate_pitcher_arsenal,
    compute_league_baselines,
    fetch_pitch_level,
)

# ---------------------------------------------------------------------------
# Upsert SQL
# ---------------------------------------------------------------------------

_BATTER_SQL = """
INSERT INTO batter_pitch_type_stats (
    player_id, season, as_of_date, pitch_type, vs_handedness,
    pitches_seen, pa_ended_on_type,
    xwoba, woba, k_rate, iso, hr_rate, swing_rate, whiff_rate
) VALUES (
    %(player_id)s, %(season)s, %(as_of_date)s, %(pitch_type)s, %(vs_handedness)s,
    %(pitches_seen)s, %(pa_ended_on_type)s,
    %(xwoba)s, %(woba)s, %(k_rate)s, %(iso)s, %(hr_rate)s, %(swing_rate)s, %(whiff_rate)s
)
ON CONFLICT (player_id, season, as_of_date, pitch_type, vs_handedness) DO UPDATE SET
    pitches_seen     = EXCLUDED.pitches_seen,
    pa_ended_on_type = EXCLUDED.pa_ended_on_type,
    xwoba            = EXCLUDED.xwoba,
    woba             = EXCLUDED.woba,
    k_rate           = EXCLUDED.k_rate,
    iso              = EXCLUDED.iso,
    hr_rate          = EXCLUDED.hr_rate,
    swing_rate       = EXCLUDED.swing_rate,
    whiff_rate       = EXCLUDED.whiff_rate
"""

_ARSENAL_SQL = """
INSERT INTO pitcher_arsenal (
    player_id, season, as_of_date, pitch_type, vs_handedness,
    pitches_thrown, usage_rate, xwoba_against, whiff_rate, avg_velocity
) VALUES (
    %(player_id)s, %(season)s, %(as_of_date)s, %(pitch_type)s, %(vs_handedness)s,
    %(pitches_thrown)s, %(usage_rate)s, %(xwoba_against)s, %(whiff_rate)s, %(avg_velocity)s
)
ON CONFLICT (player_id, season, as_of_date, pitch_type, vs_handedness) DO UPDATE SET
    pitches_thrown = EXCLUDED.pitches_thrown,
    usage_rate     = EXCLUDED.usage_rate,
    xwoba_against  = EXCLUDED.xwoba_against,
    whiff_rate     = EXCLUDED.whiff_rate,
    avg_velocity   = EXCLUDED.avg_velocity
"""

_BASELINE_SQL = """
INSERT INTO pitch_type_league_baselines (
    season, pitch_type, vs_handedness,
    league_xwoba, league_iso, league_k_rate, league_usage_rate
) VALUES (
    %(season)s, %(pitch_type)s, %(vs_handedness)s,
    %(league_xwoba)s, %(league_iso)s, %(league_k_rate)s, %(league_usage_rate)s
)
ON CONFLICT (season, pitch_type, vs_handedness) DO UPDATE SET
    league_xwoba      = EXCLUDED.league_xwoba,
    league_iso        = EXCLUDED.league_iso,
    league_k_rate     = EXCLUDED.league_k_rate,
    league_usage_rate = EXCLUDED.league_usage_rate
"""


def _ensure_players(conn: psycopg.Connection, player_ids: set[int]) -> None:
    """Stub-insert any pitch-data player ids absent from players (FK requirement).

    Names are backfilled properly by daily-slate / backfill-games elsewhere; here
    we only need the FK target to exist.
    """
    if not player_ids:
        return
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO players (id, full_name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            [(pid, f"Unknown#{pid}") for pid in player_ids],
        )


def _write_for_date(
    conn: psycopg.Connection,
    full_df: pd.DataFrame,
    season: int,
    as_of_date: date,
) -> tuple[int, int]:
    """Aggregate and upsert all pitch rows for one as_of_date. Returns (batter, arsenal) counts.

    Replaces existing rows for (season, as_of_date) first so a rerun after a
    population change (e.g. a player dropping below the sample floor) can't leave
    stale rows behind.
    """
    batter_rows = aggregate_batter_pitch_stats(full_df, as_of_date, season)
    arsenal_rows = aggregate_pitcher_arsenal(full_df, as_of_date, season)
    baseline_rows = compute_league_baselines(full_df, season, as_of_date)

    _ensure_players(
        conn,
        {r["player_id"] for r in batter_rows} | {r["player_id"] for r in arsenal_rows},
    )

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM batter_pitch_type_stats WHERE season = %s AND as_of_date = %s",
            (season, as_of_date),
        )
        cur.execute(
            "DELETE FROM pitcher_arsenal WHERE season = %s AND as_of_date = %s",
            (season, as_of_date),
        )
        if batter_rows:
            cur.executemany(_BATTER_SQL, batter_rows)
        if arsenal_rows:
            cur.executemany(_ARSENAL_SQL, arsenal_rows)
        if baseline_rows:
            cur.executemany(_BASELINE_SQL, baseline_rows)
    conn.commit()
    return len(batter_rows), len(arsenal_rows)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_refresh_pitch_aggregations(args: argparse.Namespace) -> None:
    season: int = args.season
    as_of: date = getattr(args, "as_of", None) or eastern_today()
    require_valid_season(season, cmd="refresh-pitch-aggregations")

    print(f"[refresh-pitch-aggregations] Season {season}, as-of {as_of} — loading pitch-level Statcast…")
    full_df = fetch_pitch_level(season)
    print(f"  → {len(full_df):,} pitch rows loaded")

    conn = get_connection()
    try:
        n_batter, n_arsenal = _write_for_date(conn, full_df, season, as_of)
    finally:
        conn.close()

    print(
        f"[refresh-pitch-aggregations] as-of {as_of}: "
        f"{n_batter} batter pitch-type rows, {n_arsenal} arsenal rows."
    )


def cmd_refresh_pitch_snapshots(args: argparse.Namespace) -> None:
    season: int = args.season
    start: date = args.start
    end: date = args.end
    require_valid_season(season, cmd="refresh-pitch-snapshots")

    mondays = list(_iter_mondays(start, end))
    if not mondays:
        print(f"[refresh-pitch-snapshots] No Mondays in {start}–{end}; nothing to do.")
        return

    print(
        f"[refresh-pitch-snapshots] Season {season} · {len(mondays)} Monday snapshots "
        f"({mondays[0]} → {mondays[-1]}) — loading pitch-level Statcast once…"
    )
    full_df = fetch_pitch_level(season)
    print(f"  → {len(full_df):,} pitch rows loaded; aggregating per Monday…")

    conn = get_connection()
    total_batter = 0
    total_arsenal = 0
    try:
        for monday in mondays:
            n_batter, n_arsenal = _write_for_date(conn, full_df, season, monday)
            total_batter += n_batter
            total_arsenal += n_arsenal
            print(f"  {monday}: {n_batter} batter rows, {n_arsenal} arsenal rows")
    finally:
        conn.close()

    print(
        f"[refresh-pitch-snapshots] Done. {len(mondays)} snapshots · "
        f"{total_batter} batter rows · {total_arsenal} arsenal rows total."
    )
