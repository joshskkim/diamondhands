"""Unit test for Lever 3 chase aggregation from pitch-level zone data."""
from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from ingester.statcast_pitch import aggregate_batter_pitch_stats

AS_OF = date(2025, 7, 1)


def _pitch(zone, description, events=None):
    return {
        "batter": 1, "pitch_type": "FF", "stand": "R", "p_throws": "R",
        "game_date": "2025-05-01", "description": description, "zone": zone,
        "events": events,
    }


class TestChaseAggregation(unittest.TestCase):
    def test_chase_rate_from_zone(self) -> None:
        # 10 out-of-zone (zone 13) — 6 swung (foul), 4 taken (ball);
        # 30 in-zone (zone 5) taken. → chase = 6/10, oz_pitches = 10.
        rows = (
            [_pitch(13, "foul") for _ in range(6)]
            + [_pitch(13, "ball") for _ in range(4)]
            + [_pitch(5, "called_strike") for _ in range(30)]
        )
        out = aggregate_batter_pitch_stats(pd.DataFrame(rows), AS_OF, 2025)
        ff = next(r for r in out if r["vs_handedness"] == "A" and r["pitch_type"] == "FF")
        self.assertEqual(ff["oz_pitches"], 10)
        self.assertAlmostEqual(ff["chase_rate"], 0.6, places=4)

    def test_no_out_of_zone_gives_none_chase(self) -> None:
        rows = [_pitch(5, "called_strike") for _ in range(40)]
        out = aggregate_batter_pitch_stats(pd.DataFrame(rows), AS_OF, 2025)
        ff = next(r for r in out if r["vs_handedness"] == "A" and r["pitch_type"] == "FF")
        self.assertEqual(ff["oz_pitches"], 0)
        self.assertIsNone(ff["chase_rate"])  # _safe_div(.,0) → None


if __name__ == "__main__":
    unittest.main()
