"""refresh-umpires: capture home-plate umpire assignments and recompute tendencies.

Home-plate umpires measurably move strikeout rates and run scoring through how they
call the zone. This command is the DATA LAYER (a later unit wires the tendencies into
the projection model):

  1. ASSIGNMENTS — fetch the MLB Stats API schedule hydrated with ``officials`` for the
     target date range, find the "Home Plate" official per game, upsert them into
     ``umpires``, and set ``games.home_plate_umpire_id``. Officials post close to first
     pitch and some historical games never expose them, so missing officials are
     logged-and-skipped (graceful degradation) rather than fatal.

  2. TENDENCIES — for every umpire we now have games for, recompute two season-relative
     tendencies from the Final games they officiated:
        k_rate_tendency  = total batter strikeouts / total plate appearances in their games
        runs_above_avg   = avg (home_score + away_score) in their games - league avg runs/game
     Umpires below ``MIN_GAMES_SAMPLED`` get NULL tendencies (neutral) so the model can't
     over-trust a tiny sample.

Date selection mirrors the other commands: ``--date`` (single day, default today) or a
``--start``/``--end`` range for backfilling. Network fetches are parallelized; all DB
writes stay on the main thread (psycopg connections are not thread-safe).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.mlb_api import SLATE_GAME_TYPES, fetch_schedule, parse_home_plate_umpire

MAX_WORKERS = 8

# Minimum Final games an umpire must have officiated before we trust their tendencies.
# Below this we store NULL (neutral) so a handful of games can't swing the model.
# One MLB "crew month" is roughly this many home-plate assignments.
MIN_GAMES_SAMPLED = 20

# League-average runs *per game* (both teams combined). Used as the baseline for
# runs_above_avg. ~4.4 runs/team/game in the modern era => ~8.8 combined; computed
# live from the sampled games below, this constant is only a documentation anchor.
LEAGUE_RUNS_PER_GAME_FALLBACK = 8.8


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def compute_umpire_tendencies(
    rows: list[dict],
    league_k_rate: float,
    league_runs_per_game: float,
    min_games: int = MIN_GAMES_SAMPLED,
) -> list[dict]:
    """Pure tendency aggregation — no DB, unit-testable on synthetic data.

    ``rows`` is one row per umpire with pre-aggregated totals over the Final games they
    officiated::

        {umpire_id, full_name, games, total_pa, total_k, total_runs}

    ``league_k_rate`` is total_k/total_pa across the whole sample; ``league_runs_per_game``
    is total_runs/total_games across the whole sample. Both are passed in so the caller
    computes them once over the full population.

    Returns one dict per umpire with computed tendencies::

        {umpire_id, full_name, games_sampled, k_rate_tendency, runs_above_avg}

    Umpires with fewer than ``min_games`` Final games (or no PA recorded) get NULL
    tendencies (neutral): we report games_sampled but cannot trust a small sample.
    """
    out: list[dict] = []
    for r in rows:
        games = int(r["games"])
        total_pa = int(r["total_pa"] or 0)
        total_k = int(r["total_k"] or 0)
        total_runs = float(r["total_runs"] or 0.0)

        if games >= min_games and total_pa > 0:
            k_rate = total_k / total_pa
            runs_above = (total_runs / games) - league_runs_per_game
            k_tendency: float | None = round(k_rate, 4)
            runs_aa: float | None = round(runs_above, 3)
        else:
            k_tendency = None
            runs_aa = None

        out.append(
            {
                "umpire_id": int(r["umpire_id"]),
                "full_name": r["full_name"],
                "games_sampled": games,
                "k_rate_tendency": k_tendency,
                "runs_above_avg": runs_aa,
            }
        )
    return out


def _upsert_assignments(conn: psycopg.Connection, raw_games: list[dict]) -> tuple[int, int]:
    """Upsert home-plate umpires and set games.home_plate_umpire_id.

    Returns (assignments_set, games_missing_official). Only touches games we already
    track (the UPDATE no-ops for unknown gamePks); the ump is upserted first to satisfy
    the FK on games.home_plate_umpire_id.
    """
    assigned = 0
    missing = 0
    for g in raw_games:
        if g.get("gameType") not in SLATE_GAME_TYPES:
            continue
        game_pk = g.get("gamePk")
        if game_pk is None:
            continue
        ump = parse_home_plate_umpire(g)
        if ump is None:
            missing += 1
            continue
        umpire_id, full_name = ump
        # Upsert the umpire reference row first (FK target). Don't clobber computed
        # tendencies here — only refresh the name; tendencies are set in the recompute pass.
        conn.execute(
            """
            INSERT INTO umpires (umpire_id, full_name)
            VALUES (%s, %s)
            ON CONFLICT (umpire_id) DO UPDATE SET full_name = EXCLUDED.full_name
            """,
            (umpire_id, full_name),
        )
        assigned += conn.execute(
            "UPDATE games SET home_plate_umpire_id = %s WHERE id = %s",
            (umpire_id, game_pk),
        ).rowcount
    return assigned, missing


def _recompute_tendencies(conn: psycopg.Connection) -> int:
    """Recompute k_rate_tendency and runs_above_avg for every known umpire.

    Aggregates over the Final games each umpire officiated:
      - K rate from player_game_stats (batter rows: plate_appearances / strikeouts),
        joined games -> player_game_stats on game_id.
      - Runs from games.home_score + games.away_score (only set on Final games).
    League baselines are computed once over the same sampled population so a single
    season's offensive environment is the reference, not a hard-coded constant.
    Returns the number of umpires updated.
    """
    # One row per umpire with totals across their Final games. We require scored games
    # (home_score IS NOT NULL) so runs and the games count agree on the denominator.
    rows = conn.execute(
        """
        WITH ump_games AS (
            SELECT g.home_plate_umpire_id AS umpire_id,
                   g.id                   AS game_id,
                   (g.home_score + g.away_score) AS total_runs
            FROM games g
            WHERE g.home_plate_umpire_id IS NOT NULL
              AND g.home_score IS NOT NULL
              AND g.away_score IS NOT NULL
        ),
        pa_by_game AS (
            SELECT game_id,
                   SUM(plate_appearances) AS pa,
                   SUM(strikeouts)        AS k
            FROM player_game_stats
            WHERE plate_appearances IS NOT NULL
            GROUP BY game_id
        )
        SELECT ug.umpire_id,
               u.full_name,
               COUNT(*)                            AS games,
               COALESCE(SUM(pbg.pa), 0)            AS total_pa,
               COALESCE(SUM(pbg.k), 0)             AS total_k,
               COALESCE(SUM(ug.total_runs), 0)     AS total_runs
        FROM ump_games ug
        JOIN umpires u   ON u.umpire_id = ug.umpire_id
        LEFT JOIN pa_by_game pbg ON pbg.game_id = ug.game_id
        GROUP BY ug.umpire_id, u.full_name
        """
    ).fetchall()

    if not rows:
        print("[refresh-umpires] No scored games with umpire assignments yet — skipping tendencies.")
        return 0

    cols = ["umpire_id", "full_name", "games", "total_pa", "total_k", "total_runs"]
    agg = [dict(zip(cols, r)) for r in rows]

    # League baselines over the full sampled population (PA-weighted K rate; per-game runs).
    grand_pa = sum(int(r["total_pa"] or 0) for r in agg)
    grand_k = sum(int(r["total_k"] or 0) for r in agg)
    grand_games = sum(int(r["games"]) for r in agg)
    grand_runs = sum(float(r["total_runs"] or 0.0) for r in agg)
    league_k_rate = (grand_k / grand_pa) if grand_pa else 0.0
    league_runs_per_game = (grand_runs / grand_games) if grand_games else LEAGUE_RUNS_PER_GAME_FALLBACK

    tendencies = compute_umpire_tendencies(agg, league_k_rate, league_runs_per_game)

    now = datetime.now(tz=timezone.utc)
    updated = 0
    for t in tendencies:
        updated += conn.execute(
            """
            UPDATE umpires
            SET k_rate_tendency = %s,
                runs_above_avg  = %s,
                games_sampled   = %s,
                updated_at      = %s
            WHERE umpire_id = %s
            """,
            (
                t["k_rate_tendency"],
                t["runs_above_avg"],
                t["games_sampled"],
                now,
                t["umpire_id"],
            ),
        ).rowcount

    print(
        f"[refresh-umpires] league K/PA={league_k_rate:.4f}, "
        f"runs/game={league_runs_per_game:.2f} over {grand_games} sampled games."
    )
    return updated


def cmd_refresh_umpires(args: argparse.Namespace) -> None:
    start = getattr(args, "start", None)
    end = getattr(args, "end", None)
    if start is not None or end is not None:
        if start is None or end is None:
            raise SystemExit("[refresh-umpires] --start and --end must be given together")
        if end < start:
            raise SystemExit(f"[refresh-umpires] --end {end} before --start {start}")
        dates = _date_range(start, end)
    else:
        target = args.date if getattr(args, "date", None) is not None else eastern_today()
        dates = [target]

    print(f"[refresh-umpires] Fetching officials for {len(dates)} date(s) ({dates[0]} → {dates[-1]})…")

    conn = get_connection()
    total_assigned = 0
    total_missing = 0
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            for raw in pool.map(lambda d: fetch_schedule(d, hydrate="officials"), dates):
                a, m = _upsert_assignments(conn, raw)
                total_assigned += a
                total_missing += m
        conn.commit()
        print(
            f"[refresh-umpires] Assigned home-plate umps to {total_assigned} games "
            f"({total_missing} games had no official posted yet)."
        )

        updated = _recompute_tendencies(conn)
        conn.commit()
        print(f"[refresh-umpires] Recomputed tendencies for {updated} umpires.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
