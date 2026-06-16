"""tennis-fit-calibration: learn an isotonic calibration map for the match-winner
probability from walk-forward predictions and save models/tennis_calibration.json.

Fits on an EARLIER window (default 2018–2023) so the recent backtest/live window
(2024+) it gets applied to is out-of-sample (no leakage)."""
from __future__ import annotations

import argparse
from datetime import date

from ingester.db import get_connection
from ingester.projection.calibration import fit_isotonic  # generic, reused
from ingester.tennis.calibration import MARKET, TennisCalibrator, save_map
from ingester.tennis.ratings import walk_forward_predictions


def _ece(preds: list[float], actual: list[int], bins: int = 10) -> float:
    """Expected calibration error (decile-binned |pred − observed|, n-weighted)."""
    buckets = [[0.0, 0.0, 0] for _ in range(bins)]
    for p, y in zip(preds, actual):
        b = buckets[min(int(p * bins), bins - 1)]
        b[0] += p
        b[1] += y
        b[2] += 1
    n = len(preds)
    return sum(abs(s / c - a / c) * c for s, a, c in buckets if c) / n if n else 0.0


def cmd_tennis_fit_calibration(args: argparse.Namespace) -> None:
    start = args.start or date(2018, 1, 1)
    end = args.end or date(2023, 12, 31)

    conn = get_connection()
    try:
        rows = walk_forward_predictions(conn, start, end)
    finally:
        conn.close()

    if len(rows) < 200:
        print(f"[tennis-fit-calibration] only {len(rows)} predictions in {start}..{end} — too few")
        return

    preds = [p for (_d, _s, p, _y) in rows]
    actual = [y for (_d, _s, _p, y) in rows]
    values = fit_isotonic(preds, actual)
    path = save_map(values)

    cal = TennisCalibrator({MARKET: values})
    ece_before = _ece(preds, actual)
    ece_after = _ece([cal.apply(p) for p in preds], actual)
    print(f"[tennis-fit-calibration] fit on {start}..{end} (N={len(rows)}); "
          f"ECE {ece_before:.4f} -> {ece_after:.4f}; saved {path}")
