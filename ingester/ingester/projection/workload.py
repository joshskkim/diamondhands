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
  * WALKS are the same shape as Ks — BB | BF ~ Binomial(BF, bb-rate) mixed over the
    outs distribution — so the K and BB ladders share the rate-blend and
    count-over helpers (per_bf_rate_blend / p_count_over) and differ only in which
    per-start counts and league rate they feed in.

Pure functions only; ingester.commands wiring and the eval harness live elsewhere.
"""
from __future__ import annotations

import os
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
# Per-BF strikeout rate: phantom league BF for the EB blend. Env-overridable (T2 A/B) —
# LOWER = more per-pitcher weight (less regression to league); sweep on a held-out range.
K_RATE_PRIOR_BF: float = float(os.environ.get("DIAMOND_K_RATE_PRIOR_BF", "100.0"))
# Per-BF walk rate: phantom league BF for the EB blend. Walks are rarer and noisier per
# start than Ks, so a slightly heavier prior keeps a thin sample closer to league.
# Env-overridable (T2): the smoke test showed pitcher-BB carries ~no edge — sweep this
# DOWN to test whether more per-pitcher walk-rate weight recovers signal out-of-sample.
BB_RATE_PRIOR_BF: float = float(os.environ.get("DIAMOND_BB_RATE_PRIOR_BF", "120.0"))
# Physical bounds on a start's outs.
MAX_OUTS: int = 27

# Sportsbook lines we precompute P(over) for (the prop board / picks / game-page odds
# panel read these). p_outs_over / p_strikeouts_over price any half-line; the grid just
# decides which ones survive into the stored jsonb, and a book line off the grid gets no
# model probability at all. So the grid spans the range books actually quote: outs
# 11.5–20.5 (14.5/17.5 ≈ "5 IP" / "6 IP" sit mid-range) and K 2.5–9.5.
WORKLOAD_OUTS_LINES: tuple[float, ...] = tuple(x + 0.5 for x in range(11, 21))
WORKLOAD_K_LINES: tuple[float, ...] = tuple(x + 0.5 for x in range(2, 10))
# Walks allowed: books quote a starter's walk line around 1.5–2.5; the grid spans 0.5–3.5
# so ladderProb can price (and interpolate to) any book line in that range.
WORKLOAD_BB_LINES: tuple[float, ...] = tuple(x + 0.5 for x in range(0, 4))
# Clamp the sim's per-side starter innings to a sane range (a μ of 16 outs ≈ 5 IP;
# never let a noisy estimate pull a starter below 3 or above 8 innings in the sim).
WORKLOAD_SIM_MIN_INNINGS: int = 3
WORKLOAD_SIM_MAX_INNINGS: int = 8


@dataclass(frozen=True)
class WorkloadParams:
    """League context fitted from training data (see fit helpers / eval)."""

    league_mean_outs: float          # league-average outs per start
    league_k_per_bf: float           # league per-BF strikeout rate
    league_bb_per_bf: float          # league per-BF walk rate
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


def per_bf_rate_blend(count_bf_history: list[tuple[int, int]], league_rate: float,
                      prior_bf: float) -> float:
    """Recency-weighted per-BF rate of some event, regressed toward the league rate.

    `count_bf_history` is (event_count, batters_faced) per start, most-recent-first.
    Weighted by recency × BF so a 2-inning blowup doesn't count like a full start.
    Shared by the strikeout and walk ladders — see k_rate_blend / bb_rate_blend.
    """
    num = den = 0.0
    w = 1.0
    for count, bf in count_bf_history[:WORKLOAD_WINDOW]:
        if bf and bf > 0:
            num += w * count
            den += w * bf
        w *= WORKLOAD_RECENCY_DECAY
    return (num + prior_bf * league_rate) / (den + prior_bf)


def k_rate_blend(k_bf_history: list[tuple[int, int]], league_k_per_bf: float,
                 prior_bf: float = K_RATE_PRIOR_BF) -> float:
    """Recency-weighted per-BF strikeout rate, regressed toward league."""
    return per_bf_rate_blend(k_bf_history, league_k_per_bf, prior_bf)


def bb_rate_blend(bb_bf_history: list[tuple[int, int]], league_bb_per_bf: float,
                  prior_bf: float = BB_RATE_PRIOR_BF) -> float:
    """Recency-weighted per-BF walk rate, regressed toward league."""
    return per_bf_rate_blend(bb_bf_history, league_bb_per_bf, prior_bf)


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


def p_count_over(line: float, mu_outs: float, per_bf_rate: float,
                 params: WorkloadParams) -> float:
    """P(count > line): Binomial(BF(outs), per_bf_rate) mixed over the outs distribution.

    The shared engine behind both the strikeout and walk ladders — the only difference
    between them is the per-BF event rate passed in.
    """
    total = 0.0
    for o, p_o in outs_distribution(mu_outs, params).items():
        bf = max(int(round(expected_bf(o, params))), 0)
        # P(count >= ceil(line + 0.5)) == P(count > line) for half-lines.
        needed = int(line) + 1
        total += p_o * float(binom.sf(needed - 1, bf, per_bf_rate))
    return total


def p_strikeouts_over(line: float, mu_outs: float, k_per_bf: float,
                      params: WorkloadParams) -> float:
    """P(K > line): Binomial(BF(outs), k_rate) mixed over the outs distribution."""
    return p_count_over(line, mu_outs, k_per_bf, params)


def p_walks_over(line: float, mu_outs: float, bb_per_bf: float,
                 params: WorkloadParams) -> float:
    """P(BB > line): Binomial(BF(outs), bb_rate) mixed over the outs distribution."""
    return p_count_over(line, mu_outs, bb_per_bf, params)


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


def outs_pmf_list(mu: float, params: WorkloadParams) -> list[float]:
    """The outs distribution as a 0-indexed pmf list (index = outs recorded), for CRPS.

    Wraps :func:`outs_distribution` (a {outs: prob} dict) into the dense list
    ``crps_count`` expects, padding gaps with 0. Length = highest out count with mass + 1.
    """
    dist = outs_distribution(mu, params)
    hi = max(dist) if dist else 0
    return [round(dist.get(k, 0.0), 5) for k in range(hi + 1)]


def compute_starter_workload(
    outs_history: list[int],
    kbf_history: list[tuple[int, int]],
    params: WorkloadParams,
    bbbf_history: list[tuple[int, int]] | None = None,
) -> dict:
    """Bundle the workload model's outputs for one starter into a JSON-ready dict.

    Histories are most-recent-first. Returns mu_outs, the blended per-BF K and walk
    rates, P(outs > line) for each WORKLOAD_OUTS_LINES, P(K > line) for each
    WORKLOAD_K_LINES, P(BB > line) for each WORKLOAD_BB_LINES, and the sim-clamped
    starter innings. `bbbf_history` is (walks, batters_faced) per start; when absent the
    walk rate falls to the league prior (an empty history regresses fully to league).
    """
    mu = expected_outs(outs_history, params.league_mean_outs)
    kr = k_rate_blend(kbf_history, params.league_k_per_bf)
    br = bb_rate_blend(bbbf_history or [], params.league_bb_per_bf)
    innings = max(
        WORKLOAD_SIM_MIN_INNINGS,
        min(WORKLOAD_SIM_MAX_INNINGS, int(round(mu / 3.0))),
    )
    return {
        "mu_outs": round(mu, 2),
        "k_rate": round(kr, 4),
        "bb_rate": round(br, 4),
        "innings": innings,
        "p_outs": {f"{L}": round(p_outs_over(L, mu, params), 4) for L in WORKLOAD_OUTS_LINES},
        "p_k": {f"{L}": round(p_strikeouts_over(L, mu, kr, params), 4) for L in WORKLOAD_K_LINES},
        "p_bb": {f"{L}": round(p_walks_over(L, mu, br, params), 4) for L in WORKLOAD_BB_LINES},
    }
