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


def log_loss(predicted: list[float], actual: list[int], eps: float = 1e-15) -> float:
    """Binary cross-entropy (a.k.a. logarithmic loss).

    Unlike Brier, log-loss is unbounded and punishes confident-and-wrong far harder
    than confident-and-right, so it rewards *sharp* probabilities on the rare-event
    markets (HR, 2+ hits) where Brier is nearly flat. Predictions are clipped to
    [eps, 1-eps] so a 0/1 prediction can't blow up to infinity.
    """
    if not predicted:
        return float("nan")
    import math

    total = 0.0
    for p, a in zip(predicted, actual):
        pc = min(max(p, eps), 1.0 - eps)
        total += -(a * math.log(pc) + (1 - a) * math.log(1.0 - pc))
    return total / len(predicted)


def sharpness(predicted: list[float]) -> float:
    """Sharpness = population variance of the predicted probabilities.

    Measures how decisive (concentrated away from the base rate) the forecasts are.
    A model that always predicts the base rate is perfectly calibratable yet useless
    for betting; its sharpness is ~0. Per Gneiting et al., the goal is to maximize
    sharpness *subject to* calibration, so this is reported alongside ECE — never on
    its own.
    """
    n = len(predicted)
    if n == 0:
        return float("nan")
    mean = sum(predicted) / n
    return sum((p - mean) ** 2 for p in predicted) / n


def crps_count(pmf: list[float], actual: int) -> float:
    """Ranked Probability Score for a single integer-count forecast.

    For integer-valued outcomes the (discrete) CRPS equals the RPS:
        sum_k (CDF(k) - 1[actual <= k])^2
    over the support of ``pmf`` (index k = count, pmf[k] = P(count == k)). It scores
    the *whole* predicted count distribution (e.g. P(0), P(1), P(2)+ hits/runs) rather
    than a binarized threshold, so it sees information Brier on P(>=1) discards.
    Strictly proper; lower is better.
    """
    if not pmf:
        return float("nan")
    cdf = 0.0
    total = 0.0
    for k, p in enumerate(pmf):
        cdf += p
        indicator = 1.0 if actual <= k else 0.0
        total += (cdf - indicator) ** 2
    return total


def crps_count_mean(forecasts: list[tuple[list[float], int]]) -> float:
    """Mean :func:`crps_count` over many (pmf, actual) forecasts; NaN when empty."""
    if not forecasts:
        return float("nan")
    return sum(crps_count(pmf, actual) for pmf, actual in forecasts) / len(forecasts)


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
