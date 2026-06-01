"""Batter projection model — pure functions combining skill blend and adjustments."""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import binom

from ingester.projection.constants import (
    ADJUSTED_HIT_PER_PA_CLAMP,
    ADJUSTED_HR_PER_PA_CLAMP,
    ADJUSTED_K_PER_PA_CLAMP,
    AVG_BASES_PER_HIT_CLAMP,
    AVG_BASES_PER_HIT_ISO_MULT,
    EXPECTED_PA_PER_STARTER,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    PA_L30_BLEND_CAP,
    PA_L30_FULL_WEIGHT,
    PROB_DECIMAL_PLACES,
    SHRINKAGE_ALPHA,
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
    """L30 capped at 60% of blend; needs pa_l30 > 0 (NULL L30 → season-only)."""
    if pa_l30 <= 0:
        return 0.0
    return min(pa_l30 / PA_L30_FULL_WEIGHT, PA_L30_BLEND_CAP)


def blend_metric(season: float, l30: float | None, pa_l30: int) -> float:
    w_l30 = l30_blend_weight(pa_l30)
    if w_l30 <= 0 or l30 is None:
        return season
    return l30 * w_l30 + season * (1.0 - w_l30)


def blend_batter_skills(skill: BatterSkillInput) -> SkillBlends:
    w_l30 = l30_blend_weight(skill.pa_l30)
    l30_xwoba = skill.xwoba_l30 if skill.pa_l30 > 0 else None
    l30_k = skill.k_rate_l30 if skill.pa_l30 > 0 else None
    l30_iso = skill.iso_l30 if skill.pa_l30 > 0 else None
    return SkillBlends(
        xwoba=blend_metric(skill.xwoba, l30_xwoba, skill.pa_l30),
        k_rate=blend_metric(skill.k_rate, l30_k, skill.pa_l30),
        iso=blend_metric(skill.iso, l30_iso, skill.pa_l30),
        weight_l30=w_l30,
    )


def base_rates_from_blend(blends: SkillBlends) -> BaseRates:
    """Hit rate from xwOBA; HR rate from ISO (power), not overall offensive value."""
    hit_scale = blends.xwoba / LEAGUE_XWOBA if LEAGUE_XWOBA > 0 else 1.0
    iso_scale = blends.iso / LEAGUE_ISO if LEAGUE_ISO > 0 else 1.0
    return BaseRates(
        hit_per_pa=LEAGUE_HIT_PER_PA * hit_scale,
        hr_per_pa=LEAGUE_HR_PER_PA * iso_scale,
        k_per_pa=blends.k_rate,
    )


def _clamp(rate: float, low: float, high: float) -> float:
    return max(low, min(high, rate))


def adjusted_rates_from_factors(
    base: BaseRates,
    pitcher: PitcherAdjustments,
    park: ParkAdjustments,
    adj_weather_hit: float,
    adj_weather_hr: float,
) -> AdjustedRates:
    return AdjustedRates(
        hit_per_pa=_clamp(
            base.hit_per_pa * pitcher.hit * park.hit * adj_weather_hit,
            *ADJUSTED_HIT_PER_PA_CLAMP,
        ),
        hr_per_pa=_clamp(
            base.hr_per_pa * pitcher.hr * park.hr * adj_weather_hr,
            *ADJUSTED_HR_PER_PA_CLAMP,
        ),
        k_per_pa=_clamp(
            base.k_per_pa * pitcher.k,
            *ADJUSTED_K_PER_PA_CLAMP,
        ),
    )


def shrink_rates(rates: AdjustedRates) -> AdjustedRates:
    """
    Pull adjusted per-PA rates toward league means before probabilities (v1.5.3).

    The multiplicative adjustment chain (skill × pitcher × park × weather) compounds
    and over-states the tails — a top batter in a good matchup stacks several
    multipliers on an already-elite base. Blending each rate toward its league mean
    by SHRINKAGE_ALPHA reins that in.
    """
    a = SHRINKAGE_ALPHA
    return AdjustedRates(
        hit_per_pa=(1.0 - a) * rates.hit_per_pa + a * LEAGUE_HIT_PER_PA,
        hr_per_pa=(1.0 - a) * rates.hr_per_pa + a * LEAGUE_HR_PER_PA,
        k_per_pa=(1.0 - a) * rates.k_per_pa + a * LEAGUE_K_PER_PA,
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
    matchup_xwoba: float | None = None,
    matchup_k_rate: float | None = None,
    matchup_iso: float | None = None,
) -> BatterProjection:
    """
    Compute full batter projection from blended skill and environment adjustments.

    Expected PA comes from the confirmed batting order (v2.0) or a flat fallback.

    v2.1: when ``matchup_*`` are supplied, the season/L30 skill blend is replaced by
    the pitch-mix matchup values — xwOBA drives hit rate, k_rate drives the K rate,
    ISO drives HR rate. All downstream adjustments (pitcher, park, weather,
    shrinkage, clamps) are unchanged. Omitting them reproduces v2.0.0 exactly.
    """
    blends = blend_batter_skills(skill)
    if matchup_xwoba is not None:
        blends = SkillBlends(
            xwoba=matchup_xwoba,
            k_rate=matchup_k_rate if matchup_k_rate is not None else blends.k_rate,
            iso=matchup_iso if matchup_iso is not None else blends.iso,
            weight_l30=blends.weight_l30,
        )
    base = base_rates_from_blend(blends)
    adjusted = adjusted_rates_from_factors(
        base, pitcher, park, adj_weather_hit, adj_weather_hr
    )
    # Shrink toward league means before deriving any outputs so probabilities and
    # expected counts stay consistent with the rates actually stored for audit.
    adjusted = shrink_rates(adjusted)
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
