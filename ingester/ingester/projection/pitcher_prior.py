"""Marcel-style multi-year true-talent prior per pitcher (Lever 4).

The pitcher analogue of the batter prior in ``prior.py``. A pitcher's in-season
allowed rates are a noisy estimate of true talent; ``compute_pitcher_skill_rows``
already regresses them toward a baseline, but that baseline is the flat league
mean — blind to the pitcher's established skill. This module computes the better
baseline: a Marcel projection from the pitcher's prior three seasons (recency
5/4/3, BF-weighted, itself regressed toward league), per allowed rate.

Per-rate regression strength is deliberately uneven, matched to how persistent
each rate is season-to-season (premise check, 2024→2025 split, n=212):
  K% (r≈.60) light · BB% (r≈.41) medium · hits/PA (r≈.33) medium-heavy ·
  HR/PA (r≈.21) HEAVY — so the HR prior reverts to league, matching the two OOS
  tests that show pitcher HR-allowed wants the league anchor, not own-history.

The pure functions here carry the math and are unit-tested without a DB;
``ingester.commands.refresh_pitcher_priors`` wires them to the Statcast cache.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.constants import (
    MARCEL_REGRESSION_BF_BB,
    MARCEL_REGRESSION_BF_HITS,
    MARCEL_REGRESSION_BF_HR,
    MARCEL_REGRESSION_BF_K,
    MARCEL_SEASON_WEIGHTS,
)


@dataclass(frozen=True)
class PitcherSeasonLine:
    """One prior season's counting totals for a pitcher (raw, un-regressed)."""

    bf: int       # batters faced
    k: int
    bb: int
    hr: int
    hits: int


@dataclass(frozen=True)
class PitcherPrior:
    """A pitcher's projected true-talent allowed rates for one target season.

    The stable seam ``compute_pitcher_skill_rows`` regresses toward. ``proj_bf`` is
    the recency-weighted BF behind the estimate (reliability), not a BF forecast.
    """

    k_rate: float
    bb_rate: float
    hr_per_pa: float
    hits_per_pa: float
    proj_bf: int


def _weighted_regress(
    pairs: list[tuple[float, float]],  # (weighted_bf, rate) per season
    league: float,
    regression_bf: float,
) -> float:
    """BF-weighted mean of per-season rates, regressed toward league.

    proj = (Σ wbf·rate + regression_bf·league) / (Σ wbf + regression_bf).
    """
    num = regression_bf * league
    den = regression_bf
    for wbf, rate in pairs:
        num += wbf * rate
        den += wbf
    return num / den


def compute_pitcher_marcel_prior(
    seasons_by_year: dict[int, PitcherSeasonLine],
    target_season: int,
    *,
    league_k_rate: float,
    league_bb_rate: float,
    league_hr_per_pa: float,
    league_hits_per_pa: float,
    weights: tuple[int, int, int] = MARCEL_SEASON_WEIGHTS,
    regression_bf_k: float = MARCEL_REGRESSION_BF_K,
    regression_bf_bb: float = MARCEL_REGRESSION_BF_BB,
    regression_bf_hr: float = MARCEL_REGRESSION_BF_HR,
    regression_bf_hits: float = MARCEL_REGRESSION_BF_HITS,
) -> PitcherPrior | None:
    """Project ``target_season`` allowed rates from the prior three seasons.

    ``weights`` apply to (target-1, target-2, target-3). Each rate reverts to its
    league mean by its own BF regression constant (K light, HR heavy). Returns None
    when the pitcher has no usable prior-season data at all (the caller falls back
    to the flat league mean for them — i.e. pre-Lever-4 behaviour).
    """
    present: list[tuple[int, PitcherSeasonLine]] = []
    for offset, weight in enumerate(weights, start=1):
        line = seasons_by_year.get(target_season - offset)
        if line is not None and line.bf > 0:
            present.append((weight, line))
    if not present:
        return None

    k_pairs: list[tuple[float, float]] = []
    bb_pairs: list[tuple[float, float]] = []
    hr_pairs: list[tuple[float, float]] = []
    hits_pairs: list[tuple[float, float]] = []
    weighted_bf = 0
    for weight, line in present:
        wbf = weight * line.bf
        weighted_bf += wbf
        k_pairs.append((wbf, line.k / line.bf))
        bb_pairs.append((wbf, line.bb / line.bf))
        hr_pairs.append((wbf, line.hr / line.bf))
        hits_pairs.append((wbf, line.hits / line.bf))

    return PitcherPrior(
        k_rate=round(_weighted_regress(k_pairs, league_k_rate, regression_bf_k), 4),
        bb_rate=round(_weighted_regress(bb_pairs, league_bb_rate, regression_bf_bb), 4),
        hr_per_pa=round(_weighted_regress(hr_pairs, league_hr_per_pa, regression_bf_hr), 4),
        hits_per_pa=round(
            _weighted_regress(hits_pairs, league_hits_per_pa, regression_bf_hits), 4
        ),
        proj_bf=int(weighted_bf),
    )
