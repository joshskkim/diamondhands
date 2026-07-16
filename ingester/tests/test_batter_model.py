"""Hand-computed unit test for the batter projection model."""
from __future__ import annotations

import math
import unittest
from unittest import mock

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
    LEAGUE_BB_PER_PA,
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
    PITCHER = PitcherAdjustments(hit=1.1, hr=0.9, k=1.2, bb=1.0)
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

    def test_defense_mult_scales_hits_not_hr_or_k(self) -> None:
        """A <1 opposing-defense factor lowers the hit rate / P(hit) but leaves the HR and
        K rates (and probabilities) untouched — defense can't field a HR or a strikeout."""
        base = project_batter(self.SKILL, self.PITCHER, self.PARK,
                              self.ADJ_WEATHER_HIT, self.ADJ_WEATHER_HR)
        suppressed = project_batter(self.SKILL, self.PITCHER, self.PARK,
                                    self.ADJ_WEATHER_HIT, self.ADJ_WEATHER_HR,
                                    defense_hit_mult=0.90)

        self.assertLess(suppressed.adjusted.hit_per_pa, base.adjusted.hit_per_pa)
        self.assertLess(suppressed.probabilities.p_hit_1plus, base.probabilities.p_hit_1plus)
        # HR and K untouched
        self.assertAlmostEqual(suppressed.adjusted.hr_per_pa, base.adjusted.hr_per_pa, places=9)
        self.assertAlmostEqual(suppressed.adjusted.k_per_pa, base.adjusted.k_per_pa, places=9)
        self.assertEqual(suppressed.probabilities.p_hr, base.probabilities.p_hr)
        self.assertEqual(suppressed.probabilities.p_k_1plus, base.probabilities.p_k_1plus)
        # Only the non-HR portion of the hit rate is scaled: new = hr + (hit-hr)*mult
        non_hr = base.adjusted.hit_per_pa - base.adjusted.hr_per_pa
        self.assertAlmostEqual(
            suppressed.adjusted.hit_per_pa,
            base.adjusted.hr_per_pa + non_hr * 0.90, places=9)

    def test_defense_mult_default_is_noop(self) -> None:
        base = project_batter(self.SKILL, self.PITCHER, self.PARK,
                              self.ADJ_WEATHER_HIT, self.ADJ_WEATHER_HR)
        same = project_batter(self.SKILL, self.PITCHER, self.PARK,
                             self.ADJ_WEATHER_HIT, self.ADJ_WEATHER_HR, defense_hit_mult=1.0)
        self.assertEqual(same.probabilities.p_hit_1plus, base.probabilities.p_hit_1plus)


class TestAdjustedRateClamps(unittest.TestCase):
    def test_extreme_hr_clamped(self) -> None:
        base = base_rates_from_blend(
            SkillBlends(xwoba=0.45, k_rate=0.20, iso=0.35, weight_l30=0.0)
        )
        pitcher = PitcherAdjustments(hit=1.3, hr=1.5, k=1.4, bb=1.2)
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


