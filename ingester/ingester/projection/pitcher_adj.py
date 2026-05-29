"""Pitcher skill adjustments vs batter handedness."""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.constants import (
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_K_PER_PA,
    MIN_BF_PITCHER_HANDEDNESS,
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


@dataclass(frozen=True)
class PitcherAdjustments:
    hit: float
    hr: float
    k: float


def rate_multiplier(pitcher_rate: float, league_rate: float) -> float:
    """Pitcher rate divided by league average (e.g. 30% K vs 22% league → 1.36)."""
    if league_rate <= 0:
        return 1.0
    return pitcher_rate / league_rate


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
        hit=rate_multiplier(split.hits_per_pa, LEAGUE_HIT_PER_PA),
        hr=rate_multiplier(split.hr_per_pa, LEAGUE_HR_PER_PA),
        k=rate_multiplier(split.k_rate, LEAGUE_K_PER_PA),
    )


def pitcher_adjustments_for_batter(
    splits: list[PitcherHandSplit],
    bats: str,
    pitcher_throws: str | None = None,
) -> PitcherAdjustments:
    """Select split (with fallback) and return hit / HR / K multipliers."""
    split = select_pitcher_split(splits, bats, pitcher_throws)
    return compute_pitcher_adjustments(split)
