"""Unit tests for batter batted-ball / spray aggregation."""
from __future__ import annotations

import unittest

import pandas as pd

from ingester.statcast import agg_batter_batted_ball


def _row(batter, stand, hc_x, hc_y, bb_type="fly_ball", ev=95.0, la=25.0, lsa=6):
    return {
        "batter": batter, "stand": stand, "hc_x": hc_x, "hc_y": hc_y,
        "bb_type": bb_type, "launch_speed": ev, "launch_angle": la,
        "launch_speed_angle": lsa,
    }


class TestBattedBallAgg(unittest.TestCase):
    def _by_id(self, rows):
        return {r["player_id"]: r for r in rows}

    def test_handedness_adjusted_spray(self) -> None:
        # RHB: LF=pull, CF=center, RF=oppo. LHB: RF=pull.
        # hc_x < 125.42 → left side; > 125.42 → right side; ~125.42 → center.
        df = pd.DataFrame([
            _row(1, "R", 70, 100),    # RHB to LF → pull
            _row(1, "R", 125.42, 95), # RHB to CF → center
            _row(1, "R", 180, 100),   # RHB to RF → oppo
            _row(2, "L", 180, 100),   # LHB to RF → pull
            _row(2, "L", 70, 100),    # LHB to LF → oppo
        ])
        out = self._by_id(agg_batter_batted_ball([df]))

        rhb = out[1]
        self.assertEqual(rhb["bip"], 3)
        self.assertAlmostEqual(rhb["pull_pct"], 1 / 3, places=3)
        self.assertAlmostEqual(rhb["center_pct"], 1 / 3, places=3)
        self.assertAlmostEqual(rhb["oppo_pct"], 1 / 3, places=3)

        lhb = out[2]
        self.assertEqual(lhb["bip"], 2)
        self.assertAlmostEqual(lhb["pull_pct"], 0.5, places=3)   # the RF ball
        self.assertAlmostEqual(lhb["oppo_pct"], 0.5, places=3)   # the LF ball

    def test_bb_type_quality_and_filters(self) -> None:
        df = pd.DataFrame([
            _row(7, "R", 70, 100, bb_type="ground_ball", ev=100.0, lsa=6),
            _row(7, "R", 70, 100, bb_type="fly_ball", ev=80.0, lsa=3),
            # dropped: no hit coordinates (not a fielded ball in play)
            {"batter": 7, "stand": "R", "hc_x": None, "hc_y": None,
             "bb_type": "fly_ball", "launch_speed": 99.0, "launch_angle": 20.0,
             "launch_speed_angle": 6},
        ])
        r = self._by_id(agg_batter_batted_ball([df]))[7]
        self.assertEqual(r["bip"], 2)                       # the no-coordinate row is dropped
        self.assertAlmostEqual(r["gb_pct"], 0.5, places=3)
        self.assertAlmostEqual(r["fb_pct"], 0.5, places=3)
        self.assertAlmostEqual(r["avg_launch_speed"], 90.0, places=2)  # (100+80)/2
        self.assertAlmostEqual(r["hard_hit_pct"], 0.5, places=3)       # only the 100 EV
        self.assertAlmostEqual(r["barrel_pct"], 0.5, places=3)         # one lsa==6

    def test_empty_chunks(self) -> None:
        self.assertEqual(agg_batter_batted_ball([]), [])
        self.assertEqual(agg_batter_batted_ball([pd.DataFrame()]), [])


if __name__ == "__main__":
    unittest.main()
