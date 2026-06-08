"""Unit tests for the first-inning run model (NRFI / YRFI)."""
from __future__ import annotations

import unittest

from ingester.projection.batter_model import yrfi_probability


class TestYrfi(unittest.TestCase):
    def test_league_average_is_about_half(self) -> None:
        p, efir = yrfi_probability(4.3, 4.3)
        self.assertAlmostEqual(p, 0.50, delta=0.03)   # calibrated to ~0.50 YRFI
        self.assertGreater(efir, 0.0)

    def test_high_offense_more_likely_to_score(self) -> None:
        low, _ = yrfi_probability(3.0, 3.0)
        high, _ = yrfi_probability(6.0, 6.0)
        self.assertGreater(high, low)
        self.assertGreater(high, 0.5)
        self.assertLess(low, 0.5)

    def test_probability_bounded(self) -> None:
        for h, a in [(0.0, 0.0), (12.0, 12.0), (8.0, 1.0)]:
            p, _ = yrfi_probability(h, a)
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_zero_offense_is_zero_yrfi(self) -> None:
        p, efir = yrfi_probability(0.0, 0.0)
        self.assertAlmostEqual(p, 0.0, places=6)
        self.assertAlmostEqual(efir, 0.0, places=6)

    def test_efir_scales_with_runs(self) -> None:
        _, low = yrfi_probability(3.0, 3.0)
        _, high = yrfi_probability(6.0, 6.0)
        self.assertGreater(high, low)


if __name__ == "__main__":
    unittest.main()
