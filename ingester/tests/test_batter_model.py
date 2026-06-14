"""Hand-computed unit test for the batter projection model."""
from __future__ import annotations

import math
import unittest

from scipy.stats import binom

from ingester.projection.batter_model import (
    AdjustedRates,
    BatterProbabilities,
    BatterProjection,
    BatterSkillInput,
    SkillBlends,
    adjusted_rates_from_factors,
    base_rates_from_blend,
    blend_batter_skills,
    expected_team_runs,
    l30_blend_weight,
    league_average_projection,
    project_batter,
)
from ingester.projection.constants import (
    ADJUSTED_HIT_PER_PA_CLAMP,
    ADJUSTED_HR_PER_PA_CLAMP,
    ADJUSTED_K_PER_PA_CLAMP,
    EXPECTED_PA_PER_STARTER,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    PITCHER_MULT_HR_CLAMP,
    LEAGUE_PA_PER_GAME,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    PA_L30_BLEND_CAP,
    PA_L30_FULL_WEIGHT,
    PITCHER_MULT_HIT_CLAMP,
    SHRINKAGE_ALPHA,
)
from ingester.projection.park_adj import ParkAdjustments
from ingester.projection.pitcher_adj import (
    PitcherAdjustments,
    PitcherHandSplit,
    compute_pitcher_adjustments,
)


