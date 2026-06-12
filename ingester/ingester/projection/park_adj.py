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
    PARK_HIT_GEO_BETA,
    PARK_HIT_GEO_MULT_CLAMP,
    PARK_WALL_DIST_PER_FT,
    PARK_WALL_STD_FT,
    WEATHER_CARRY_EV_FLOOR_MPH,
    WEATHER_CARRY_HR_CLAMP,
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


# League-average batter, used as the weather-carry fallback for hitters with no
# batted-ball profile so EVERY batter still gets a (physically-derived) weather HR
# effect — the v2.6 "full replacement" of the old flat scalar.
LEAGUE_AVERAGE_PROFILE = BattedBallProfile(
    pull_pct=LEAGUE_PULL_PCT,
    center_pct=LEAGUE_CENTER_PCT,
    oppo_pct=LEAGUE_OPPO_PCT,
    fb_pct=LEAGUE_FB_PCT,
    avg_launch_speed=LEAGUE_EV_MPH,
)


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


def weather_carry_hr_mult(
    geo: ParkGeometry | None,
    profile: BattedBallProfile | None,
    hand: str,
    delta_carry_ft: float,
) -> float:
    """Physical weather HR multiplier (v2.6): the change in P(clear the fence) when
    the day's conditions add ``delta_carry_ft`` to this batter's fly-ball carry.

    Unlike :func:`personalized_park_hr_mult` (a ratio vs the league hitter, so the
    park/weather cancel), this is the batter's OWN clear-probability with the weather
    vs without — so the full weather signal survives, but it is now *non-linear* in
    the batter's power and the park: the same +12 ft helps a warning-track hitter far
    more than a slap hitter (who never reaches the wall) or a light-tower slugger (who
    clears it anyway). Replaces the old flat density×wind scalar. Returns 1.0 when
    there is no weather effect or no geometry/profile.
    """
    if geo is None or profile is None or delta_carry_ft == 0.0:
        return 1.0

    scale = PARK_GEO_LOGISTIC_SCALE_FT
    carry = _carry_ft(profile.avg_launch_speed)
    fence = _targeted_fence(
        geo, hand, profile.pull_pct, profile.center_pct, profile.oppo_pct
    )
    s_base = _logistic((carry - fence) / scale)
    s_today = _logistic((carry + delta_carry_ft - fence) / scale)
    if s_base <= 0.0:
        return 1.0
    raw = s_today / s_base

    # Two gates, both 1.0 at the league-average batter (so the run-env calibration
    # holds), each pulling the effect toward 1.0 for hitters carry can't help:
    #   * fly-ball rate — a grounder hitter's HR barely responds to carry;
    #   * exit velocity — a soft hitter never reaches the wall, so the steep low-tail
    #     of the logistic (which otherwise inflates their ratio) is damped out.
    fb_gate = _clamp(profile.fb_pct / LEAGUE_FB_PCT, (0.0, 1.0))
    power_gate = _clamp(
        (profile.avg_launch_speed - WEATHER_CARRY_EV_FLOOR_MPH)
        / (LEAGUE_EV_MPH - WEATHER_CARRY_EV_FLOOR_MPH),
        (0.0, 1.3),
    )
    mult = 1.0 + fb_gate * power_gate * (raw - 1.0)
    return _clamp(mult, WEATHER_CARRY_HR_CLAMP)


def personalized_park_hit_mult(
    geo: ParkGeometry | None,
    profile: BattedBallProfile | None,
    hand: str,
) -> float:
    """Per-batter multiplier on the empirical park HIT factor (v2.7, default OFF).

    Reuses the HR personalization's clear-the-fence ratio at a much smaller exponent
    (``PARK_HIT_GEO_BETA``): the only hit types fence geometry plausibly moves are
    wall-ball doubles and deep-gap drives. Ships with beta 0.0 → exactly 1.0 until a
    backtest shows signal; tightly clamped even when enabled.
    """
    if PARK_HIT_GEO_BETA == 0.0 or geo is None or profile is None:
        return 1.0

    scale = PARK_GEO_LOGISTIC_SCALE_FT
    batter_fence = _targeted_fence(
        geo, hand, profile.pull_pct, profile.center_pct, profile.oppo_pct
    )
    s_batter = _logistic((_carry_ft(profile.avg_launch_speed) - batter_fence) / scale)
    ref_fence = _targeted_fence(
        geo, hand, LEAGUE_PULL_PCT, LEAGUE_CENTER_PCT, LEAGUE_OPPO_PCT
    )
    s_ref = _logistic((PARK_CARRY_BASE_FT - ref_fence) / scale)
    if s_ref <= 0.0:
        return 1.0
    return _clamp((s_batter / s_ref) ** PARK_HIT_GEO_BETA, PARK_HIT_GEO_MULT_CLAMP)


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
    factor is further personalized to the batter's spray + carry (v2.5.0), and the
    hit factor by the (default-off) v2.7 spray-hit personalization.
    """
    hand = effective_bats(bats, pitcher_throws)
    adj_hr = (
        factors.park_factor_hr_lhb
        if hand == "L"
        else factors.park_factor_hr_rhb
    )
    adj_hr *= personalized_park_hr_mult(factors.geometry, profile, hand)
    return ParkAdjustments(
        hit=factors.park_factor_hits
        * personalized_park_hit_mult(factors.geometry, profile, hand),
        hr=adj_hr,
    )
