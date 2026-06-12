"""Starter workload model (v1): per-start OUTS and STRIKEOUT distributions.

The spine of every starter prop: recorded outs IS the market, and Ks/ER are rates ×
how deep he goes. v1 is deliberately empirical and explainable:

  * expected outs = recency-weighted mean of the pitcher's recent starts, regressed
    toward the league mean by evidence (phantom league starts) — same EB shape as
    the rest of the model;
  * the outs DISTRIBUTION around that mean is the pooled league residual histogram
    (actual − expected at the time, computed walk-forward), shifted to the
    pitcher's mean. Workload variance is mostly league-shaped (blowups, early
    hooks), not pitcher-shaped — pooling borrows strength;
  * BF is a linear function of outs (fit on data) — baserunners add batters;
  * K | BF ~ Binomial(BF, k-rate), with the per-BF k-rate recency-weighted and
    regressed toward league; P(K ≥ line) mixes the binomial over the outs
    distribution.

Pure functions only; ingester.commands wiring and the eval harness live elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import binom

# Recency weight per start back (most recent start = 1.0, next 0.9, …). Workload is
# sticky — rotations hold pitchers to stable pitch counts — so the decay is gentle
# and the phantom prior small: a full 10-start history carries ~68% of the weight.
WORKLOAD_RECENCY_DECAY: float = 0.9
# Only the last N starts inform the expectation (older usage patterns are stale).
WORKLOAD_WINDOW: int = 10
# Phantom league-average starts mixed into a thin history (EB regression).
WORKLOAD_PRIOR_STARTS: float = 3.0
# Per-BF strikeout rate: phantom league BF for the EB blend.
K_RATE_PRIOR_BF: float = 100.0
# Physical bounds on a start's outs.
MAX_OUTS: int = 27


@dataclass(frozen=True)
class WorkloadParams:
    """League context fitted from training data (see fit helpers / eval)."""

    league_mean_outs: float          # league-average outs per start
    league_k_per_bf: float           # league per-BF strikeout rate
    residuals: tuple[float, ...]     # pooled (actual − expected) outs residuals
    bf_intercept: float              # BF ≈ intercept + slope × outs
    bf_slope: float


def weighted_mean(values: list[float], decay: float = WORKLOAD_RECENCY_DECAY,
                  window: int = WORKLOAD_WINDOW) -> tuple[float, float]:
    """(recency-weighted mean, effective n) over the most recent `window` values.

    `values` are most-recent-first. Effective n is the sum of weights — the
    evidence mass the EB regression weighs against the phantom prior.
    """
    recent = values[:window]
    if not recent:
        return 0.0, 0.0
    num = den = 0.0
    w = 1.0
    for v in recent:
        num += w * v
        den += w
        w *= decay
    return num / den, den


def expected_outs(outs_history: list[int], league_mean_outs: float,
                  prior_starts: float = WORKLOAD_PRIOR_STARTS) -> float:
    """EB-regressed expected outs for the next start (history most-recent-first)."""
    mean, n_eff = weighted_mean([float(o) for o in outs_history])
    return (n_eff * mean + prior_starts * league_mean_outs) / (n_eff + prior_starts)


def k_rate_blend(k_bf_history: list[tuple[int, int]], league_k_per_bf: float,
                 prior_bf: float = K_RATE_PRIOR_BF) -> float:
    """Recency-weighted per-BF strikeout rate, regressed toward league.

    `k_bf_history` is (strikeouts, batters_faced) per start, most-recent-first.
    Weighted by recency × BF so a 2-inning blowup doesn't count like a full start.
    """
    num = den = 0.0
    w = 1.0
    for k, bf in k_bf_history[:WORKLOAD_WINDOW]:
        if bf and bf > 0:
            num += w * k
            den += w * bf
        w *= WORKLOAD_RECENCY_DECAY
    return (num + prior_bf * league_k_per_bf) / (den + prior_bf)


def outs_distribution(mu: float, params: WorkloadParams) -> dict[int, float]:
    """P(outs = o) for o in [0, MAX_OUTS]: the pooled residual histogram shifted to mu."""
    dist: dict[int, float] = {}
    n = len(params.residuals)
    if n == 0:
        # Degenerate fallback: all mass on round(mu).
        return {max(0, min(MAX_OUTS, round(mu))): 1.0}
    for r in params.residuals:
        o = max(0, min(MAX_OUTS, round(mu + r)))
        dist[o] = dist.get(o, 0.0) + 1.0 / n
    return dist


def p_outs_over(line: float, mu: float, params: WorkloadParams) -> float:
    """P(outs > line) for a half-line (e.g. 16.5)."""
    return sum(p for o, p in outs_distribution(mu, params).items() if o > line)


def expected_bf(outs: float, params: WorkloadParams) -> float:
    return params.bf_intercept + params.bf_slope * outs


def p_strikeouts_over(line: float, mu_outs: float, k_per_bf: float,
                      params: WorkloadParams) -> float:
    """P(K > line): Binomial(BF(outs), k_rate) mixed over the outs distribution."""
    total = 0.0
    for o, p_o in outs_distribution(mu_outs, params).items():
        bf = max(int(round(expected_bf(o, params))), 0)
        # P(K >= ceil(line + 0.5)) == P(K > line) for half-lines.
        k_needed = int(line) + 1
        total += p_o * float(binom.sf(k_needed - 1, bf, k_per_bf))
    return total


# ── fitting helpers (used by the eval harness / refresh wiring) ───────────────

def fit_bf_given_outs(pairs: list[tuple[int, int]]) -> tuple[float, float]:
    """Least-squares BF ≈ a + b·outs over (outs, bf) pairs."""
    n = len(pairs)
    if n < 2:
        return 4.0, 1.35  # sane league-ish fallback
    sx = sum(o for o, _ in pairs)
    sy = sum(b for _, b in pairs)
    sxx = sum(o * o for o, _ in pairs)
    sxy = sum(o * b for o, b in pairs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 4.0, 1.35
    b = (n * sxy - sx * sy) / denom
    a = (sy - b * sx) / n
    return a, b


def walk_forward_residuals(
    starts_by_pitcher: dict[int, list[int]], league_mean_outs: float
) -> list[float]:
    """Pooled (actual − expected-at-the-time) residuals, walking each pitcher's
    starts oldest→newest. `starts_by_pitcher` lists outs OLDEST-FIRST."""
    residuals: list[float] = []
    for outs in starts_by_pitcher.values():
        history: list[int] = []  # most-recent-first
        for o in outs:
            mu = expected_outs(history, league_mean_outs)
            residuals.append(o - mu)
            history.insert(0, o)
    return residuals
