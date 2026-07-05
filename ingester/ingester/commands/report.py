"""compare-runs: side-by-side per-market diagnostics across backtest runs.

Read-only. Pulls each run's stored Brier columns + calibration_buckets JSONB and prints,
per market: Brier, the naive base-rate Brier (derived from the buckets' weighted actual
rate), and the calibration ECE (weighted mean |predicted - actual|). Use it to compare
mechanistic / xgb / blend on the same held-out range.
"""
from __future__ import annotations

import argparse
import json

from ingester.db import get_connection

_MARKETS = [("hit1plus", "H>=1"), ("hit2plus", "H>=2"), ("hr", "HR"), ("k1plus", "K>=1")]


def _buckets(raw) -> dict:
    if raw is None:
        return {}
    return raw if isinstance(raw, dict) else json.loads(raw)


def _ece(buckets: list[dict]) -> float | None:
    n = sum(b["n"] for b in buckets)
    if not n:
        return None
    return sum(b["n"] * abs(b["actual_rate"] - b["predicted_mean"]) for b in buckets) / n


def _base_rate(buckets: list[dict]) -> float | None:
    n = sum(b["n"] for b in buckets)
    if not n:
        return None
    return sum(b["n"] * b["actual_rate"] for b in buckets) / n


def cmd_compare_runs(args: argparse.Namespace) -> None:
    run_ids = [int(x) for x in args.runs.split(",")]

    conn = get_connection()
    try:
        runs = []
        for rid in run_ids:
            row = conn.execute(
                """SELECT id, model_version, range_start, range_end, n_batter_projections,
                          brier_hit1plus, brier_hit2plus, brier_hr, brier_k1plus, calibration_buckets
                   FROM backtest_runs WHERE id = %s""",
                (rid,),
            ).fetchone()
            if row is None:
                raise SystemExit(f"[compare-runs] no run {rid}")
            runs.append(row)
    finally:
        conn.close()

    print(f"Range {runs[0][2]} → {runs[0][3]}   (runs: {', '.join(str(r[0]) for r in runs)})\n")
    for mk, label in _MARKETS:
        print(f"{label}:")
        for r in runs:
            cb = _buckets(r[9])
            buckets = cb.get(mk, [])
            bval = r[5 + [c for c, _ in _MARKETS].index(mk)]
            if bval is None:
                print(f"   #{r[0]} {r[1]:<22} (incomplete run)")
                continue
            brier = float(bval)
            base = _base_rate(buckets)
            naive = base * (1 - base) if base is not None else None
            ece = _ece(buckets)
            tag = f"#{r[0]} {r[1]}"
            naive_s = f"{naive:.4f}" if naive is not None else "  N/A"
            ece_s = f"{ece:.3f}" if ece is not None else " N/A"
            print(f"   {tag:<26} Brier {brier:.4f}  (naive {naive_s})   ECE {ece_s}")
        print()
