"""Hand-computed unit tests for the bat-tracking aggregation."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ingester.statcast import agg_batter_bat_tracking


def chunk(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestAggBatterBatTracking(unittest.TestCase):
    def test_hand_computed_aggregate(self):
        df = chunk([
            # batter 1: three measured swings — 78, 72, 76 mph (2 fast of 3)
            {"batter": 1, "bat_speed": 78.0, "swing_length": 7.5, "attack_angle": 10.0},
            {"batter": 1, "bat_speed": 72.0, "swing_length": 7.1, "attack_angle": 8.0},
            {"batter": 1, "bat_speed": 76.0, "swing_length": np.nan, "attack_angle": 12.0},
            # batter 1: a take (no bat speed) — must not count
            {"batter": 1, "bat_speed": np.nan, "swing_length": np.nan, "attack_angle": np.nan},
            # batter 2: one slow swing
            {"batter": 2, "bat_speed": 65.0, "swing_length": 6.0, "attack_angle": 2.0},
        ])
        rows = {r["player_id"]: r for r in agg_batter_bat_tracking([df])}

        b1 = rows[1]
        self.assertEqual(b1["swings"], 3)
        self.assertAlmostEqual(b1["avg_bat_speed"], round((78 + 72 + 76) / 3, 2))
        self.assertAlmostEqual(b1["fast_swing_rate"], round(2 / 3, 4))
        self.assertAlmostEqual(b1["avg_swing_length"], round((7.5 + 7.1) / 2, 2))
        self.assertAlmostEqual(b1["avg_attack_angle"], round((10 + 8 + 12) / 3, 2))

        b2 = rows[2]
        self.assertEqual(b2["swings"], 1)
        self.assertAlmostEqual(b2["fast_swing_rate"], 0.0)

    def test_chunks_without_bat_tracking_are_skipped(self):
        # 2023-style chunk: no bat_speed column at all.
        df = chunk([{"batter": 1, "launch_speed": 95.0}])
        self.assertEqual(agg_batter_bat_tracking([df]), [])

    def test_accumulates_across_chunks(self):
        a = chunk([{"batter": 7, "bat_speed": 80.0, "swing_length": 8.0, "attack_angle": 15.0}])
        b = chunk([{"batter": 7, "bat_speed": 70.0, "swing_length": 6.0, "attack_angle": 5.0}])
        rows = {r["player_id"]: r for r in agg_batter_bat_tracking([a, b])}
        self.assertEqual(rows[7]["swings"], 2)
        self.assertAlmostEqual(rows[7]["avg_bat_speed"], 75.0)
        self.assertAlmostEqual(rows[7]["fast_swing_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
