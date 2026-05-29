"""Hand-computed unit test for the batter projection model."""
from __future__ import annotations

import math
import unittest

from scipy.stats import binom

from ingester.projection.batter_model import (
    BatterSkillInput,
    SkillBlends,
    adjusted_rates_from_factors,
    base_rates_from_blend,
    blend_batter_skills,
    expected_team_runs,
    l30_blend_weight,
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
    PITCHER_MULT_HR_CLAMP,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    PA_L30_BLEND_CAP,
    PA_L30_FULL_WEIGHT,
    PITCHER_MULT_HIT_CLAMP,
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

        cls.ADJ_HIT = (
            cls.BASE_HIT * cls.PITCHER.hit * cls.PARK.hit * cls.ADJ_WEATHER_HIT
        )
        cls.ADJ_HR = (
            cls.BASE_HR * cls.PITCHER.hr * cls.PARK.hr * cls.ADJ_WEATHER_HR
        )
        cls.ADJ_K = cls.BASE_K * cls.PITCHER.k

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
        self.assertAlmostEqual(self.W_L30, 50 / PA_L30_FULL_WEIGHT)
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


class TestExpectedTeamRuns(unittest.TestCase):
    def test_hand_computed_team_runs(self) -> None:
        xwoba = 0.350
        park = 1.05
        weather = 1.02
        scale = (xwoba / LEAGUE_XWOBA) ** 1.8
        expected = LEAGUE_RUNS_PER_GAME_BASE * scale * park * weather

        result = expected_team_runs([xwoba] * 9, park, weather)
        self.assertAlmostEqual(result, expected, places=6)


if __name__ == "__main__":
    unittest.main()