class TestWalksProjection(unittest.TestCase):
    """v2.11 walk prop: batter discipline × pitcher control, no park/weather."""

    PARK = ParkAdjustments(hit=1.0, hr=1.0)
    NEUTRAL = PitcherAdjustments(hit=1.0, hr=1.0, k=1.0, bb=1.0)

    @staticmethod
    def _skill(bb_rate: float) -> BatterSkillInput:
        return BatterSkillInput(
            xwoba=0.320, xwoba_l30=0.320, k_rate=0.22, k_rate_l30=0.22,
            iso=0.15, iso_l30=0.15, pa_l30=0, bb_rate=bb_rate,
        )

    @staticmethod
    def _base(bb_rate: float):
        return base_rates_from_blend(
            SkillBlends(xwoba=0.32, k_rate=0.22, iso=0.15, weight_l30=0.0, bb_rate=bb_rate)
        )

    def test_p_bb_increases_with_walk_rate(self) -> None:
        low = project_batter(self._skill(0.05), self.NEUTRAL, self.PARK, 1.0, 1.0)
        high = project_batter(self._skill(0.16), self.NEUTRAL, self.PARK, 1.0, 1.0)
        self.assertGreater(high.adjusted.bb_per_pa, low.adjusted.bb_per_pa)
        self.assertGreater(high.probabilities.p_bb_1plus, low.probabilities.p_bb_1plus)

    def test_pitcher_bb_multiplier_scales_walk_rate(self) -> None:
        base = self._base(0.09)
        wild = adjusted_rates_from_factors(
            base, PitcherAdjustments(hit=1.0, hr=1.0, k=1.0, bb=1.4), self.PARK, 1.0, 1.0)
        control = adjusted_rates_from_factors(
            base, PitcherAdjustments(hit=1.0, hr=1.0, k=1.0, bb=0.7), self.PARK, 1.0, 1.0)
        self.assertGreater(wild.bb_per_pa, control.bb_per_pa)

    def test_walks_ignore_park_and_weather(self) -> None:
        base = self._base(0.09)
        a = adjusted_rates_from_factors(
            base, self.NEUTRAL, ParkAdjustments(hit=1.3, hr=1.3), 1.2, 1.2)
        b = adjusted_rates_from_factors(
            base, self.NEUTRAL, ParkAdjustments(hit=0.8, hr=0.8), 0.9, 0.9)
        self.assertAlmostEqual(a.bb_per_pa, b.bb_per_pa, places=9)

    def test_league_avg_projection_has_zero_walk_prob(self) -> None:
        proj = league_average_projection(4.0)
        self.assertEqual(proj.probabilities.p_bb_1plus, 0.0)
        self.assertAlmostEqual(proj.adjusted.bb_per_pa, LEAGUE_BB_PER_PA)

    def test_matchup_override_keeps_skill_walk_rate(self) -> None:
        # The pitch-mix matchup replaces xwOBA/K/ISO but never the walk rate.
        without = project_batter(self._skill(0.13), self.NEUTRAL, self.PARK, 1.0, 1.0)
        with_matchup = project_batter(
            self._skill(0.13), self.NEUTRAL, self.PARK, 1.0, 1.0,
            matchup_xwoba=0.40, matchup_k_rate=0.30, matchup_iso=0.25)
        self.assertAlmostEqual(
            without.adjusted.bb_per_pa, with_matchup.adjusted.bb_per_pa, places=9)


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


