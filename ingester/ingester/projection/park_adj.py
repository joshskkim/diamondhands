"""Park factor adjustments from stadium metadata."""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.weather_adj import effective_bats


@dataclass(frozen=True)
class ParkFactors:
    park_factor_hits: float = 1.0
    park_factor_hr_lhb: float = 1.0
    park_factor_hr_rhb: float = 1.0


@dataclass(frozen=True)
class ParkAdjustments:
    hit: float
    hr: float


def compute_park_adjustments(
    factors: ParkFactors,
    bats: str,
    pitcher_throws: str | None = None,
) -> ParkAdjustments:
    """
    Return per-outcome park multipliers.

    HR factor is handedness-specific; switch hitters use the side opposite the
    pitcher's throwing hand (same rule as pitcher matchup and weather pull).
    """
    hand = effective_bats(bats, pitcher_throws)
    adj_hr = (
        factors.park_factor_hr_lhb
        if hand == "L"
        else factors.park_factor_hr_rhb
    )
    return ParkAdjustments(
        hit=factors.park_factor_hits,
        hr=adj_hr,
    )
