"""Parity tests for the empirical-shrinkage blend.

These pin the Python port to the SAME hand-computed values the Java OddsServiceTest asserts,
so the backtest measures exactly the blend the site serves. If the API's PropBlend constants
change, both these and the Java test must move together.
"""
from __future__ import annotations

import unittest

from ingester.projection.prop_blend import blend, blend_market


class TestBlend(unittest.TestCase):
    def test_matches_java_hit_case(self):
        # OddsServiceTest.batterMarketBlendsTowardTheDemonstratedClearRate:
        # 60-game .42 hitter, model 0.70 → empirical = (60*.42 + 25*.62)/85 = .4788,
        # w = 85/145 = .5862 → .5862*.4788 + .4138*.70 = .5703.
        self.assertAlmostEqual(blend(0.70, 0.42, 60, 0.62), 0.5703, places=4)

    def test_no_history_regresses_toward_league(self):
        # n=0, no season rate → empirical = league, w = 25/85; tb league = 0.31, raw 0.30.
        # 0.2941*0.31 + 0.7059*0.30 = 0.30294 (OddsServiceTest simHistogramMarkets... case).
        self.assertAlmostEqual(blend(0.30, None, 0, 0.31), 0.30294, places=5)

    def test_evidence_grows_pulls_harder_toward_empirical(self):
        # More prior games at a low rate pulls a confident model prob further down.
        low_n = blend(0.70, 0.42, 10, 0.62)
        high_n = blend(0.70, 0.42, 200, 0.62)
        self.assertGreater(low_n, high_n)

    def test_output_stays_inside_unit_interval(self):
        for p in (0.01, 0.5, 0.99):
            self.assertGreater(blend(p, 0.5, 40, 0.6), 0.0)
            self.assertLess(blend(p, 0.5, 40, 0.6), 1.0)


class TestBlendMarket(unittest.TestCase):
    def test_blends_at_canonical_line(self):
        self.assertAlmostEqual(blend_market("hit", 0.5, 0.70, 0.42, 60), 0.5703, places=4)

    def test_off_canonical_line_passes_through(self):
        # hit clear rate is 1+ (line 0.5); a 2+ quote (1.5) is a different event → raw.
        self.assertEqual(blend_market("hit", 1.5, 0.30, 0.42, 60), 0.30)

    def test_pitcher_market_never_blends(self):
        # No pitcher clear rate exists — pass through even if rate args are supplied.
        self.assertEqual(blend_market("pitcher_k", 5.5, 0.44, 0.42, 60), 0.44)

    def test_null_in_null_out(self):
        self.assertIsNone(blend_market("hit", 0.5, None, 0.42, 60))


if __name__ == "__main__":
    unittest.main()
