"""refresh-projections: pull external projection systems into batter_projection_prior.

Replaces the manual "export a CSV from FanGraphs and run ingest-steamer" step with
an automated fetch of every configured system (Steamer / THE BAT X / ATC / ZiPS)
from the public FanGraphs projections API. Each system lands as its own
method-tagged row (they coexist with the Marcel rows and each other), which
blend-priors then ensembles into a single method='blend' prior.
"""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.fangraphs_api import SYSTEMS, fetch_projection
from ingester.commands.ingest_steamer import ingest_prior_frame


def _bank_snapshot(conn, season: int, methods: list[str]) -> int:
    """Copy the just-fetched current rows into the dated snapshot table.

    Builds the (projection, later-actual) archive a leak-free backtest needs: the
    earliest snapshot of a season is its preseason prior. Idempotent per run date.
    """
    if not methods:
        return 0
    as_of = eastern_today()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO batter_projection_prior_snapshot
                (player_id, season, method, as_of_date,
                 proj_xwoba, proj_k_rate, proj_iso, proj_pa, updated_at)
            SELECT player_id, season, method, %s,
                   proj_xwoba, proj_k_rate, proj_iso, proj_pa, NOW()
            FROM batter_projection_prior
            WHERE season = %s AND method = ANY(%s)
            ON CONFLICT (player_id, season, method, as_of_date) DO UPDATE SET
                proj_xwoba=EXCLUDED.proj_xwoba, proj_k_rate=EXCLUDED.proj_k_rate,
                proj_iso=EXCLUDED.proj_iso, proj_pa=EXCLUDED.proj_pa, updated_at=NOW()
            """,
            (as_of, season, methods),
        )
        return cur.rowcount


def cmd_refresh_projections(args: argparse.Namespace) -> None:
    season: int = args.season
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]

    conn = get_connection()
    total = 0
    fetched: list[str] = []
    for system in systems:
        try:
            df = fetch_projection(system)
        except Exception as exc:  # one system down shouldn't sink the rest
            print(f"[refresh-projections] {system}: SKIPPED ({exc})")
            continue
        written, unmatched = ingest_prior_frame(conn, df, season, system)
        conn.commit()
        total += written
        fetched.append(system)
        print(
            f"[refresh-projections] {system}: {written} priors for {season} "
            f"({unmatched} unmatched/incomplete of {len(df)} fetched)"
        )

    banked = _bank_snapshot(conn, season, fetched)
    conn.commit()
    conn.close()
    print(
        f"[refresh-projections] Wrote {total} rows across {fetched}; "
        f"banked {banked} dated snapshot rows (as_of {eastern_today()}). "
        f"Run blend-priors next to ensemble them."
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--season", type=int, default=eastern_today().year,
        help="Target season year (default: current season)",
    )
    parser.add_argument(
        "--systems",
        default=",".join(SYSTEMS),
        help=f"Comma-separated FanGraphs system codes (default: {','.join(SYSTEMS)})",
    )
