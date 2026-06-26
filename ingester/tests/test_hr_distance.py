"""Unit tests for per-batter HR-distance aggregation and the projected-carry shrink."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ingester.projection.constants import LEAGUE_HR_DISTANCE_P90_FT
from ingester.projection.runner import _shrunk_hr_distance
from ingester.statcast import agg_batter_hr_distance


def _df(rows):
    return pd.DataFrame(rows, columns=["batter", "events", "hit_distance_sc"])


class TestHrDistanceAgg(unittest.TestCase):
    def _by_id(self, rows):
        return {r["player_id"]: r for r in rows}

    def test_hr_only_avg_and_p90(self) -> None:
        df = _df([
            [1, "home_run", 400.0],
            [1, "home_run", 450.0],
            [1, "single", 320.0],   # not a HR → excluded
            [1, "home_run", None],  # HR but no measured distance → excluded
            [2, "home_run", 410.0],
        ])
        out = self._by_id(agg_batter_hr_distance([df]))

        self.assertEqual(out[1]["hr_n"], 2)
        self.assertAlmostEqual(out[1]["avg_distance_ft"], 425.0, places=1)
        self.assertAlmostEqual(
            out[1]["p90_distance_ft"],
            round(float(np.percentile([400.0, 450.0], 90)), 1),
            places=1,
        )
        self.assertEqual(out[2]["hr_n"], 1)
        self.assertAlmostEqual(out[2]["p90_distance_ft"], 410.0, places=1)

    def test_no_hrs_and_empty(self) -> None:
        self.assertEqual(agg_batter_hr_distance([]), [])
        self.assertEqual(agg_batter_hr_distance([pd.DataFrame()]), [])
        # A batter with no home runs produces no row at all.
        self.assertEqual(
            agg_batter_hr_distance([_df([[1, "single", 300.0], [1, "double", 330.0]])]), []
        )


class TestShrink(unittest.TestCase):
    def test_zero_sample_is_all_league(self) -> None:
        self.assertAlmostEqual(_shrunk_hr_distance(999.0, 0), LEAGUE_HR_DISTANCE_P90_FT, places=6)

    def test_big_sample_keeps_own(self) -> None:
        self.assertLess(abs(_shrunk_hr_distance(455.0, 1000) - 455.0), 1.0)

    def test_more_hrs_pull_closer_to_own(self) -> None:
        # Own p90 (460) sits above the league (425): more sample → less regression → higher.
        self.assertGreater(_shrunk_hr_distance(460.0, 40), _shrunk_hr_distance(460.0, 5))


if __name__ == "__main__":
    unittest.main()
