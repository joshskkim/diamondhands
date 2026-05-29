"""Batter projection model — pure functions combining skill blend and adjustments."""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import binom

from ingester.projection.constants import (
    AVG_BASES_PER_HIT_CLAMP,
    AVG_BASES_PER_HIT_ISO_MULT,
    EXPECTED_PA_PER_STARTER,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    PA_L30_FULL_WEIGHT,
    PROB_DECIMAL_PLACES,
    RATE_CLAMP,
    TEAM_RUNS_XWOBA_EXPONENT,
)
from ingester.projection.park_adj import ParkAdjustments
from ingester.projection.pitcher_adj import PitcherAdjustments


@dataclass(frozen=True)
class BatterSkillInput:
    xwoba: float
    xwoba_l30: float
    k_rate: float
    k_rate_l30: float
    iso: float
    iso_l30: float
    pa_l30: int


@dataclass(frozen=True)
class SkillBlends:
    xwoba: float
    k_rate: float
    iso: float
    weight_l30: float


@dataclass(frozen=True)
class BaseRates:
    hit_per_pa: float
    hr_per_pa: float
    k_per_pa: float


@dataclass(frozen=True)
class AdjustedRates:
    hit_per_pa: float
    hr_per_pa: float
    k_per_pa: float


@dataclass(frozen=True)
class BatterProbabilities:
    p_hit_1plus: float
    p_hit_2plus: float
    p_hr: float
    p_k_1plus: float


@dataclass(frozen=True)
class BatterProjection:
    """Full per-batter projection output for DB upsert."""

    expected_pa: float
    adjusted: AdjustedRates
    probabilities: BatterProbabilities
    expected_hits: float
    expected_total_bases: float
    xwoba_blend: float
    iso_blend: float
    # Audit trail (hit-side park/pitcher; weather split per schema)
    adj_park_hit: float
    adj_pitcher_hit: float
    adj_weather_hit: float
    adj_weather_hr: float


def l30_blend_weight(pa_l30: int) -> float:
    return min(pa_l30 / PA_L30_FULL_WEIGHT, 1.0)


def blend_metric(season: float, l30: float, pa_l30: int) -> float:
    w_l30 = l30_blend_weight(pa_l30)
    return l30 * w_l30 + season * (1.0 - w_l30)


def blend_batter_skills(skill: BatterSkillInput) -> SkillBlends:
    w_l30 = l30_blend_weight(skill.pa_l30)
    return SkillBlends(
        xwoba=blend_metric(skill.xwoba, skill.xwoba_l30, skill.pa_l30),
        k_rate=blend_metric(skill.k_rate, skill.k_rate_l30, skill.pa_l30),
        iso=blend_metric(skill.iso, skill.iso_l30, skill.pa_l30),
        weight_l30=w_l30,
    )


def base_rates_from_blend(blends: SkillBlends) -> BaseRates:
    hit_scale = blends.xwoba / LEAGUE_XWOBA if LEAGUE_XWOBA > 0 else 1.0
    iso_scale = blends.iso / LEAGUE_ISO if LEAGUE_ISO > 0 else 1.0
    return BaseRates(
        hit_per_pa=LEAGUE_HIT_PER_PA * hit_scale,
        hr_per_pa=LEAGUE_HR_PER_PA * iso_scale,
        k_per_pa=blends.k_rate,
    )


def clamp_rate(rate: float) -> float:
    return max(RATE_CLAMP[0], min(RATE_CLAMP[1], rate))


def adjusted_rates_from_factors(
    base: BaseRates,
    pitcher: PitcherAdjustments,
    park: ParkAdjustments,
    adj_weather_hit: float,
    adj_weather_hr: float,
) -> AdjustedRates:
    return AdjustedRates(
        hit_per_pa=clamp_rate(
            base.hit_per_pa * pitcher.hit * park.hit * adj_weather_hit
        ),
        hr_per_pa=clamp_rate(
            base.hr_per_pa * pitcher.hr * park.hr * adj_weather_hr
        ),
        k_per_pa=clamp_rate(base.k_per_pa * pitcher.k),
    )


