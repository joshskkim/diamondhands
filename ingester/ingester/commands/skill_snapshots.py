"""refresh-skill-snapshots: Compute point-in-time batter/pitcher skill for backtesting.

Usage:
    uv run python main.py refresh-skill-snapshots \\
        --season 2025 --start 2025-04-01 --end 2025-09-30 --interval weekly

Writes to batter_skill_snapshots and pitcher_skill_snapshots, one row per
(player_id, as_of_date) using only game_date < as_of_date.
Idempotent: ON CONFLICT ... DO UPDATE.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

import psycopg

from ingester.db import get_connection
from ingester.commands.refresh_skills import (
    MIN_BF_PITCHER,
    compute_batter_skill_rows,
    compute_pitcher_skill_rows,
    load_all_statcast_pa,
)
from ingester.statcast import require_valid_season


# ---------------------------------------------------------------------------
# Monday iteration
# ---------------------------------------------------------------------------

def _iter_mondays(start: date, end: date):
    """Yield each Monday in [start, end] inclusive."""
    days_to_monday = (0 - start.weekday()) % 7  # weekday(): 0=Monday
    current = start + timedelta(days=days_to_monday)
    while current <= end:
        yield current
        current += timedelta(days=7)


# ---------------------------------------------------------------------------
# Snapshot upserts
# ---------------------------------------------------------------------------

_BATTER_SNAPSHOT_SQL = """
INSERT INTO batter_skill_snapshots (
    player_id, as_of_date, season, plate_appearances,
    xwoba, woba, k_rate, bb_rate, iso, babip,
    barrel_rate, hard_hit_rate,
    xwoba_l30, k_rate_l30, iso_l30, pa_l30,
    computed_at
)
VALUES (
    %(player_id)s, %(as_of_date)s, %(season)s, %(plate_appearances)s,
    %(xwoba)s, %(woba)s, %(k_rate)s, %(bb_rate)s, %(iso)s, %(babip)s,
    %(barrel_rate)s, %(hard_hit_rate)s,
    %(xwoba_l30)s, %(k_rate_l30)s, %(iso_l30)s, %(pa_l30)s,
    NOW()
)
ON CONFLICT (player_id, as_of_date) DO UPDATE SET
    season            = EXCLUDED.season,
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
    computed_at       = NOW()
"""

_PITCHER_SNAPSHOT_SQL = """
INSERT INTO pitcher_skill_snapshots (
    player_id, as_of_date, season, vs_handedness,
    batters_faced, woba_against, xwoba_against,
    k_rate, bb_rate, hr_per_pa, hits_per_pa,
    computed_at
)
VALUES (
    %(player_id)s, %(as_of_date)s, %(season)s, %(vs_handedness)s,
    %(batters_faced)s, %(woba_against)s, %(xwoba_against)s,
    %(k_rate)s, %(bb_rate)s, %(hr_per_pa)s, %(hits_per_pa)s,
    NOW()
)
ON CONFLICT (player_id, as_of_date, vs_handedness) DO UPDATE SET
    season        = EXCLUDED.season,
    batters_faced = EXCLUDED.batters_faced,
    woba_against  = EXCLUDED.woba_against,
    xwoba_against = EXCLUDED.xwoba_against,
    k_rate        = EXCLUDED.k_rate,
    bb_rate       = EXCLUDED.bb_rate,
    hr_per_pa     = EXCLUDED.hr_per_pa,
    hits_per_pa   = EXCLUDED.hits_per_pa,
    computed_at   = NOW()
"""


def _write_batter_snapshot(
    conn: psycopg.Connection,
    as_of_date: date,
    rows: list[dict],
) -> None:
    """Upsert batter skill rows into batter_skill_snapshots."""
    with conn.cursor() as cur:
        for row in rows:
            cur.execute(_BATTER_SNAPSHOT_SQL, {**row, "as_of_date": as_of_date})


def _write_pitcher_snapshot(
    conn: psycopg.Connection,
    as_of_date: date,
    rows: list[dict],
) -> None:
    """Upsert pitcher skill rows into pitcher_skill_snapshots."""
    CHUNK = 500
    with conn.cursor() as cur:
        for i in range(0, len(rows), CHUNK):
            batch = [{**r, "as_of_date": as_of_date} for r in rows[i : i + CHUNK]]
            cur.executemany(_PITCHER_SNAPSHOT_SQL, batch)


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def _delete_existing_snapshots(conn: psycopg.Connection, mondays: list[date]) -> None:
    """
    Remove all snapshot rows for the target dates so a rebuild can't leave stale
    rows behind. Needed when the player population changes (e.g. lowering the PA
    floor): plain upsert only overwrites players still present, leaving dropped
    players' old rows in place. Delete-then-insert guarantees a clean rebuild.
    """
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM batter_skill_snapshots WHERE as_of_date = ANY(%s)",
            (mondays,),
        )
        n_batter = cur.rowcount
        cur.execute(
            "DELETE FROM pitcher_skill_snapshots WHERE as_of_date = ANY(%s)",
            (mondays,),
        )
        n_pitcher = cur.rowcount
    conn.commit()
    print(
        f"[refresh-skill-snapshots] --force-rebuild: cleared "
        f"{n_batter} batter + {n_pitcher} pitcher snapshot rows for {len(mondays)} dates"
    )


def cmd_refresh_skill_snapshots(args: argparse.Namespace) -> None:
    season: int = args.season
    start: date = args.start
    end: date = args.end
    force_rebuild: bool = getattr(args, "force_rebuild", False)

    require_valid_season(season, cmd="refresh-skill-snapshots")

    mondays = list(_iter_mondays(start, end))
    if not mondays:
        print(f"[refresh-skill-snapshots] No Mondays in {start}–{end}; nothing to do.")
        return

    print(
        f"[refresh-skill-snapshots] Season {season} · {len(mondays)} Monday snapshots "
        f"({mondays[0]} → {mondays[-1]})"
    )

    # Load all Statcast PA data for the season once (reads from pybaseball cache).
    print("[refresh-skill-snapshots] Loading Statcast cache for pitcher splits…")
    all_pa = load_all_statcast_pa(season)
    print(f"  → {sum(len(p) for p in all_pa):,} terminal-PA rows loaded")

    conn = get_connection()
    total_batter_rows = 0
    total_pitcher_rows = 0

    try:
        if force_rebuild:
            _delete_existing_snapshots(conn, mondays)

        for monday in mondays:
            batter_rows = compute_batter_skill_rows(conn, season, cutoff_date=monday)
            _write_batter_snapshot(conn, monday, batter_rows)
            conn.commit()

            pitcher_rows = compute_pitcher_skill_rows(season, all_pa, cutoff_date=monday)
            _write_pitcher_snapshot(conn, monday, pitcher_rows)
            conn.commit()

            total_batter_rows += len(batter_rows)
            total_pitcher_rows += len(pitcher_rows)
            print(
                f"  {monday}: {len(batter_rows)} batters, "
                f"{len(pitcher_rows)} pitcher×hand rows"
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[refresh-skill-snapshots] Done. "
        f"{len(mondays)} snapshots · "
        f"{total_batter_rows} batter rows · "
        f"{total_pitcher_rows} pitcher×hand rows total"
    )
