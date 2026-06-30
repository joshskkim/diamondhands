"""Unit tests for the Lever 3 (redesigned) chase shift on the matchup K driver."""
from __future__ import annotations

import unittest
from unittest import mock

from ingester.projection import matchup as M
from ingester.projection.constants import CHASE_K_PER_Z, CHASE_MEAN, CHASE_SD
from ingester.projection.matchup import BatterPitchStat, batter_chase_k_delta


def _stat(chase, oz, k=0.22):
    return BatterPitchStat(xwoba=0.32, k_rate=k, iso=0.15, pitches_seen=100,
                           chase_rate=chase, oz_pitches=oz)


class TestBatterChaseKDelta(unittest.TestCase):
    def test_off_by_default(self) -> None:
        # Default flag off → no shift even with chase data.
        self.assertEqual(batter_chase_k_delta({"FF": _stat(0.40, 50)}), 0.0)

    def test_oz_weighted_overall_and_sign(self) -> None:
        with mock.patch.object(M, "CHASE_K_ENABLED", True):
            # Two pitch types: chase .40 over 30 oz, .20 over 10 oz → overall .35.
            d = batter_chase_k_delta({"FF": _stat(0.40, 30), "SL": _stat(0.20, 10)})
        overall = (0.40 * 30 + 0.20 * 10) / 40
        self.assertAlmostEqual(d, CHASE_K_PER_Z * (overall - CHASE_MEAN) / CHASE_SD, places=8)
        # Above-mean chase with a negative coef → negative delta (trims K).
        self.assertLess(d, 0.0)

    def test_noop_without_oz_data(self) -> None:
        with mock.patch.object(M, "CHASE_K_ENABLED", True):
            self.assertEqual(batter_chase_k_delta({"FF": _stat(None, 0)}), 0.0)
            self.assertEqual(batter_chase_k_delta({}), 0.0)


if __name__ == "__main__":
    unittest.main()
