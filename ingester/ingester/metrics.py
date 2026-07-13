"""Pure projection-accuracy metric helpers (unit-testable, no DB).

Shared by the `backtest` (range-level) and `compute-accuracy` (per-slate)
commands so the two surfaces always score predictions identically.
"""
from __future__ import annotations

import math


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


def brier_decomposition(buckets: list[dict], base_rate: float) -> dict:
    """Murphy's 3-term decomposition of the (binned) Brier score.

    Reads the calibration buckets (each {n, predicted_mean, actual_rate}) and splits the
    score into where it comes from::

        brier ≈ reliability − resolution + uncertainty

    - reliability  Σ nₖ(predₖ − actualₖ)² / N   calibration error — lower is better
    - resolution   Σ nₖ(actualₖ − base)²  / N   discrimination    — higher is better
    - uncertainty  base·(1 − base)               irreducible spread of the outcome

    So a bad Brier from *miscalibration* (fix the probabilities) reads very differently from
    one from *no discrimination* (fix the signal) — which ECE/sharpness alone can't tell
    apart. ``brier`` is the reconstructed binned score (≈ the raw Brier up to binning). NaN
    when there are no samples.
    """
    total = sum(b["n"] for b in buckets)
    if total == 0:
        nan = float("nan")
        return {"reliability": nan, "resolution": nan, "uncertainty": nan, "brier": nan}
    reliability = sum(b["n"] * (b["predicted_mean"] - b["actual_rate"]) ** 2 for b in buckets) / total
    resolution = sum(b["n"] * (b["actual_rate"] - base_rate) ** 2 for b in buckets) / total
    uncertainty = base_rate * (1.0 - base_rate)
    return {
        "reliability": reliability,
        "resolution": resolution,
        "uncertainty": uncertainty,
        "brier": reliability - resolution + uncertainty,
    }


def log_loss(predicted: list[float], actual: list[int], eps: float = 1e-15) -> float:
    """Binary cross-entropy (a.k.a. logarithmic loss).

    Unlike Brier, log-loss is unbounded and punishes confident-and-wrong far harder
    than confident-and-right, so it rewards *sharp* probabilities on the rare-event
    markets (HR, 2+ hits) where Brier is nearly flat. Predictions are clipped to
    [eps, 1-eps] so a 0/1 prediction can't blow up to infinity.
    """
    if not predicted:
        return float("nan")
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


def roc_auc(predicted: list[float], actual: list[int]) -> float:
    """Area under the ROC curve — a pure, tie-aware discrimination metric.

    AUC answers "given one random positive and one random negative, how often does
    the model score the positive higher?" — i.e. *ranking* quality, independent of
    calibration or base rate. That is exactly the axis Brier is blind to on the rare
    HR event: a model can have a near-flat Brier yet still rank sluggers correctly.

    Computed via the Mann-Whitney U identity on average ranks (so exact ties count
    as half), which matches ``sklearn.metrics.roc_auc_score``. Returns NaN when the
    metric is undefined — no rows, or only one class present (all HR or none).
    """
    n = len(predicted)
    if n == 0:
        return float("nan")
    n_pos = sum(actual)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = sorted(range(n), key=lambda i: predicted[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and predicted[order[j]] == predicted[order[i]]:
            j += 1
        avg_rank = (i + j - 1) / 2.0 + 1.0  # 1-based average rank of the tie group
        for k in range(i, j):
            ranks[order[k]] = avg_rank
        i = j
    sum_ranks_pos = sum(ranks[idx] for idx in range(n) if actual[idx] == 1)
    return (sum_ranks_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def average_precision(predicted: list[float], actual: list[int]) -> float:
    """Average precision — the area under the precision-recall curve.

    PR-AUC is the discrimination metric of choice for *rare* positives (HR is ~3-5%
    of PA): unlike ROC-AUC it is not inflated by the huge true-negative mass, so it
    reflects how well the top of our ranked list actually concentrates home runs.
    A no-skill model scores ~= the base rate; skill shows up as lift above it.

    AP = sum_n (R_n - R_{n-1}) * P_n over descending score thresholds, with tied
    scores collapsed into one threshold — matching ``average_precision_score``.
    Returns NaN when empty or when there are no positives.
    """
    n = len(predicted)
    if n == 0:
        return float("nan")
    n_pos = sum(actual)
    if n_pos == 0:
        return float("nan")
    order = sorted(range(n), key=lambda i: predicted[i], reverse=True)
    tp = 0
    fp = 0
    prev_recall = 0.0
    ap = 0.0
    i = 0
    while i < n:
        j = i
        while j < n and predicted[order[j]] == predicted[order[i]]:
            j += 1
        for k in range(i, j):
            if actual[order[k]] == 1:
                tp += 1
            else:
                fp += 1
        recall = tp / n_pos
        precision = tp / (tp + fp)
        ap += (recall - prev_recall) * precision
        prev_recall = recall
        i = j
    return ap


def top_k_lift(predicted: list[float], actual: list[int], k: int) -> dict:
    """Realized positive rate among the model's top-k picks vs the overall base rate.

    This is what "getting HR right" means operationally: of the k batters we'd rank
    highest, how much more often do they actually homer than a random batter? Lift =
    top_k_rate / base_rate (1.0 = no skill, 3.0 = triple the base rate). It is the
    projection-side proxy for the pick-layer metric the plan really cares about.

    Returns a dict {k, n, top_k_rate, base_rate, lift}; lift is NaN when the base
    rate is 0. ``k`` is clamped to the sample size. Ties at the cutoff are broken by
    the sort's stable order — good enough for a pooled diagnostic.
    """
    n = len(predicted)
    if n == 0 or k <= 0:
        return {"k": 0, "n": n, "top_k_rate": float("nan"),
                "base_rate": float("nan"), "lift": float("nan")}
    k = min(k, n)
    order = sorted(range(n), key=lambda i: predicted[i], reverse=True)
    top = order[:k]
    top_k_rate = sum(actual[idx] for idx in top) / k
    base_rate = sum(actual) / n
    lift = top_k_rate / base_rate if base_rate > 0 else float("nan")
    return {
        "k": k,
        "n": n,
        "top_k_rate": round(top_k_rate, 4),
        "base_rate": round(base_rate, 4),
        "lift": round(lift, 3) if lift == lift else float("nan"),
    }


def crps_count(pmf: list[float], actual: int) -> float:
    """Ranked Probability Score for a single integer-count forecast.

    For integer-valued outcomes the (discrete) CRPS equals the RPS:
        sum_k (CDF(k) - 1[actual <= k])^2
    where index k = count and pmf[k] = P(count == k). It scores the *whole* predicted
    count distribution (e.g. P(0), P(1), P(2)+ hits/runs) rather than a binarized
    threshold, so it sees information Brier on P(>=1) discards. Strictly proper; lower
    is better.

    The sum runs to ``max(len(pmf)-1, actual)`` — critically, PAST the pmf's support when
    the outcome exceeds it: beyond the support the CDF is frozen at its accumulated total
    (1.0 for a normalized pmf), so each missing tail step contributes (1 - 0)^2 = 1. Without
    this, a forecast whose support stops short of a large actual would be scored on a
    truncated sum and look unfairly good next to a wider-support forecast.
    """
    if not pmf:
        return float("nan")
    cdf = 0.0
    total = 0.0
    for k in range(max(len(pmf) - 1, actual) + 1):
        if k < len(pmf):
            cdf += pmf[k]
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