def avg_bases_per_hit(iso_blend: float) -> float:
    raw = 1.0 + iso_blend * AVG_BASES_PER_HIT_ISO_MULT
    return max(AVG_BASES_PER_HIT_CLAMP[0], min(AVG_BASES_PER_HIT_CLAMP[1], raw))


def at_least_one_probability(rate_per_pa: float, expected_pa: float) -> float:
    return 1.0 - (1.0 - rate_per_pa) ** expected_pa


def at_least_two_hits_probability(rate_per_pa: float, expected_pa: float) -> float:
    n = int(math.floor(expected_pa))
    if n < 2:
        return 0.0
    return 1.0 - float(binom.cdf(1, n, rate_per_pa))


def compute_probabilities(
    rates: AdjustedRates,
    expected_pa: float = EXPECTED_PA_PER_STARTER,
) -> BatterProbabilities:
    return BatterProbabilities(
        p_hit_1plus=round(
            at_least_one_probability(rates.hit_per_pa, expected_pa),
            PROB_DECIMAL_PLACES,
        ),
        p_hit_2plus=round(
            at_least_two_hits_probability(rates.hit_per_pa, expected_pa),
            PROB_DECIMAL_PLACES,
        ),
        p_hr=round(
            at_least_one_probability(rates.hr_per_pa, expected_pa),
            PROB_DECIMAL_PLACES,
        ),
        p_k_1plus=round(
            at_least_one_probability(rates.k_per_pa, expected_pa),
            PROB_DECIMAL_PLACES,
        ),
    )


def compute_expected_counts(
    rates: AdjustedRates,
    iso_blend: float,
    expected_pa: float = EXPECTED_PA_PER_STARTER,
) -> tuple[float, float]:
    expected_hits = expected_pa * rates.hit_per_pa
    bases_per_hit = avg_bases_per_hit(iso_blend)
    expected_total_bases = expected_pa * rates.hit_per_pa * bases_per_hit
    return expected_hits, expected_total_bases


def project_batter(
    skill: BatterSkillInput,
    pitcher: PitcherAdjustments,
    park: ParkAdjustments,
    adj_weather_hit: float,
    adj_weather_hr: float,
    expected_pa: float = EXPECTED_PA_PER_STARTER,
) -> BatterProjection:
    """
    Compute full batter projection from blended skill and environment adjustments.

    v1 uses a flat ``expected_pa`` for every starter (lineup order unknown).
    """
    blends = blend_batter_skills(skill)
    base = base_rates_from_blend(blends)
    adjusted = adjusted_rates_from_factors(
        base, pitcher, park, adj_weather_hit, adj_weather_hr
    )
    probs = compute_probabilities(adjusted, expected_pa)
    exp_hits, exp_tb = compute_expected_counts(adjusted, blends.iso, expected_pa)

    return BatterProjection(
        expected_pa=expected_pa,
        adjusted=adjusted,
        probabilities=probs,
        expected_hits=exp_hits,
        expected_total_bases=exp_tb,
        xwoba_blend=blends.xwoba,
        iso_blend=blends.iso,
        adj_park_hit=park.hit,
        adj_pitcher_hit=pitcher.hit,
        adj_weather_hit=adj_weather_hit,
        adj_weather_hr=adj_weather_hr,
    )


def expected_team_runs(
    starter_xwoba_blends: list[float],
    park_factor_hits: float,
    adj_weather_hit_avg: float,
) -> float:
    """
    v1 team run proxy — weak; proper RE24 / base-out matrix is v2+.

    Pythagorean-ish scaling on mean starter xwOBA, park hits, and mean weather hit adj.
    """
    if not starter_xwoba_blends:
        return 0.0
    team_xwoba_avg = sum(starter_xwoba_blends) / len(starter_xwoba_blends)
    scale = (team_xwoba_avg / LEAGUE_XWOBA) ** TEAM_RUNS_XWOBA_EXPONENT
    return (
        LEAGUE_RUNS_PER_GAME_BASE
        * scale
        * park_factor_hits
        * adj_weather_hit_avg
    )
