"""Pitcher skill adjustments vs batter handedness."""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.constants import (
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_K_PER_PA,
    MIN_BF_PITCHER_HANDEDNESS,
    PITCHER_MULT_HIT_CLAMP,
    PITCHER_MULT_HR_CLAMP,
    PITCHER_MULT_K_CLAMP,
)
from ingester.projection.weather_adj import effective_bats


@dataclass(frozen=True)
class PitcherHandSplit:
    """One ``pitcher_skill`` row (rates are per batter plate appearance)."""

    vs_handedness: str  # batter stand faced: 'L' or 'R'
    batters_faced: int
    hits_per_pa: float
    hr_per_pa: float
    k_rate: float


# Synthetic league-average pitcher used as Tier 3 fallback.
# All rates equal league averages → compute_pitcher_adjustments returns ≈ 1.0 multipliers.
LEAGUE_AVG_PITCHER = PitcherHandSplit(
    vs_handedness="*",
    batters_faced=9999,
    hits_per_pa=LEAGUE_HIT_PER_PA,
    hr_per_pa=LEAGUE_HR_PER_PA,
    k_rate=LEAGUE_K_PER_PA,
)


@dataclass(frozen=True)
class PitcherAdjustments:
    hit: float
    hr: float
    k: float


def _clamp_mult(value: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], value))


def rate_multiplier(
    pitcher_rate: float,
    league_rate: float,
    bounds: tuple[float, float],
) -> float:
    """Pitcher rate / league average, clamped so one matchup moves rates modestly."""
    if league_rate <= 0:
        return 1.0
    return _clamp_mult(pitcher_rate / league_rate, bounds)


def _weighted_rate(
    splits: list[PitcherHandSplit],
    attr: str,
) -> float:
    total_bf = sum(s.batters_faced for s in splits)
    if total_bf <= 0:
        return 0.0
    return sum(getattr(s, attr) * s.batters_faced for s in splits) / total_bf


def overall_pitcher_split(splits: list[PitcherHandSplit]) -> PitcherHandSplit:
    """BF-weighted average across both batter hands (fallback when split is thin)."""
    total_bf = sum(s.batters_faced for s in splits)
    if total_bf <= 0:
        raise ValueError("cannot average pitcher splits with zero batters_faced")
    return PitcherHandSplit(
        vs_handedness="*",
        batters_faced=total_bf,
        hits_per_pa=_weighted_rate(splits, "hits_per_pa"),
        hr_per_pa=_weighted_rate(splits, "hr_per_pa"),
        k_rate=_weighted_rate(splits, "k_rate"),
    )


def select_pitcher_split(
    splits: list[PitcherHandSplit],
    bats: str,
    pitcher_throws: str | None = None,
) -> PitcherHandSplit:
    """
    Pick the pitcher's rates vs the batter's effective hand.

    Uses the ``vs_handedness`` row when BF ≥ ``MIN_BF_PITCHER_HANDEDNESS``; otherwise
    falls back to both-hands average.
    """
    if not splits:
        raise ValueError("pitcher splits required")

    hand = effective_bats(bats, pitcher_throws)
    by_hand = {s.vs_handedness.upper(): s for s in splits}
    split = by_hand.get(hand)
    if split is not None and split.batters_faced >= MIN_BF_PITCHER_HANDEDNESS:
        return split
    return overall_pitcher_split(list(by_hand.values()))


def compute_pitcher_adjustments(split: PitcherHandSplit) -> PitcherAdjustments:
    return PitcherAdjustments(
        hit=rate_multiplier(
            split.hits_per_pa, LEAGUE_HIT_PER_PA, PITCHER_MULT_HIT_CLAMP
        ),
        hr=rate_multiplier(split.hr_per_pa, LEAGUE_HR_PER_PA, PITCHER_MULT_HR_CLAMP),
        k=rate_multiplier(split.k_rate, LEAGUE_K_PER_PA, PITCHER_MULT_K_CLAMP),
    )


def pitcher_adjustments_for_batter(
    splits: list[PitcherHandSplit],
    bats: str,
    pitcher_throws: str | None = None,
) -> PitcherAdjustments:
    """Select split (with fallback) and return hit / HR / K multipliers."""
    split = select_pitcher_split(splits, bats, pitcher_throws)
    return compute_pitcher_adjustments(split)


def resolve_pitcher_skill(
    splits: list[PitcherHandSplit],
    batter_hand: str,
    pitcher_throws: str | None = None,
) -> tuple[PitcherHandSplit, str]:
    """
    Three-tier pitcher skill resolution. Returns (split, quality_tag).

    Tier 1 'matchup'    — vs-handedness row with BF ≥ MIN_BF_PITCHER_HANDEDNESS.
    Tier 2 'overall'    — BF-weighted average of both hands when total BF ≥ threshold.
    Tier 3 'league_avg' — synthetic league-average pitcher (adjustment multipliers ≈ 1.0).
    """
    if splits:
        hand = effective_bats(batter_hand, pitcher_throws)
        by_hand = {s.vs_handedness.upper(): s for s in splits}
        matchup = by_hand.get(hand)

        # Tier 1: matchup-specific split with sufficient sample.
        if matchup is not None and matchup.batters_faced >= MIN_BF_PITCHER_HANDEDNESS:
            return matchup, "matchup"

        # Tier 2: overall both-hands average with sufficient combined sample.
        total_bf = sum(s.batters_faced for s in splits)
        if total_bf >= MIN_BF_PITCHER_HANDEDNESS:
            return overall_pitcher_split(list(by_hand.values())), "overall"

    # Tier 3: no usable data — fall back to league average.
    return LEAGUE_AVG_PITCHER, "league_avg"
