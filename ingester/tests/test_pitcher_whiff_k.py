"""Unit tests for the Lever 2 pitcher-whiff → matchup K multiplier."""
from __future__ import annotations

import math
import unittest
from unittest import mock

from ingester.projection import matchup as M
from ingester.projection.matchup import ArsenalEntry, pitcher_whiff_k_factor

LEAGUE = {"FF": 0.20, "SL": 0.25}


def _arsenal(ff_whiff, sl_whiff, ff_use=0.5, sl_use=0.5):
    return [
        ArsenalEntry("FF", ff_use, 100, whiff_rate=ff_whiff),
        ArsenalEntry("SL", sl_use, 100, whiff_rate=sl_whiff),
    ]


class TestPitcherWhiffKFactor(unittest.TestCase):
    def test_off_by_default(self) -> None:
        with mock.patch.object(M, "PITCHER_WHIFF_K_BETA", 0.0):
            f = pitcher_whiff_k_factor(_arsenal(0.30, 0.40), LEAGUE)
        self.assertEqual(f, 1.0)

    def test_high_whiff_raises_k(self) -> None:
        with mock.patch.object(M, "PITCHER_WHIFF_K_BETA", 1.0):
            f = pitcher_whiff_k_factor(_arsenal(0.30, 0.40), LEAGUE)
        # num_p = .5*.30+.5*.40 = .35 ; num_l = .5*.20+.5*.25 = .225
        self.assertAlmostEqual(f, 0.35 / 0.225, places=6)
        self.assertGreater(f, 1.0)

    def test_low_whiff_trims_k(self) -> None:
        with mock.patch.object(M, "PITCHER_WHIFF_K_BETA", 1.0):
            f = pitcher_whiff_k_factor(_arsenal(0.12, 0.15), LEAGUE)
        self.assertLess(f, 1.0)

    def test_exponent_dampens(self) -> None:
        ars = _arsenal(0.30, 0.40)
        with mock.patch.object(M, "PITCHER_WHIFF_K_BETA", 0.5):
            f = pitcher_whiff_k_factor(ars, LEAGUE)
        self.assertAlmostEqual(f, math.sqrt(0.35 / 0.225), places=6)

    def test_missing_whiff_is_noop(self) -> None:
        with mock.patch.object(M, "PITCHER_WHIFF_K_BETA", 1.0):
            # No per-pitch whiff on the arsenal → nothing to weight → 1.0.
            f1 = pitcher_whiff_k_factor(_arsenal(None, None), LEAGUE)
            # No league whiff for the pitches thrown → 1.0.
            f2 = pitcher_whiff_k_factor(_arsenal(0.30, 0.40), {})
            f3 = pitcher_whiff_k_factor([], LEAGUE)
        self.assertEqual((f1, f2, f3), (1.0, 1.0, 1.0))


if __name__ == "__main__":
    unittest.main()
