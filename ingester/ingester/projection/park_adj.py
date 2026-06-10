"""Park factor adjustments from stadium metadata.

Two layers:
  * the empirical handedness HR factor + hit factor (league-wide, well-calibrated);
  * a per-batter personalization (v2.5.0) that nudges the HR factor for how a
    specific hitter's spray + power make THIS park's fence geometry play shorter
    or longer for them than it does for the average hitter of their hand.

The personalization is a RATIO of "clear-the-fence" probability — this batter vs
the league-average hitter, evaluated in the same park. Because both sides run
through the same coarse carry curve and the same spray→fence interpolation, the
absolute errors in those models largely cancel; what survives is the batter's
deviation in pull tendency and exit velocity. The ratio multiplies the empirical
factor and is clamped, so it can only nudge, never dominate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ingester.projection.constants import (
    LEAGUE_CENTER_PCT,
    LEAGUE_EV_MPH,
    LEAGUE_FB_PCT,
    LEAGUE_OPPO_PCT,
    LEAGUE_PULL_PCT,
    PARK_CARRY_BASE_FT,
    PARK_CARRY_PER_MPH,
    PARK_FENCE_OPPO_FRAC,
    PARK_FENCE_PULL_FRAC,
    PARK_GEO_BETA,
    PARK_GEO_LOGISTIC_SCALE_FT,
    PARK_GEO_MULT_CLAMP,
    PARK_WALL_DIST_PER_FT,
    PARK_WALL_STD_FT,
)
from ingester.projection.weather_adj import effective_bats


@dataclass(frozen=True)
class ParkGeometry:
    """Outfield fence distances (ft) and wall heights (ft) for one park."""

    lf_line_ft: float
    cf_ft: float
    rf_line_ft: float
    lf_wall_ft: float
    cf_wall_ft: float
    rf_wall_ft: float


@dataclass(frozen=True)
class BattedBallProfile:
    """One batter's batted-ball tendencies (from batter_batted_ball)."""

    pull_pct: float
    center_pct: float
    oppo_pct: float
    fb_pct: float
    avg_launch_speed: float  # mph (exit velocity, all batted balls)


@dataclass(frozen=True)
class ParkFactors:
    park_factor_hits: float = 1.0
    park_factor_hr_lhb: float = 1.0
    park_factor_hr_rhb: float = 1.0
    geometry: ParkGeometry | None = None


@dataclass(frozen=True)
class ParkAdjustments:
    hit: float
    hr: float


def _clamp(v: float, bounds: tuple[float, float]) -> float:
    return max(bounds[0], min(bounds[1], v))


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _interp_fence(line_ft: float, cf_ft: float, frac: float, wall_ft: float) -> float:
    """Effective fence distance at a spray angle ``frac`` of the way from CF (0)
    to the foul line (1), plus an added-distance penalty for a tall wall."""
    dist = cf_ft * (1.0 - frac) + line_ft * frac
    wall_penalty = PARK_WALL_DIST_PER_FT * max(wall_ft - PARK_WALL_STD_FT, 0.0)
    return dist + wall_penalty


def _targeted_fence(
    geo: ParkGeometry, hand: str, pull_pct: float, center_pct: float, oppo_pct: float
) -> float:
    """Spray-weighted effective fence distance a hitter must clear in this park.

    Pull/oppo map to the L/R foul-line distances by batting hand: a RHB pulls to
    left field, a LHB to right. Center always targets CF.
    """
    if hand == "L":
        pull_line, pull_wall = geo.rf_line_ft, geo.rf_wall_ft
        oppo_line, oppo_wall = geo.lf_line_ft, geo.lf_wall_ft
    else:
        pull_line, pull_wall = geo.lf_line_ft, geo.lf_wall_ft
        oppo_line, oppo_wall = geo.rf_line_ft, geo.rf_wall_ft

    fence_pull = _interp_fence(pull_line, geo.cf_ft, PARK_FENCE_PULL_FRAC, pull_wall)
    fence_center = _interp_fence(geo.cf_ft, geo.cf_ft, 0.0, geo.cf_wall_ft)
    fence_oppo = _interp_fence(oppo_line, geo.cf_ft, PARK_FENCE_OPPO_FRAC, oppo_wall)
    return pull_pct * fence_pull + center_pct * fence_center + oppo_pct * fence_oppo


def _carry_ft(avg_launch_speed: float) -> float:
    """Carry of the batter's typical authoritative fly ball from average EV.

    Anchored so a league-average-EV hitter carries ``PARK_CARRY_BASE_FT``; only
    the deviation from league EV matters (the ratio cancels the rest)."""
    return PARK_CARRY_BASE_FT + PARK_CARRY_PER_MPH * (avg_launch_speed - LEAGUE_EV_MPH)


def personalized_park_hr_mult(
    geo: ParkGeometry | None,
    profile: BattedBallProfile | None,
    hand: str,
) -> float:
    """Per-batter multiplier on the empirical park HR factor (1.0 = no change).

    Returns 1.0 when geometry or profile is missing, so the empirical factor
    stands alone. ``hand`` is the effective batting side ('L'/'R').
    """
    if geo is None or profile is None:
        return 1.0

    scale = PARK_GEO_LOGISTIC_SCALE_FT

    # This batter: their spray + their carry.
    batter_fence = _targeted_fence(
        geo, hand, profile.pull_pct, profile.center_pct, profile.oppo_pct
    )
    s_batter = _logistic((_carry_ft(profile.avg_launch_speed) - batter_fence) / scale)

    # Reference: the league-average hitter of this hand, same park.
    ref_fence = _targeted_fence(
        geo, hand, LEAGUE_PULL_PCT, LEAGUE_CENTER_PCT, LEAGUE_OPPO_PCT
    )
    s_ref = _logistic((PARK_CARRY_BASE_FT - ref_fence) / scale)

    if s_ref <= 0.0:
        return 1.0
    raw_mult = _clamp((s_batter / s_ref) ** PARK_GEO_BETA, PARK_GEO_MULT_CLAMP)

    # Gate by fly-ball rate: a grounder-heavy hitter clears no fence regardless of
    # which one they aim at, so dampen the spray personalization toward 1.0.
    gate = _clamp(profile.fb_pct / LEAGUE_FB_PCT, (0.0, 1.0))
    geo_mult = 1.0 + gate * (raw_mult - 1.0)
    return _clamp(geo_mult, PARK_GEO_MULT_CLAMP)


def compute_park_adjustments(
    factors: ParkFactors,
    bats: str,
    pitcher_throws: str | None = None,
    profile: BattedBallProfile | None = None,
) -> ParkAdjustments:
    """
    Return per-outcome park multipliers.

    HR factor is handedness-specific; switch hitters use the side opposite the
    pitcher's throwing hand (same rule as pitcher matchup and weather pull). When
    a batted-ball ``profile`` and the park ``geometry`` are both present, the HR
    factor is further personalized to the batter's spray + carry (v2.5.0).
    """
    hand = effective_bats(bats, pitcher_throws)
    adj_hr = (
        factors.park_factor_hr_lhb
        if hand == "L"
        else factors.park_factor_hr_rhb
    )
    adj_hr *= personalized_park_hr_mult(factors.geometry, profile, hand)
    return ParkAdjustments(
        hit=factors.park_factor_hits,
        hr=adj_hr,
    )
