"""Unit tests for the per-market probability calibrator (S3)."""
from __future__ import annotations

import unittest

from ingester.projection.batter_model import (
    AdjustedRates,
    BatterProbabilities,
    BatterProjection,
)
from ingester.projection.calibration import Calibrator, fit_isotonic


def _proj(p_h1: float, p_h2: float, p_hr: float, p_k: float) -> BatterProjection:
    return BatterProjection(
        expected_pa=4.0,
        adjusted=AdjustedRates(hit_per_pa=0.25, hr_per_pa=0.03, k_per_pa=0.22),
        probabilities=BatterProbabilities(p_h1, p_h2, p_hr, p_k),
        expected_hits=1.0,
        expected_total_bases=1.5,
        xwoba_blend=0.32,
        iso_blend=0.15,
        adj_park_hit=1.0,
        adj_pitcher_hit=1.0,
        adj_weather_hit=1.0,
        adj_weather_hr=1.0,
    )


class TestCalibrator(unittest.TestCase):
    def test_hit_is_skipped_others_calibrated(self) -> None:
        # HIT (h1) is deliberately NOT calibrated — the clear-rate blend owns it now (see
        # Calibrator.apply). A doubling h1 map must leave p_hit_1plus untouched, while hr's
        # map still applies and h2/k (no map) pass through.
        doubling = [min(2 * (i / 100), 1.0) for i in range(101)]
        c = Calibrator({"hr": [0.0] * 101, "h1": doubling})
        out = c.apply(_proj(0.4, 0.2, 0.3, 0.6))
        self.assertAlmostEqual(out.probabilities.p_hit_1plus, 0.4)   # h1 skipped → unchanged
        self.assertAlmostEqual(out.probabilities.p_hr, 0.0)          # hr map applied
        self.assertAlmostEqual(out.probabilities.p_hit_2plus, 0.2)   # no map → unchanged
        self.assertAlmostEqual(out.probabilities.p_k_1plus, 0.6)     # no map → unchanged

    def test_interpolates_between_grid_points(self) -> None:
        # Map that doubles the input (clipped at 1): y[i] = min(2*x, 1).
        doubling = [min(2 * (i / 100), 1.0) for i in range(101)]
        c = Calibrator({"hr": doubling})
        out = c.apply(_proj(0.5, 0.2, 0.25, 0.6))
        self.assertAlmostEqual(out.probabilities.p_hr, 0.5, places=6)

    def test_fit_isotonic_is_monotonic_and_bounded(self) -> None:
        # Predictions uncorrelated-ish with a clear upward trend → monotonic non-decreasing.
        preds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8] * 20
        actual = [0, 0, 0, 1, 0, 1, 1, 1] * 20
        grid = fit_isotonic(preds, actual)
        self.assertEqual(len(grid), 101)
        self.assertTrue(all(0.0 <= v <= 1.0 for v in grid))
        self.assertTrue(all(grid[i] <= grid[i + 1] + 1e-9 for i in range(len(grid) - 1)))

    def test_none_when_file_missing(self) -> None:
        self.assertIsNone(Calibrator.load("/nonexistent/calibration.json"))
