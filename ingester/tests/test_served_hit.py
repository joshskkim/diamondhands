"""Unit tests for the engine's served-hit blend step (_served_hit_prob)."""
from __future__ import annotations

import unittest

from ingester.projection.prop_blend import blend_market
from ingester.projection.runner import _served_hit_prob


class TestServedHitProb(unittest.TestCase):
    def test_blends_toward_clear_rate(self) -> None:
        # Matches prop_blend: a 60-game .42 hitter, model 0.70 → 0.5703.
        self.assertAlmostEqual(_served_hit_prob(0.70, (0.42, 60)), 0.5703, places=4)
        # Same value the shared util produces (rounded to 4dp as stored).
        self.assertAlmostEqual(
            _served_hit_prob(0.70, (0.42, 60)),
            round(blend_market("hit", 0.5, 0.70, 0.42, 60), 4),
        )

    def test_no_clear_rate_regresses_to_league(self) -> None:
        # None rate_n → (None, 0): regress toward the 0.62 league rate, still in (0,1).
        served = _served_hit_prob(0.70, None)
        self.assertIsNotNone(served)
        self.assertLess(served, 0.70)      # pulled down toward league
        self.assertGreater(served, 0.62)   # but not all the way

    def test_degenerate_sentinel_returns_none(self) -> None:
        # 0-PA / padded slot: raw 0 or 1 must NOT be blended (would launder toward league).
        self.assertIsNone(_served_hit_prob(0.0, (0.42, 60)))
        self.assertIsNone(_served_hit_prob(1.0, (0.42, 60)))
        self.assertIsNone(_served_hit_prob(None, (0.42, 60)))


if __name__ == "__main__":
    unittest.main()
