"""Unit tests for minor-league equivalencies (pure translation; no DB/network)."""
from __future__ import annotations

import unittest

from ingester.projection.constants import MLE_LEVEL_FACTORS, MLE_PA_DISCOUNT
from ingester.projection.mle import (
    LEVEL_BY_SPORT_ID,
    MinorLeagueLine,
    is_supported_level,
    to_equivalent_season,
    translate_rates,
)


class TestTranslateRates(unittest.TestCase):
    def test_level_up_suppresses_offense_raises_k(self):
        hit, iso, k = translate_rates("AAA", 0.300, 0.200, 0.200)
        self.assertLess(hit, 0.300)   # hit rate falls vs MLB pitching
        self.assertLess(iso, 0.200)   # power falls
        self.assertGreater(k, 0.200)  # K rises

    def test_lower_levels_translate_harder(self):
        # Same minor-league rates discount more at A than AAA.
        aaa = translate_rates("AAA", 0.300, 0.200, 0.200)
        low_a = translate_rates("A", 0.300, 0.200, 0.200)
        self.assertGreater(aaa[0], low_a[0])   # AAA retains more hit rate
        self.assertGreater(aaa[1], low_a[1])   # and more power
        self.assertLess(aaa[2], low_a[2])      # and adds less K

    def test_k_is_capped(self):
        _, _, k = translate_rates("R", 0.300, 0.200, 0.40)  # 0.40 * 1.40 = 0.56 → capped
        self.assertLessEqual(k, 0.45)

    def test_matches_constants(self):
        f = MLE_LEVEL_FACTORS["AA"]
        hit, iso, k = translate_rates("AA", 0.250, 0.150, 0.220)
        self.assertAlmostEqual(hit, 0.250 * f["hit"])
        self.assertAlmostEqual(iso, 0.150 * f["iso"])
        self.assertAlmostEqual(k, 0.220 * f["k"])


class TestToEquivalentSeason(unittest.TestCase):
    def _line(self, level="AAA") -> MinorLeagueLine:
        # 500 PA, 450 AB, .300/.200 ISO line: 135 H, 25 HR, TB = 135 + .200*450 = 225
        return MinorLeagueLine(level=level, pa=500, ab=450, hits=135, hr=25, tb=225, k=100)

    def test_pa_is_discounted(self):
        se = to_equivalent_season(self._line())
        assert se is not None
        self.assertEqual(se.pa, round(500 * MLE_PA_DISCOUNT))

    def test_xwoba_none(self):
        # Minors have no Statcast xwOBA → component falls back to league in the prior.
        self.assertIsNone(to_equivalent_season(self._line()).xwoba)

    def test_translated_offense_lower_than_raw(self):
        se = to_equivalent_season(self._line())
        assert se is not None
        raw_hit_rate = 135 / 500
        mle_hit_rate = se.hits / se.pa
        self.assertLess(mle_hit_rate, raw_hit_rate)   # MLB-equiv hit rate is suppressed
        raw_iso = (225 - 135) / 450
        mle_iso = (se.tb - se.hits) / se.ab
        self.assertLess(mle_iso, raw_iso)

    def test_hr_not_above_total_extra_bases(self):
        se = to_equivalent_season(self._line())
        assert se is not None
        self.assertLessEqual(se.hr, se.tb - se.hits)

    def test_unsupported_level_or_empty_returns_none(self):
        self.assertIsNone(to_equivalent_season(
            MinorLeagueLine("MLB", 500, 450, 135, 25, 225, 100)))
        self.assertIsNone(to_equivalent_season(
            MinorLeagueLine("AAA", 0, 0, 0, 0, 0, 0)))

    def test_sport_id_map_supported(self):
        # Every mapped sportId level is a translatable level.
        for level in LEVEL_BY_SPORT_ID.values():
            self.assertTrue(is_supported_level(level))


if __name__ == "__main__":
    unittest.main()
