"""Hand-built unit tests for the opener / bullpen-game detector.

outs_history is recorded outs per START, MOST-RECENT-FIRST. A real start is >= 15 outs
(5 IP). The detector must skip likely openers but never an established or recently-
converted starter.
"""
from __future__ import annotations

import unittest

from ingester.mlb_api import _parse_innings
from ingester.projection.opener import SeasonRole, is_likely_opener

SP = SeasonRole(games_started=30, games_pitched=31, innings_pitched=180.0)
RP = SeasonRole(games_started=2, games_pitched=55, innings_pitched=60.0)


class TestIsLikelyOpener(unittest.TestCase):
    def test_established_sp_not_flagged(self):
        flagged, reason = is_likely_opener([19, 18, 20, 17, 21], SP)
        self.assertFalse(flagged, reason)

    def test_established_opener_flagged(self):
        flagged, reason = is_likely_opener([4, 3, 5, 2, 4], RP)
        self.assertTrue(flagged, reason)

    def test_recent_conversion_not_flagged(self):
        # Reliever-shaped season, but the last two outings are real starts → SP now.
        flagged, reason = is_likely_opener([18, 17, 4, 3, 2], RP)
        self.assertFalse(flagged, reason)

    def test_fluke_short_start_not_flagged(self):
        # One 1-IP blowup amid deep starts; season says SP → signals disagree → keep.
        flagged, reason = is_likely_opener([3, 20, 19, 18, 21], SP)
        self.assertFalse(flagged, reason)

    def test_opener_with_few_short_starts_flagged(self):
        flagged, reason = is_likely_opener([2, 4, 3], SeasonRole(5, 50, 55.0))
        self.assertTrue(flagged, reason)

    def test_no_history_season_sp_not_flagged(self):
        flagged, reason = is_likely_opener([], SeasonRole(3, 3, 16.0))
        self.assertFalse(flagged, reason)

    def test_no_history_season_rp_flagged(self):
        flagged, reason = is_likely_opener([], SeasonRole(0, 40, 42.0))
        self.assertTrue(flagged, reason)

    def test_no_history_no_season_defaults_project(self):
        flagged, reason = is_likely_opener([], None)
        self.assertFalse(flagged, reason)

    def test_season_none_rich_history_uses_recency(self):
        # Fetch failed: short recent starts, no real start in window → flag from recency.
        flagged, reason = is_likely_opener([3, 4, 2, 5, 3], None)
        self.assertTrue(flagged, reason)
        # Deep starts but no season info → keep.
        keep, _ = is_likely_opener([18, 19, 17], None)
        self.assertFalse(keep)

    def test_reason_string_present(self):
        for hist, season in (([4, 3, 5, 2, 4], RP), ([19, 18, 20], SP)):
            _, reason = is_likely_opener(hist, season)
            self.assertTrue(reason)

    def test_recency_ordering_flips_flag(self):
        # Same outings, different order. A real start at the FRONT (most recent) should
        # be more starter-leaning than the same start buried at the back.
        front, _ = is_likely_opener([18, 4, 3], RP)   # recent real start
        back, _ = is_likely_opener([3, 4, 18], RP)    # stale real start
        self.assertFalse(front)
        self.assertTrue(back)


class TestParseInnings(unittest.TestCase):
    def test_outs_decimal(self):
        self.assertAlmostEqual(_parse_innings("42.1"), 42 + 1 / 3, places=4)
        self.assertAlmostEqual(_parse_innings("42.2"), 42 + 2 / 3, places=4)
        self.assertAlmostEqual(_parse_innings("42.0"), 42.0, places=4)
        self.assertEqual(_parse_innings(None), 0.0)
        self.assertEqual(_parse_innings("bad"), 0.0)


if __name__ == "__main__":
    unittest.main()
