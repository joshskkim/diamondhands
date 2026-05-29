"""Hand-computed unit test for the batter projection model."""
from __future__ import annotations

import math
import unittest

from scipy.stats import binom

from ingester.projection.batter_model import (
    BatterSkillInput,
    SkillBlends,
    base_rates_from_blend,
    blend_batter_skills,
    expected_team_runs,
    project_batter,
)
from ingester.projection.constants import (
    EXPECTED_PA_PER_STARTER,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_ISO,
    LEAGUE_RUNS_PER_GAME_BASE,
    LEAGUE_XWOBA,
    PA_L30_FULL_WEIGHT,
)
from ingester.projection.park_adj import ParkAdjustments
from ingester.projection.pitcher_adj import PitcherAdjustments


class TestBatterModelHandComputed(unittest.TestCase):
    """
    Synthetic batter with pa_l30=50 → 50/50 L30 vs season blend.

    Skill inputs
    ------------
    xwOBA 0.340 / 0.360 → blend 0.350
    K%    0.200 / 0.240 → blend 0.220
    ISO   0.170 / 0.190 → blend 0.180

    Base rates (vs league)
    ----------------------
    hit/PA = 0.225 × (0.350 / 0.318) ≈ 0.24764
    HR/PA  = 0.030 × (0.180 / 0.155) ≈ 0.03484
    K/PA   = 0.220

    Adjustments: pitcher hit×1.1, HR×0.9, K×1.2; park hit×1.05, HR×1.10;
    weather hit×1.02, HR×1.0.

    Adjusted per-PA
    ---------------
    hit ≈ 0.29175, HR ≈ 0.03449, K = 0.264

    expected_pa = 4.0
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
        w = 50 / PA_L30_FULL_WEIGHT
        cls.W_L30 = w
        cls.XWOBA_BLEND = 0.360 * w + 0.340 * (1 - w)
        cls.K_BLEND = 0.240 * w + 0.200 * (1 - w)
        cls.ISO_BLEND = 0.190 * w + 0.170 * (1 - w)

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

    def test_blend_weights(self) -> None:
        blends = blend_batter_skills(self.SKILL)
        self.assertAlmostEqual(blends.weight_l30, self.W_L30)
        self.assertAlmostEqual(blends.xwoba, self.XWOBA_BLEND)
        self.assertAlmostEqual(blends.k_rate, self.K_BLEND)
        self.assertAlmostEqual(blends.iso, self.ISO_BLEND)

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

        self.assertEqual(proj.probabilities.p_hit_1plus, self.EXP_P_HIT_1)
        self.assertEqual(proj.probabilities.p_hit_2plus, self.EXP_P_HIT_2)
        self.assertEqual(proj.probabilities.p_hr, self.EXP_P_HR)
        self.assertEqual(proj.probabilities.p_k_1plus, self.EXP_P_K)

        self.assertAlmostEqual(proj.expected_hits, self.EXP_HITS, places=4)
        self.assertAlmostEqual(proj.expected_total_bases, self.EXP_TB, places=4)

        self.assertEqual(proj.adj_park_hit, 1.05)
        self.assertEqual(proj.adj_pitcher_hit, 1.1)
        self.assertEqual(proj.adj_weather_hit, 1.02)
        self.assertEqual(proj.adj_weather_hr, 1.0)


class TestExpectedTeamRuns(unittest.TestCase):
    def test_hand_computed_team_runs(self) -> None:
        """Nine starters at 0.350 xwOBA, park 1.05, weather hit 1.02."""
        xwoba = 0.350
        park = 1.05
        weather = 1.02
        scale = (xwoba / LEAGUE_XWOBA) ** 1.8
        expected = LEAGUE_RUNS_PER_GAME_BASE * scale * park * weather

        result = expected_team_runs([xwoba] * 9, park, weather)
        self.assertAlmostEqual(result, expected, places=6)
        self.assertAlmostEqual(result, 5.7274, places=3)


if __name__ == "__main__":
    unittest.main()
