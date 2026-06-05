"""Unit tests for the pitcher-line projection (aggregate of the opposing lineup)."""
from __future__ import annotations

import unittest

from ingester.projection.batter_model import (
    AdjustedRates,
    BatterProbabilities,
    BatterProjection,
    pitcher_line_from_lineup,
)
from ingester.projection.constants import LEAGUE_BB_PER_PA, STARTER_PA_SHARE


def _proj(pa: float, k: float, hit: float, hr: float, iso: float = 0.15) -> BatterProjection:
    return BatterProjection(
        expected_pa=pa,
        adjusted=AdjustedRates(hit_per_pa=hit, hr_per_pa=hr, k_per_pa=k),
        probabilities=BatterProbabilities(0.0, 0.0, 0.0, 0.0),
        expected_hits=pa * hit,
        expected_total_bases=0.0,
        xwoba_blend=0.32,
        iso_blend=iso,
        adj_park_hit=1.0,
        adj_pitcher_hit=1.0,
        adj_weather_hit=1.0,
        adj_weather_hr=1.0,
    )


class TestPitcherLine(unittest.TestCase):
    def test_aggregates_lineup_over_starter_share(self) -> None:
        lineup = [_proj(4.0, 0.25, 0.25, 0.03) for _ in range(9)]
        line = pitcher_line_from_lineup(lineup, starter_share=0.60)

        faced_total = 9 * 0.60 * 4.0  # 21.6 BF
        self.assertAlmostEqual(line.expected_bf, faced_total, places=4)
        self.assertAlmostEqual(line.expected_k, faced_total * 0.25, places=4)
        self.assertAlmostEqual(line.expected_h, faced_total * 0.25, places=4)
        self.assertAlmostEqual(line.expected_hr, faced_total * 0.03, places=4)
        self.assertAlmostEqual(line.expected_bb, faced_total * LEAGUE_BB_PER_PA, places=4)
        # outs = BF - hits - walks; IP = outs / 3
        outs = faced_total - line.expected_h - line.expected_bb
        self.assertAlmostEqual(line.expected_outs, outs, places=4)
        self.assertAlmostEqual(line.expected_ip, outs / 3.0, places=4)
        self.assertGreater(line.expected_runs, 0.0)

    def test_share_scales_workload(self) -> None:
        lineup = [_proj(4.2, 0.22, 0.24, 0.035) for _ in range(9)]
        small = pitcher_line_from_lineup(lineup, starter_share=0.40)
        big = pitcher_line_from_lineup(lineup, starter_share=0.70)
        self.assertLess(small.expected_bf, big.expected_bf)
        self.assertLess(small.expected_k, big.expected_k)
        self.assertAlmostEqual(small.expected_bf, 9 * 0.40 * 4.2, places=4)

    def test_default_share_is_constant(self) -> None:
        lineup = [_proj(4.0, 0.25, 0.25, 0.03) for _ in range(9)]
        self.assertAlmostEqual(
            pitcher_line_from_lineup(lineup).expected_bf,
            9 * STARTER_PA_SHARE * 4.0,
            places=4,
        )


if __name__ == "__main__":
    unittest.main()
