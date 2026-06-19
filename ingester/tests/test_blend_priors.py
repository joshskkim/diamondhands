"""Unit tests for the projection-ensemble blend math (no DB)."""
from __future__ import annotations

import unittest

from ingester.commands.blend_priors import _weighted, blend_player


class TestWeighted(unittest.TestCase):
    def test_weighted_mean_over_present_methods(self):
        vals = {"a": 0.30, "b": 0.20}
        w = {"a": 0.75, "b": 0.25}
        self.assertAlmostEqual(_weighted(vals, w), 0.75 * 0.30 + 0.25 * 0.20)

    def test_renormalizes_when_a_method_is_missing(self):
        # 'b' has a weight but no value → weights renormalize over {a, c}.
        vals = {"a": 0.40, "c": 0.20}
        w = {"a": 0.50, "b": 0.30, "c": 0.20}
        expected = (0.50 * 0.40 + 0.20 * 0.20) / (0.50 + 0.20)
        self.assertAlmostEqual(_weighted(vals, w), expected)

    def test_none_when_no_overlap(self):
        self.assertIsNone(_weighted({"x": 0.3}, {"a": 1.0}))


class TestBlendPlayer(unittest.TestCase):
    WEIGHTS = {
        "xwoba":  {"marcel": 0.5, "steamer": 0.5},
        "k_rate": {"marcel": 0.5, "steamer": 0.5},
        "iso":    {"marcel": 0.5, "steamer": 0.5},
    }

    def test_full_coverage_averages_each_metric(self):
        by_method = {
            "marcel":  {"xwoba": 0.340, "k_rate": 0.220, "iso": 0.180, "pa": 600},
            "steamer": {"xwoba": 0.320, "k_rate": 0.240, "iso": 0.200, "pa": 550},
        }
        out = blend_player(by_method, self.WEIGHTS)
        self.assertAlmostEqual(out["xwoba"], 0.330)
        self.assertAlmostEqual(out["k_rate"], 0.230)
        self.assertAlmostEqual(out["iso"], 0.190)
        self.assertEqual(out["pa"], 550)  # steamer has PA priority over marcel

    def test_marcel_only_player_falls_back_to_marcel(self):
        by_method = {"marcel": {"xwoba": 0.330, "k_rate": 0.250, "iso": 0.150, "pa": 700}}
        out = blend_player(by_method, self.WEIGHTS)
        self.assertAlmostEqual(out["xwoba"], 0.330)
        self.assertAlmostEqual(out["iso"], 0.150)
        self.assertEqual(out["pa"], 700)

    def test_system_only_player_blends_without_marcel(self):
        # Rookie with a Steamer line but no Marcel history still gets a blend.
        by_method = {"steamer": {"xwoba": 0.310, "k_rate": 0.260, "iso": 0.170, "pa": 500}}
        out = blend_player(by_method, self.WEIGHTS)
        self.assertAlmostEqual(out["xwoba"], 0.310)
        self.assertEqual(out["pa"], 500)

    def test_returns_none_when_no_metrics_present(self):
        by_method = {"marcel": {"xwoba": None, "k_rate": None, "iso": None, "pa": None}}
        self.assertIsNone(blend_player(by_method, self.WEIGHTS))


if __name__ == "__main__":
    unittest.main()
