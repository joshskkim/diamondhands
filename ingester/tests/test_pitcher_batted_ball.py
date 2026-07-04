"""Unit tests for pitcher contact-quality-allowed aggregation (Lever 1)."""
from __future__ import annotations

import unittest

import pandas as pd

from ingester.statcast import agg_pitcher_batted_ball


def _row(pitcher, stand, bb_type="fly_ball", ev=95.0, lsa=6):
    return {
        "pitcher": pitcher, "stand": stand, "bb_type": bb_type,
        "launch_speed": ev, "launch_speed_angle": lsa,
    }


class TestPitcherBattedBallAgg(unittest.TestCase):
    def _by_key(self, rows):
        return {(r["player_id"], r["vs_handedness"]): r for r in rows}

    def test_split_by_batter_hand(self) -> None:
        df = pd.DataFrame([
            _row(1, "L"), _row(1, "L"),   # two vs LHB
            _row(1, "R"),                 # one vs RHB
        ])
        out = self._by_key(agg_pitcher_batted_ball([df]))
        self.assertEqual(out[(1, "L")]["bip"], 2)
        self.assertEqual(out[(1, "R")]["bip"], 1)

    def test_quality_rates_and_filters(self) -> None:
        df = pd.DataFrame([
            _row(7, "R", bb_type="ground_ball", ev=100.0, lsa=6),   # hard, barrel, not FB
            _row(7, "R", bb_type="fly_ball", ev=80.0, lsa=3),       # soft FB, no barrel
            # dropped: no launch_speed (not a measured ball in play)
            {"pitcher": 7, "stand": "R", "bb_type": "fly_ball",
             "launch_speed": None, "launch_speed_angle": 6},
        ])
        r = self._by_key(agg_pitcher_batted_ball([df]))[(7, "R")]
        self.assertEqual(r["bip"], 2)                          # no-EV row dropped
        self.assertAlmostEqual(r["fb_pct"], 0.5, places=3)     # one of two
        self.assertAlmostEqual(r["hard_hit_pct"], 0.5, places=3)  # only the 100 EV
        self.assertAlmostEqual(r["barrel_pct"], 0.5, places=3)    # one lsa==6

    def test_switch_hitter_rows_split_by_stand(self) -> None:
        # `stand` already reflects the side the batter hit from — no correction.
        df = pd.DataFrame([_row(3, "L"), _row(3, "R")])
        out = self._by_key(agg_pitcher_batted_ball([df]))
        self.assertIn((3, "L"), out)
        self.assertIn((3, "R"), out)

    def test_empty_chunks(self) -> None:
        self.assertEqual(agg_pitcher_batted_ball([]), [])
        self.assertEqual(agg_pitcher_batted_ball([pd.DataFrame()]), [])


if __name__ == "__main__":
    unittest.main()
