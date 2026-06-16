"""tennis-score: compute out-of-sample match-winner accuracy (Brier, baseline,
ECE, calibration buckets) bucketed by month x surface, into tennis_daily_accuracy.

Uses the shared walk-forward predictions (leak-free), so the accuracy tab shows
the model's real out-of-sample history. Live per-slate scoring is a later nightly
concern; this gives a populated, honest accuracy view now."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date

from ingester.db import eastern_today, get_connection
from ingester.tennis.constants import MODEL_VERSION
from ingester.tennis.ratings import walk_forward_predictions

_MIN_BUCKET = 20


def _metrics(preds: list[float], actual: list[int], bins: int = 10):
    n = len(preds)
    brier = sum((p - y) ** 2 for p, y in zip(preds, actual)) / n
    base = sum(actual) / n
    baseline = sum((base - y) ** 2 for y in actual) / n
    raw = [[0.0, 0.0, 0] for _ in range(bins)]
    for p, y in zip(preds, actual):
        b = raw[min(int(p * bins), bins - 1)]
        b[0] += p
        b[1] += y
        b[2] += 1
    ece = 0.0
    buckets = []
    for i, (s, a, c) in enumerate(raw):
        if not c:
            continue
        pm, ar = s / c, a / c
        ece += abs(pm - ar) * c
        buckets.append({"lo": round(i / bins, 2), "hi": round((i + 1) / bins, 2),
                        "n": c, "predictedMean": round(pm, 4), "actualRate": round(ar, 4)})
    return brier, baseline, ece / n, buckets


def cmd_tennis_score(args: argparse.Namespace) -> None:
    start = args.start or date(2024, 1, 1)
    end = args.end or eastern_today()

    conn = get_connection()
    try:
        rows = walk_forward_predictions(conn, start, end)
        # (month, surface) -> (preds, actual); each match feeds 'all' + its surface.
        groups: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
        for d, surface, p, y in rows:
            period = d.replace(day=1)
            keys = ["all"]
            if surface in ("hard", "clay", "grass"):
                keys.append(surface)
            for s in keys:
                preds, act = groups[(period, s)]
                preds.append(p)
                act.append(y)

        out_rows = []
        for (period, surface), (preds, act) in groups.items():
            if len(preds) < _MIN_BUCKET:
                continue
            brier, baseline, ece, buckets = _metrics(preds, act)
            out_rows.append((period, MODEL_VERSION, surface, "match_winner", len(preds),
                             round(brier, 5), round(baseline, 5), round(ece, 5),
                             json.dumps(buckets)))

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tennis_daily_accuracy WHERE model_version = %s "
                "AND period_date BETWEEN %s AND %s",
                (MODEL_VERSION, start.replace(day=1), end),
            )
            cur.executemany(
                "INSERT INTO tennis_daily_accuracy (period_date, model_version, surface, "
                "market, n, brier, baseline_brier, ece, calibration_buckets) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                out_rows,
            )
        conn.commit()
        print(f"[tennis-score] wrote {len(out_rows)} (month x surface) rows over {start}..{end}")
    finally:
        conn.close()
