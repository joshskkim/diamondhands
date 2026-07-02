"""Unit tests for the Lever 1 barrel-allowed HR blend and prior loader."""
from __future__ import annotations

import unittest
from unittest import mock

from ingester.commands.refresh_skills import (
    PITCHER_BARREL_REGRESSION_BIP,
    _load_pitcher_barrel_allowed,
)
from ingester.projection import pitcher_adj
from ingester.projection.constants import (
    LEAGUE_BARREL_RATE,
    LEAGUE_HR_PER_PA,
    PITCHER_MULT_HR_CLAMP,
)
from ingester.projection.pitcher_adj import (
    PitcherHandSplit,
    compute_pitcher_adjustments,
    rate_multiplier,
)


def _split(hr_per_pa=LEAGUE_HR_PER_PA, barrel_allowed=None):
    return PitcherHandSplit(
        vs_handedness="R",
        batters_faced=200,
        hits_per_pa=0.220,
        hr_per_pa=hr_per_pa,
        k_rate=0.230,
        barrel_allowed=barrel_allowed,
    )


class TestBarrelAllowedBlend(unittest.TestCase):
    def test_weight_zero_reproduces_realized(self) -> None:
        """Ship default (W=0): barrel-allowed present but ignored → realized basis."""
        split = _split(hr_per_pa=0.04, barrel_allowed=0.13)
        with mock.patch.object(pitcher_adj, "PITCHER_HR_BARREL_BLEND_W", 0.0):
            adj = compute_pitcher_adjustments(split)
        expected = rate_multiplier(0.04, LEAGUE_HR_PER_PA, PITCHER_MULT_HR_CLAMP)
        self.assertAlmostEqual(adj.hr, expected, places=6)

    def test_none_barrel_falls_back_even_with_weight(self) -> None:
        split = _split(hr_per_pa=0.04, barrel_allowed=None)
        with mock.patch.object(pitcher_adj, "PITCHER_HR_BARREL_BLEND_W", 0.6):
            adj = compute_pitcher_adjustments(split)
        expected = rate_multiplier(0.04, LEAGUE_HR_PER_PA, PITCHER_MULT_HR_CLAMP)
        self.assertAlmostEqual(adj.hr, expected, places=6)

    def test_high_barrel_allowed_raises_hr(self) -> None:
        # Realized neutral (hr_per_pa == league → mult 1.0); barrel-allowed 1.5× league.
        split = _split(hr_per_pa=LEAGUE_HR_PER_PA, barrel_allowed=1.5 * LEAGUE_BARREL_RATE)
        with mock.patch.object(pitcher_adj, "PITCHER_HR_BARREL_BLEND_W", 0.6):
            adj = compute_pitcher_adjustments(split)
        # blended = 0.4*1.0 + 0.6*1.5 = 1.3 (inside the clamp).
        self.assertAlmostEqual(adj.hr, 1.3, places=6)
        self.assertGreater(adj.hr, 1.0)

    def test_clamp_binds_on_extreme_barrel(self) -> None:
        split = _split(hr_per_pa=LEAGUE_HR_PER_PA, barrel_allowed=5.0 * LEAGUE_BARREL_RATE)
        with mock.patch.object(pitcher_adj, "PITCHER_HR_BARREL_BLEND_W", 0.6):
            adj = compute_pitcher_adjustments(split)
        self.assertAlmostEqual(adj.hr, PITCHER_MULT_HR_CLAMP[1], places=6)


class _FakeConn:
    """Minimal stand-in: conn.execute(sql, params).fetchall()."""

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params):
        return self

    def fetchall(self):
        return self._rows


class TestLoadPitcherBarrelAllowed(unittest.TestCase):
    def test_eb_regression_and_keying(self) -> None:
        rows = [
            (100, "L", 0.10, 75),     # regressed below raw toward league
            (100, "R", 0.078, 0),     # bip 0 → skipped
            (200, "L", None, 50),     # NULL barrel → skipped
        ]
        out = _load_pitcher_barrel_allowed(_FakeConn(rows), 2024)
        self.assertEqual(set(out), {(100, "L")})
        n = 75.0
        expected = round(
            (0.10 * n + LEAGUE_BARREL_RATE * PITCHER_BARREL_REGRESSION_BIP)
            / (n + PITCHER_BARREL_REGRESSION_BIP),
            4,
        )
        self.assertAlmostEqual(out[(100, "L")], expected, places=6)
        # Regressed value sits between the raw rate and the league mean.
        self.assertLess(out[(100, "L")], 0.10)
        self.assertGreater(out[(100, "L")], LEAGUE_BARREL_RATE)


if __name__ == "__main__":
    unittest.main()