class TestBatterModelHandComputed(unittest.TestCase):
    """
    Synthetic batter with pa_l30=50 → weight min(50/150, 0.6) = 1/3.

    xwOBA 0.340 / 0.360 → blend 0.3533…
    K%    0.200 / 0.240 → blend 0.2133…
    ISO   0.170 / 0.190 → blend 0.1767…

    Hit/PA from xwOBA; HR/PA from ISO (not xwOBA).
    """

    SKILL = BatterSkillInput(
        xwoba=0.340,
        xwoba_l30=0.360,
        k_rate=0.200,
        k_rate_l30=0.240,
        iso=0.170,
        iso_l30=0.190,
        pa_l30=50,
    )
    PITCHER = PitcherAdjustments(hit=1.1, hr=0.9, k=1.2)
    PARK = ParkAdjustments(hit=1.05, hr=1.10)
    ADJ_WEATHER_HIT = 1.02
    ADJ_WEATHER_HR = 1.0

    @classmethod
    def setUpClass(cls) -> None:
        cls.W_L30 = l30_blend_weight(50)
        cls.XWOBA_BLEND = 0.360 * cls.W_L30 + 0.340 * (1 - cls.W_L30)
        cls.K_BLEND = 0.240 * cls.W_L30 + 0.200 * (1 - cls.W_L30)
        cls.ISO_BLEND = 0.190 * cls.W_L30 + 0.170 * (1 - cls.W_L30)

        cls.BASE_HIT = LEAGUE_HIT_PER_PA * (cls.XWOBA_BLEND / LEAGUE_XWOBA)
        cls.BASE_HR = LEAGUE_HR_PER_PA * (cls.ISO_BLEND / LEAGUE_ISO)
        cls.BASE_K = cls.K_BLEND

        # Multiplicative adjustment chain, then the v1.5.3 shrinkage toward league
        # means (shrink_rates: (1-α)·adjusted + α·league) that project_batter applies.
        adj_hit = cls.BASE_HIT * cls.PITCHER.hit * cls.PARK.hit * cls.ADJ_WEATHER_HIT
        adj_hr = cls.BASE_HR * cls.PITCHER.hr * cls.PARK.hr * cls.ADJ_WEATHER_HR
        adj_k = cls.BASE_K * cls.PITCHER.k
        a = SHRINKAGE_ALPHA
        cls.ADJ_HIT = (1 - a) * adj_hit + a * LEAGUE_HIT_PER_PA
        cls.ADJ_HR = (1 - a) * adj_hr + a * LEAGUE_HR_PER_PA
        cls.ADJ_K = (1 - a) * adj_k + a * LEAGUE_K_PER_PA

        pa = EXPECTED_PA_PER_STARTER
        cls.EXP_P_HIT_1 = round(1 - (1 - cls.ADJ_HIT) ** pa, 4)
        cls.EXP_P_HIT_2 = round(
            1 - float(binom.cdf(1, int(math.floor(pa)), cls.ADJ_HIT)),
            4,
        )
        cls.EXP_P_HR = round(1 - (1 - cls.ADJ_HR) ** pa, 4)
        cls.EXP_P_K = round(1 - (1 - cls.ADJ_K) ** pa, 4)

        bases_per_hit = 1.0 + cls.ISO_BLEND * 3.0
        cls.EXP_HITS = pa * cls.ADJ_HIT
        cls.EXP_TB = pa * cls.ADJ_HIT * bases_per_hit

    def test_l30_weight_cap(self) -> None:
        # Cap-aware: at the hot-hand-audit default (cap 0.0) recent form carries zero
        # weight; under an env-override sweep the ramp min(pa/150, cap) still holds.
        self.assertAlmostEqual(self.W_L30, min(50 / PA_L30_FULL_WEIGHT, PA_L30_BLEND_CAP))
        self.assertLessEqual(self.W_L30, PA_L30_BLEND_CAP)
        self.assertAlmostEqual(l30_blend_weight(0), 0.0)
        self.assertAlmostEqual(l30_blend_weight(500), PA_L30_BLEND_CAP)

    def test_blend_weights(self) -> None:
        blends = blend_batter_skills(self.SKILL)
        self.assertAlmostEqual(blends.weight_l30, self.W_L30)
        self.assertAlmostEqual(blends.xwoba, self.XWOBA_BLEND)
        self.assertAlmostEqual(blends.k_rate, self.K_BLEND)
        self.assertAlmostEqual(blends.iso, self.ISO_BLEND)

    def test_hr_uses_iso_not_xwoba(self) -> None:
        blends = SkillBlends(
            xwoba=0.400,
            k_rate=0.22,
            iso=0.120,
            weight_l30=0.0,
        )
        base = base_rates_from_blend(blends)
        xwoba_only_hr = LEAGUE_HR_PER_PA * (0.400 / LEAGUE_XWOBA)
        self.assertAlmostEqual(base.hit_per_pa, LEAGUE_HIT_PER_PA * (0.400 / LEAGUE_XWOBA))
        self.assertAlmostEqual(base.hr_per_pa, LEAGUE_HR_PER_PA * (0.120 / LEAGUE_ISO))
        self.assertNotAlmostEqual(base.hr_per_pa, xwoba_only_hr, places=3)

    def test_hr_barrel_blend(self) -> None:
        from ingester.projection.constants import HR_BARREL_BLEND_W, LEAGUE_BARREL_RATE
        kw = dict(xwoba=0.32, k_rate=0.22, iso=LEAGUE_ISO, weight_l30=0.0)
        # No barrel -> pure ISO basis (league ISO -> league HR).
        self.assertAlmostEqual(
            base_rates_from_blend(SkillBlends(**kw)).hr_per_pa, LEAGUE_HR_PER_PA
        )
        # Barrel at the league rate leaves HR at league (no nudge).
        self.assertAlmostEqual(
            base_rates_from_blend(SkillBlends(**kw, barrel_rate=LEAGUE_BARREL_RATE)).hr_per_pa,
            LEAGUE_HR_PER_PA,
        )
        # High barrel scales HR up by the blended factor (ISO held at league).
        hi = base_rates_from_blend(SkillBlends(**kw, barrel_rate=0.13))
        expected_scale = (1 - HR_BARREL_BLEND_W) * 1.0 + HR_BARREL_BLEND_W * (0.13 / LEAGUE_BARREL_RATE)
        self.assertAlmostEqual(hi.hr_per_pa, LEAGUE_HR_PER_PA * expected_scale)
        self.assertGreater(hi.hr_per_pa, LEAGUE_HR_PER_PA)

    def test_base_rates(self) -> None:
        blends = SkillBlends(
            xwoba=self.XWOBA_BLEND,
            k_rate=self.K_BLEND,
            iso=self.ISO_BLEND,
            weight_l30=self.W_L30,
        )
        base = base_rates_from_blend(blends)
        self.assertAlmostEqual(base.hit_per_pa, self.BASE_HIT, places=6)
        self.assertAlmostEqual(base.hr_per_pa, self.BASE_HR, places=6)
        self.assertAlmostEqual(base.k_per_pa, self.BASE_K, places=6)

    def test_full_projection_matches_hand_math(self) -> None:
        proj = project_batter(
            self.SKILL,
            self.PITCHER,
            self.PARK,
            self.ADJ_WEATHER_HIT,
            self.ADJ_WEATHER_HR,
        )

        self.assertAlmostEqual(proj.xwoba_blend, self.XWOBA_BLEND)
        self.assertAlmostEqual(proj.iso_blend, self.ISO_BLEND)
        self.assertAlmostEqual(proj.adjusted.hit_per_pa, self.ADJ_HIT, places=6)
        self.assertAlmostEqual(proj.adjusted.hr_per_pa, self.ADJ_HR, places=6)
        self.assertAlmostEqual(proj.adjusted.k_per_pa, self.ADJ_K, places=6)
        self.assertLessEqual(proj.probabilities.p_hr, 0.40)

        self.assertEqual(proj.probabilities.p_hit_1plus, self.EXP_P_HIT_1)
        self.assertEqual(proj.probabilities.p_hit_2plus, self.EXP_P_HIT_2)
        self.assertEqual(proj.probabilities.p_hr, self.EXP_P_HR)
        self.assertEqual(proj.probabilities.p_k_1plus, self.EXP_P_K)

        self.assertAlmostEqual(proj.expected_hits, self.EXP_HITS, places=4)
        self.assertAlmostEqual(proj.expected_total_bases, self.EXP_TB, places=4)


