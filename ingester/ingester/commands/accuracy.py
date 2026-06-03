"""compute-accuracy: score a single slate's projections against actuals.

Where `backtest` runs a full range and writes one backtest_runs row, this writes
one `daily_accuracy` snapshot per market for a single slate date so the API/web
can plot a rolling accuracy trend + the latest calibration curve. It is chained
into the nightly `daily` run (scoring the PRIOR slate, whose actuals now exist).

For each market it joins the LIVE projection tables to actuals:
  hit1plus | hit2plus | hr | k1plus  — batter_projections → player_game_stats
                                        (only PA>0 rows), binary Brier + calibration.
  total_runs                          — game_projections → games (final scores), MAE.

Upserts one row per (slate_date, model_version, market). A market with no scored
rows is skipped (no row written) rather than writing a misleading n=0 snapshot.

psycopg3 GOTCHA: autocommit is OFF and conn.transaction() only makes SAVEPOINTs,
so we commit explicitly after the writes (try / commit / except-rollback / finally).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.metrics import (
    baseline_brier,
    brier_score,
    calibration_buckets,
    expected_calibration_error,
    mae_per_game,
)
from ingester.projection.constants import MODEL_VERSION

# Binary prop markets: (market key, batter_projections prob column, actual predicate).
_BINARY_MARKETS = ("hit1plus", "hit2plus", "hr", "k1plus")


def _load_binary_outcomes(
    conn: psycopg.Connection, slate_date: date
) -> dict[str, tuple[list[float], list[int]]]:
    """
    Join batter_projections → player_game_stats for the slate and return
    {market: (predicted, actual)} for the four binary prop markets.

    Mirrors the backtest join (PA>0 rows with non-NULL predictions). p_hit_2plus
    falls back to p_hit_1plus and p_hr/p_k_1plus to 0.0 when NULL, matching
    backtest._load_outcomes so the two surfaces score identically.
    """
    rows = conn.execute(
        """
        SELECT
            bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus,
            CASE WHEN pgs.hits       >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.hits       >= 2 THEN 1 ELSE 0 END,
            CASE WHEN pgs.home_runs  >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.strikeouts >= 1 THEN 1 ELSE 0 END
        FROM batter_projections bp
        JOIN games g ON g.id = bp.game_id
        JOIN player_game_stats pgs
            ON pgs.player_id = bp.player_id
            AND pgs.game_id  = bp.game_id
            AND pgs.plate_appearances > 0
            AND pgs.plate_appearances IS NOT NULL
        WHERE g.game_date = %s
          AND bp.p_hit_1plus IS NOT NULL
        """,
        (slate_date,),
    ).fetchall()

    p_hit1: list[float] = []
    p_hit2: list[float] = []
    p_hr: list[float] = []
    p_k: list[float] = []
    a_hit1: list[int] = []
    a_hit2: list[int] = []
    a_hr: list[int] = []
    a_k: list[int] = []

    for (pred_h1, pred_h2, pred_hr, pred_k, act_h1, act_h2, act_hr, act_k) in rows:
        p_hit1.append(float(pred_h1))
        p_hit2.append(float(pred_h2) if pred_h2 is not None else float(pred_h1))
        p_hr.append(float(pred_hr) if pred_hr is not None else 0.0)
        p_k.append(float(pred_k) if pred_k is not None else 0.0)
        a_hit1.append(int(act_h1))
        a_hit2.append(int(act_h2))
        a_hr.append(int(act_hr))
        a_k.append(int(act_k))

    return {
        "hit1plus": (p_hit1, a_hit1),
        "hit2plus": (p_hit2, a_hit2),
        "hr": (p_hr, a_hr),
        "k1plus": (p_k, a_k),
    }


def _load_run_totals(conn: psycopg.Connection, slate_date: date) -> dict[int, tuple[float, float]]:
    """
    Join game_projections → games (final scores) for the slate.
    Returns {game_id: (expected_total_runs, actual_total_runs)} for scored games,
    keyed for mae_per_game().
    """
    rows = conn.execute(
        """
        SELECT g.id, gp.expected_total_runs, g.home_score + g.away_score
        FROM game_projections gp
        JOIN games g ON g.id = gp.game_id
        WHERE g.game_date = %s
          AND gp.expected_total_runs IS NOT NULL
          AND g.home_score IS NOT NULL
          AND g.away_score IS NOT NULL
        """,
        (slate_date,),
    ).fetchall()
    return {int(gid): (float(exp), float(actual)) for gid, exp, actual in rows}


def _upsert_binary(
    conn: psycopg.Connection,
    slate_date: date,
    model_version: str,
    market: str,
    predicted: list[float],
    actual: list[int],
) -> None:
    """Compute + upsert a binary-market accuracy snapshot (mae left NULL)."""
    buckets = calibration_buckets(predicted, actual)
    brier = brier_score(predicted, actual)
    base = baseline_brier(actual)
    ece = expected_calibration_error(buckets)

    def _num(v: float) -> float | None:
        return None if v != v else round(v, 5)  # NaN -> NULL

    conn.execute(
        """
        INSERT INTO daily_accuracy (
            slate_date, model_version, market, n,
            brier, baseline_brier, ece, calibration_buckets, mae, computed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, NULL, NOW())
        ON CONFLICT (slate_date, model_version, market) DO UPDATE SET
            n                   = EXCLUDED.n,
            brier               = EXCLUDED.brier,
            baseline_brier      = EXCLUDED.baseline_brier,
            ece                 = EXCLUDED.ece,
            calibration_buckets = EXCLUDED.calibration_buckets,
            mae                 = EXCLUDED.mae,
            computed_at         = EXCLUDED.computed_at
        """,
        (
            slate_date, model_version, market, len(predicted),
            _num(brier), _num(base), _num(ece), json.dumps(buckets),
        ),
    )


def _upsert_runs(
    conn: psycopg.Connection,
    slate_date: date,
    model_version: str,
    game_runs: dict[int, tuple[float, float]],
) -> None:
    """Compute + upsert the total_runs MAE snapshot (binary metric cols left NULL)."""
    mae = mae_per_game(game_runs)
    conn.execute(
        """
        INSERT INTO daily_accuracy (
            slate_date, model_version, market, n,
            brier, baseline_brier, ece, calibration_buckets, mae, computed_at
        )
        VALUES (%s, %s, 'total_runs', %s, NULL, NULL, NULL, NULL, %s, NOW())
        ON CONFLICT (slate_date, model_version, market) DO UPDATE SET
            n           = EXCLUDED.n,
            mae         = EXCLUDED.mae,
            computed_at = EXCLUDED.computed_at
        """,
        (slate_date, model_version, len(game_runs),
         None if mae != mae else round(mae, 3)),
    )


def cmd_compute_accuracy(args: argparse.Namespace) -> None:
    # Default to YESTERDAY: live nightly runs score the prior slate, whose
    # actuals (final scores + box scores) only exist after games finish.
    slate_date: date = (
        args.date if getattr(args, "date", None) is not None
        else eastern_today() - timedelta(days=1)
    )
    model_version = MODEL_VERSION

    print(f"[compute-accuracy] {slate_date}  |  Model {model_version}")

    conn = get_connection()
    try:
        binary = _load_binary_outcomes(conn, slate_date)
        game_runs = _load_run_totals(conn, slate_date)

        written = []
        for market in _BINARY_MARKETS:
            predicted, actual = binary[market]
            if not predicted:
                continue
            _upsert_binary(conn, slate_date, model_version, market, predicted, actual)
            written.append((market, len(predicted), brier_score(predicted, actual)))

        if game_runs:
            _upsert_runs(conn, slate_date, model_version, game_runs)
            written.append(("total_runs", len(game_runs), mae_per_game(game_runs)))

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not written:
        print(
            f"[compute-accuracy] WARN: no scored projections for {slate_date}. "
            "Ensure batter_projections/game_projections and actuals "
            "(player_game_stats / final scores) both exist for that date.",
            file=sys.stderr,
        )
        return

    for market, n, metric in written:
        label = "mae" if market == "total_runs" else "brier"
        print(f"[compute-accuracy] {market:<11} n={n:>5}  {label}={metric:.5f}")
    print(f"[compute-accuracy] done — {len(written)} market snapshot(s) written")
