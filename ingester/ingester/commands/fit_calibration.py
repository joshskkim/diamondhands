"""fit-calibration: learn per-market probability calibration from a backtest run.

Reads a backtest run's stored predictions joined to actual outcomes, fits a monotonic
(isotonic) predicted→observed map per market (H>=1, H>=2, HR, K>=1), and writes
models/calibration.json. Fit on one date range and apply to another (project/backtest
--calibrate) to recalibrate without leakage.
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection
from ingester.projection.calibration import fit_isotonic, save_maps

_SQL = """
    SELECT bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus,
           pgs.hits, pgs.home_runs, pgs.strikeouts
    FROM backtest_projections bp
    JOIN player_game_stats pgs
      ON pgs.player_id = bp.player_id AND pgs.game_id = bp.game_id
     AND pgs.plate_appearances > 0
    WHERE bp.backtest_run_id = %s AND bp.p_hit_1plus IS NOT NULL
"""


def cmd_fit_calibration(args: argparse.Namespace) -> None:
    conn = get_connection()
    rows = conn.execute(_SQL, (args.run,)).fetchall()
    conn.close()

    if not rows:
        print(f"[fit-calibration] No scored rows for backtest run {args.run}.")
        return

    preds: dict[str, list[float]] = {m: [] for m in ("h1", "h2", "hr", "k")}
    acts: dict[str, list[int]] = {m: [] for m in ("h1", "h2", "hr", "k")}
    for p_h1, p_h2, p_hr, p_k, hits, hr, k in rows:
        preds["h1"].append(float(p_h1))
        acts["h1"].append(1 if hits >= 1 else 0)
        preds["h2"].append(float(p_h2))
        acts["h2"].append(1 if hits >= 2 else 0)
        preds["hr"].append(float(p_hr))
        acts["hr"].append(1 if hr >= 1 else 0)
        preds["k"].append(float(p_k))
        acts["k"].append(1 if k >= 1 else 0)

    maps = {m: fit_isotonic(preds[m], acts[m]) for m in preds}
    path = save_maps(maps, getattr(args, "models_dir", None) and f"{args.models_dir}/calibration.json")
    print(
        f"[fit-calibration] Fit {len(rows)} rows from run {args.run} → {path}\n"
        + "  per-market base rates: "
        + ", ".join(f"{m}={sum(acts[m]) / len(acts[m]):.3f}" for m in preds)
    )