class TestAdjustedRateClamps(unittest.TestCase):
    def test_extreme_hr_clamped(self) -> None:
        base = base_rates_from_blend(
            SkillBlends(xwoba=0.45, k_rate=0.20, iso=0.35, weight_l30=0.0)
        )
        pitcher = PitcherAdjustments(hit=1.3, hr=1.5, k=1.4)
        park = ParkAdjustments(hit=1.05, hr=1.4)
        rates = adjusted_rates_from_factors(base, pitcher, park, 1.05, 1.2)
        self.assertLessEqual(rates.hr_per_pa, ADJUSTED_HR_PER_PA_CLAMP[1])
        self.assertGreaterEqual(rates.hr_per_pa, ADJUSTED_HR_PER_PA_CLAMP[0])
        self.assertLessEqual(rates.hit_per_pa, ADJUSTED_HIT_PER_PA_CLAMP[1])
        self.assertLessEqual(rates.k_per_pa, ADJUSTED_K_PER_PA_CLAMP[1])


class TestPitcherMultiplierClamps(unittest.TestCase):
    def test_hr_mult_capped_at_ceiling(self) -> None:
        split = PitcherHandSplit(
            vs_handedness="R",
            batters_faced=200,
            hits_per_pa=0.15,
            hr_per_pa=0.06,
            k_rate=0.35,
        )
        adj = compute_pitcher_adjustments(split)
        self.assertEqual(adj.hr, PITCHER_MULT_HR_CLAMP[1])
        self.assertGreater(0.06 / LEAGUE_HR_PER_PA, PITCHER_MULT_HR_CLAMP[1])


def _proj_with_rates(hit_per_pa: float, hr_per_pa: float, pa: float) -> BatterProjection:
    """Minimal BatterProjection carrying just the per-PA rates the run model reads."""
    return BatterProjection(
        expected_pa=pa,
        adjusted=AdjustedRates(hit_per_pa=hit_per_pa, hr_per_pa=hr_per_pa, k_per_pa=0.22),
        probabilities=BatterProbabilities(0.0, 0.0, 0.0, 0.0),
        expected_hits=pa * hit_per_pa,
        expected_total_bases=0.0,
        xwoba_blend=0.0,
        iso_blend=0.0,
        adj_park_hit=1.0,
        adj_pitcher_hit=1.0,
        adj_weather_hit=1.0,
        adj_weather_hr=1.0,
    )


class TestExpectedTeamRuns(unittest.TestCase):
    def test_league_average_lineup_hits_anchor(self) -> None:
        # Nine league-average batters whose PA sums to exactly LEAGUE_PA_PER_GAME
        # must score exactly the league run anchor (deviations are all zero).
        pa_each = LEAGUE_PA_PER_GAME / 9.0
        lineup = [league_average_projection(pa_each) for _ in range(9)]
        self.assertAlmostEqual(
            expected_team_runs(lineup), LEAGUE_RUNS_PER_GAME_BASE, places=6
        )

    def test_better_lineup_scores_above_anchor(self) -> None:
        pa_each = LEAGUE_PA_PER_GAME / 9.0
        strong = [_proj_with_rates(0.27, 0.05, pa_each) for _ in range(9)]
        self.assertGreater(expected_team_runs(strong), LEAGUE_RUNS_PER_GAME_BASE)

    def test_empty_lineup_is_zero(self) -> None:
        self.assertEqual(expected_team_runs([]), 0.0)

    def test_weaker_bullpen_blend_lowers_runs(self) -> None:
        # Blending later PAs against a weaker-hitting matchup (lower rates) must pull
        # the run estimate below the starter-only estimate.
        pa_each = LEAGUE_PA_PER_GAME / 9.0
        starters = [_proj_with_rates(0.27, 0.05, pa_each) for _ in range(9)]
        weak_pen = [_proj_with_rates(0.20, 0.02, pa_each) for _ in range(9)]
        starter_only = expected_team_runs(starters)
        blended = expected_team_runs(starters, weak_pen)
        self.assertLess(blended, starter_only)


if __name__ == "__main__":
    unittest.main()
