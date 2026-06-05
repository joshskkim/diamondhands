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
    LEAGUE_1B_SHARE,
    LEAGUE_2B_SHARE,
    LEAGUE_3B_SHARE,
    LEAGUE_BB_PER_PA,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_PA_PER_GAME,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    LW_DOUBLE,
    LW_HOMERUN,
    LW_SINGLE,
    LW_TRIPLE,
    LW_WALK,
    PA_L30_BLEND_CAP,
    PA_L30_FULL_WEIGHT,
    PROB_DECIMAL_PLACES,
    SHRINKAGE_ALPHA,
    STARTER_PA_SHARE,
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


def league_average_projection(expected_pa: float) -> BatterProjection:
    """A league-average batter projection, used to pad confirmed lineups missing skill."""
    rates = AdjustedRates(
        hit_per_pa=LEAGUE_HIT_PER_PA,
        hr_per_pa=LEAGUE_HR_PER_PA,
        k_per_pa=LEAGUE_K_PER_PA,
    )
    return BatterProjection(
        expected_pa=expected_pa,
        adjusted=rates,
        probabilities=BatterProbabilities(0.0, 0.0, 0.0, 0.0),
        expected_hits=expected_pa * LEAGUE_HIT_PER_PA,
        expected_total_bases=0.0,
        xwoba_blend=LEAGUE_XWOBA,
        iso_blend=LEAGUE_ISO,
        adj_park_hit=1.0,
        adj_pitcher_hit=1.0,
        adj_weather_hit=1.0,
        adj_weather_hr=1.0,
    )


def _blended_hit_hr(
    starter: BatterProjection,
    bullpen: BatterProjection | None,
    starter_share: float,
) -> tuple[float, float]:
    """Per-PA (hit, HR) rates blending the starter- and bullpen-faced projections."""
    s_hit = starter.adjusted.hit_per_pa
    s_hr = starter.adjusted.hr_per_pa
    if bullpen is None:
        return s_hit, s_hr
    b_hit = bullpen.adjusted.hit_per_pa
    b_hr = bullpen.adjusted.hr_per_pa
    return (
        starter_share * s_hit + (1.0 - starter_share) * b_hit,
        starter_share * s_hr + (1.0 - starter_share) * b_hr,
    )


def expected_team_runs(
    starters: list[BatterProjection],
    bullpen: list[BatterProjection] | None = None,
    starter_share: float = STARTER_PA_SHARE,
) -> float:
    """
    Expected team runs (v2.2): linear weights on each batter's projected events.

    For every starter we already have fully-adjusted per-PA rates (skill + matchup +
    park + weather). When ``bullpen`` is supplied (aligned by lineup index, the same
    hitters re-projected against the opposing team's relief staff), each batter's
    hit/HR rates are blended ``starter_share`` vs the starter and the rest vs the
    bullpen. We then turn rates into expected singles/doubles/triples/HR/BB counts,
    and score the team's *deviation from league average at the same PA total* with
    standard linear weights, anchored at ``LEAGUE_RUNS_PER_GAME_BASE``. A perfectly
    league-average lineup yields the anchor (scaled by actual PA); park/weather/matchup
    move it from there. No separate park/weather factor here — those are already baked
    into the per-PA rates (the v1 proxy double-counted park).
    """
    if not starters:
        return 0.0

    total_pa = 0.0
    team_1b = team_2b = team_3b = team_hr = team_bb = 0.0
    for i, starter in enumerate(starters):
        pen = bullpen[i] if bullpen is not None and i < len(bullpen) else None
        hit, hr = _blended_hit_hr(starter, pen, starter_share)
        non_hr = max(hit - hr, 0.0)
        pa = starter.expected_pa
        total_pa += pa
        team_hr += pa * hr
        team_1b += pa * non_hr * LEAGUE_1B_SHARE
        team_2b += pa * non_hr * LEAGUE_2B_SHARE
        team_3b += pa * non_hr * LEAGUE_3B_SHARE
        team_bb += pa * LEAGUE_BB_PER_PA  # flat league BB (per-batter BB is a later refinement)

    if total_pa <= 0:
        return 0.0

    # League-average event counts at this PA total (the deviation baseline).
    lg_non_hr = max(LEAGUE_HIT_PER_PA - LEAGUE_HR_PER_PA, 0.0)
    lg_1b = total_pa * lg_non_hr * LEAGUE_1B_SHARE
    lg_2b = total_pa * lg_non_hr * LEAGUE_2B_SHARE
    lg_3b = total_pa * lg_non_hr * LEAGUE_3B_SHARE
    lg_hr = total_pa * LEAGUE_HR_PER_PA
    lg_bb = total_pa * LEAGUE_BB_PER_PA

    runs = LEAGUE_RUNS_PER_GAME_BASE * (total_pa / LEAGUE_PA_PER_GAME)
    runs += LW_SINGLE * (team_1b - lg_1b)
    runs += LW_DOUBLE * (team_2b - lg_2b)
    runs += LW_TRIPLE * (team_3b - lg_3b)
    runs += LW_HOMERUN * (team_hr - lg_hr)
    runs += LW_WALK * (team_bb - lg_bb)
    return max(runs, 0.0)


@dataclass(frozen=True)
class PitcherLine:
    """A probable starter's projected line, aggregated from the opposing lineup."""

    expected_bf: float
    expected_outs: float
    expected_ip: float
    expected_k: float
    expected_h: float
    expected_hr: float
    expected_bb: float
    expected_runs: float


def pitcher_line_from_lineup(
    opposing_starters: list[BatterProjection],
    starter_share: float = STARTER_PA_SHARE,
) -> PitcherLine:
    """
    Project the starter's line by aggregating the opposing lineup he faces.

    Each opposing batter's fully-adjusted per-PA rates (the same matchup/park/weather
    projection used for their props) are summed over the batters the starter is expected
    to face — ``starter_share`` of each batter's plate appearances (~60%, the rest go to
    the bullpen). Outs ≈ BF − hits − walks; runs allowed ≈ the starter's PA-share of the
    lineup's starter-only expected team runs.
    """
    bf = k = h = hr = bb = 0.0
    for proj in opposing_starters:
        faced = starter_share * proj.expected_pa
        bf += faced
        k += faced * proj.adjusted.k_per_pa
        h += faced * proj.adjusted.hit_per_pa
        hr += faced * proj.adjusted.hr_per_pa
        bb += faced * LEAGUE_BB_PER_PA
    outs = max(bf - h - bb, 0.0)
    runs = starter_share * expected_team_runs(opposing_starters)
    return PitcherLine(
        expected_bf=bf,
        expected_outs=outs,
        expected_ip=outs / 3.0,
        expected_k=k,
        expected_h=h,
        expected_hr=hr,
        expected_bb=bb,
        expected_runs=runs,
    )
