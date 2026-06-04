"""Pure projection-accuracy metric helpers (unit-testable, no DB).

Shared by the `backtest` (range-level) and `compute-accuracy` (per-slate)
commands so the two surfaces always score predictions identically.
"""
from __future__ import annotations


def brier_score(predicted: list[float], actual: list[int]) -> float:
    """Mean squared error between probabilistic predictions and binary outcomes."""
    if not predicted:
        return float("nan")
    return sum((p - a) ** 2 for p, a in zip(predicted, actual)) / len(predicted)


def baseline_brier(actual: list[int]) -> float:
    """Brier score of the naive baseline (always predict the empirical mean rate)."""
    if not actual:
        return float("nan")
    rate = sum(actual) / len(actual)
    return rate * (1.0 - rate)


def calibration_buckets(
    predicted: list[float],
    actual: list[int],
    n_buckets: int = 10,
) -> list[dict]:
    """
    Divide predictions into n_buckets equal-width bins [lo, hi).

    Returns list of dicts (empty bins omitted):
        {lo, hi, n, predicted_mean, actual_rate}
    """
    if not predicted:
        return []
    bucket_width = 1.0 / n_buckets
    result = []
    for i in range(n_buckets):
        lo = i * bucket_width
        hi = (i + 1) * bucket_width
        if i < n_buckets - 1:
            pairs = [(p, a) for p, a in zip(predicted, actual) if lo <= p < hi]
        else:  # last bucket includes 1.0
            pairs = [(p, a) for p, a in zip(predicted, actual) if lo <= p <= 1.0]
        if not pairs:
            continue
        preds, acts = zip(*pairs)
        result.append({
            "lo": round(lo, 2),
            "hi": round(hi, 2),
            "n": len(pairs),
            "predicted_mean": round(sum(preds) / len(preds), 4),
            "actual_rate": round(sum(acts) / len(acts), 4),
        })
    return result


def expected_calibration_error(buckets: list[dict]) -> float:
    """
    Expected Calibration Error: sample-weighted mean |predicted_mean - actual_rate|
    across the calibration buckets. Returns NaN when there are no samples.
    """
    total = sum(b["n"] for b in buckets)
    if total == 0:
        return float("nan")
    return sum(b["n"] * abs(b["predicted_mean"] - b["actual_rate"]) for b in buckets) / total


def mae_per_game(game_hits: dict[int, tuple[float, float]]) -> float:
    """
    MAE between expected and actual hits per game.

    game_hits maps game_id → (sum_expected_hits, sum_actual_hits).
    Used as an accessible proxy for the harder-to-measure runs MAE.
    """
    if not game_hits:
        return float("nan")
    errors = [abs(exp - act) for exp, act in game_hits.values()]
    return sum(errors) / len(errors)


def mae(predicted: list[float], actual: list[float]) -> float:
    """Mean absolute error between paired predictions and actuals."""
    if not predicted:
        return float("nan")
    return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)


def pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation; NaN when undefined (n<2 or zero variance on a side)."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    if vx == 0 or vy == 0:
        return float("nan")
    return cov / (vx * vy)
