"""Empirical-rate shrinkage blend — a Python port of the API's `PropBlend`.

The serving layer (api/.../service/PropBlend.java) regresses a model probability toward
the player's demonstrated season clear rate before it reaches the board. That transform
lives in Java and reads `ClearRateRepository`, so the projection engine and the backtest
harness — both Python — never see it. This module reimplements the same arithmetic so the
backtest can score the blended probability against actuals (see `backtest --clear-rate-blend`).

Kept deliberately faithful to the Java, constants included; a divergence would make the
backtest measure a blend the site never serves. `tests/test_prop_blend.py` pins the two
implementations to the same hand-computed values.
"""
from __future__ import annotations

# Two-stage shrinkage constants — must match PropBlend.java.
SHRINK_K = 60
PRIOR_N = 25

# The one line each market's clear rate measures, and the league-average rate at it.
# Mirrors PropBlend.CANONICAL / ClearRateRepository's SQL. A blend is only legitimate at
# the canonical line — the clear rate counts a different event at any other line.
_CANONICAL: dict[str, tuple[float, float]] = {
    "hit": (0.5, 0.62),
    "hr": (0.5, 0.15),
    "bb": (0.5, 0.30),
    "tb": (1.5, 0.31),
    "hrr": (1.5, 0.44),
}


def blend(model_prob: float, season_rate: float | None, n_season: int | None,
          league_rate: float) -> float:
    """Blend the model's probability toward a league-stabilized empirical clear rate.

    Stage 1 stabilizes the season rate with PRIOR_N phantom league games; stage 2 weights
    that empirical target by how much evidence backs it. A player with no prior games
    (n=0, rate None) regresses PRIOR_N/(PRIOR_N+SHRINK_K) of the way to the league rate —
    the early-season behavior the live board shows.
    """
    n = 0 if (season_rate is None or n_season is None) else max(n_season, 0)
    season = league_rate if season_rate is None else season_rate
    empirical = (n * season + PRIOR_N * league_rate) / (n + PRIOR_N)
    w = (n + PRIOR_N) / (n + PRIOR_N + SHRINK_K)
    return w * empirical + (1.0 - w) * model_prob


def blend_market(market: str, line: float, raw: float | None,
                 season_rate: float | None, n_season: int | None) -> float | None:
    """Blended probability for a prop selection, or `raw` unchanged when this market/line
    has no comparable clear rate (pitcher markets, off-canonical lines). Null in → null out.
    """
    canonical = _CANONICAL.get(market)
    if raw is None or canonical is None or abs(canonical[0] - line) > 1e-9:
        return raw
    return blend(raw, season_rate, n_season, canonical[1])