class TestXhrHandSplit(unittest.TestCase):
    """xHR HR-power weight lever (DIAMOND_XHR_W) — blends barrel↔hand-split xHR."""

    KW = dict(xwoba=0.32, k_rate=0.22, iso=LEAGUE_ISO, weight_l30=0.0)

    def _blends(self, **extra) -> SkillBlends:
        return SkillBlends(**self.KW, **extra)

    def test_w_zero_ignores_xhr_and_uses_barrel(self) -> None:
        """Default (XHR_W=0): xHR present but the barrel path is unchanged."""
        from ingester.projection.constants import HR_BARREL_BLEND_W, LEAGUE_BARREL_RATE
        blends = self._blends(barrel_rate=0.13, xhr_per_bb=0.09,
                              xhr_vs_l=0.09, xhr_vs_r=0.05)
        barrel_scale = (1 - HR_BARREL_BLEND_W) * 1.0 + HR_BARREL_BLEND_W * (0.13 / LEAGUE_BARREL_RATE)
        # Both hands identical (xHR ignored) and equal to the barrel-only result.
        for hand in ("L", "R", None):
            base = base_rates_from_blend(blends, hand)
            self.assertAlmostEqual(base.hr_per_pa, LEAGUE_HR_PER_PA * barrel_scale)

    def test_w_one_differs_by_opposing_hand(self) -> None:
        from ingester.projection.constants import HR_BARREL_BLEND_W
        from ingester.projection.constants import LEAGUE_XHR_PER_BB as LG
        blends = self._blends(barrel_rate=0.13, xhr_per_bb=0.07,
                              xhr_vs_l=0.10, xhr_vs_r=0.04)
        with mock.patch("ingester.projection.batter_model.XHR_W", 1.0):
            hr_l = base_rates_from_blend(blends, "L").hr_per_pa
            hr_r = base_rates_from_blend(blends, "R").hr_per_pa
        exp_l = LEAGUE_HR_PER_PA * ((1 - HR_BARREL_BLEND_W) + HR_BARREL_BLEND_W * (0.10 / LG))
        exp_r = LEAGUE_HR_PER_PA * ((1 - HR_BARREL_BLEND_W) + HR_BARREL_BLEND_W * (0.04 / LG))
        self.assertAlmostEqual(hr_l, exp_l)
        self.assertAlmostEqual(hr_r, exp_r)
        self.assertGreater(hr_l, hr_r)  # more power vs LHP → higher HR vs a lefty

    def test_partial_weight_blends_barrel_and_xhr(self) -> None:
        """0 < XHR_W < 1 sits strictly between the pure-barrel and pure-xHR power."""
        from ingester.projection.constants import HR_BARREL_BLEND_W, LEAGUE_BARREL_RATE
        from ingester.projection.constants import LEAGUE_XHR_PER_BB as LG
        blends = self._blends(barrel_rate=0.13, xhr_per_bb=0.05, xhr_vs_l=0.05, xhr_vs_r=0.05)
        barrel_scale = 0.13 / LEAGUE_BARREL_RATE
        xhr_scale = 0.05 / LG
        power = 0.75 * barrel_scale + 0.25 * xhr_scale
        exp = LEAGUE_HR_PER_PA * ((1 - HR_BARREL_BLEND_W) + HR_BARREL_BLEND_W * power)
        with mock.patch("ingester.projection.batter_model.XHR_W", 0.25):
            hr = base_rates_from_blend(blends, "L").hr_per_pa
        self.assertAlmostEqual(hr, exp)

    def test_on_falls_back_to_barrel_when_no_xhr(self) -> None:
        from ingester.projection.constants import HR_BARREL_BLEND_W, LEAGUE_BARREL_RATE
        blends = self._blends(barrel_rate=0.13)  # xHR all None
        with mock.patch("ingester.projection.batter_model.XHR_W", 1.0):
            hr = base_rates_from_blend(blends, "L").hr_per_pa
        barrel_scale = (1 - HR_BARREL_BLEND_W) * 1.0 + HR_BARREL_BLEND_W * (0.13 / LEAGUE_BARREL_RATE)
        self.assertAlmostEqual(hr, LEAGUE_HR_PER_PA * barrel_scale)

    def test_on_hand_split_absent_uses_overall_xhr(self) -> None:
        """Facing an LHP with no vs-L split → the overall xHR is used, not barrel."""
        from ingester.projection.constants import HR_BARREL_BLEND_W
        from ingester.projection.constants import LEAGUE_XHR_PER_BB as LG
        blends = self._blends(barrel_rate=0.13, xhr_per_bb=0.06, xhr_vs_r=0.04)  # vs_l None
        with mock.patch("ingester.projection.batter_model.XHR_W", 1.0):
            hr = base_rates_from_blend(blends, "L").hr_per_pa
        exp = LEAGUE_HR_PER_PA * ((1 - HR_BARREL_BLEND_W) + HR_BARREL_BLEND_W * (0.06 / LG))
        self.assertAlmostEqual(hr, exp)

    def test_project_batter_threads_opposing_hand(self) -> None:
        """The opp_pitcher_throws arg reaches the HR scale end to end."""
        skill = BatterSkillInput(
            xwoba=0.32, xwoba_l30=0.32, k_rate=0.22, k_rate_l30=0.22,
            iso=LEAGUE_ISO, iso_l30=LEAGUE_ISO, pa_l30=0,
            barrel_rate=0.10, xhr_per_bb=0.07, xhr_vs_l=0.11, xhr_vs_r=0.03,
        )
        neutral_pitch = PitcherAdjustments(hit=1.0, hr=1.0, k=1.0, bb=1.0)
        neutral_park = ParkAdjustments(hit=1.0, hr=1.0)
        with mock.patch("ingester.projection.batter_model.XHR_W", 1.0):
            vs_l = project_batter(skill, neutral_pitch, neutral_park, 1.0, 1.0,
                                  opp_pitcher_throws="L")
            vs_r = project_batter(skill, neutral_pitch, neutral_park, 1.0, 1.0,
                                  opp_pitcher_throws="R")
        self.assertGreater(vs_l.probabilities.p_hr, vs_r.probabilities.p_hr)


if __name__ == "__main__":
    unittest.main()
