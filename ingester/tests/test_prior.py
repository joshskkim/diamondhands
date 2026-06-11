"""Hand-computed unit tests for the Marcel-style true-talent prior."""
from __future__ import annotations

import unittest

from ingester.projection.constants import (
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_XWOBA,
    MARCEL_REGRESSION_PA_ISO,
    MARCEL_REGRESSION_PA_K,
    MARCEL_REGRESSION_PA_XWOBA,
)
from ingester.projection.prior import (
    ProjectionPrior,
    SeasonLine,
    compute_marcel_prior,
)


class TestMarcelPrior(unittest.TestCase):
    def _three_seasons(self) -> dict[int, SeasonLine]:
        # target = 2026 → prior years 2025 (w5), 2024 (w4), 2023 (w3).
        return {
            2025: SeasonLine(pa=600, ab=540, hits=160, hr=30, tb=280, k=120, xwoba=0.360),
            2024: SeasonLine(pa=550, ab=500, hits=140, hr=25, tb=240, k=110, xwoba=0.350),
            2023: SeasonLine(pa=500, ab=450, hits=120, hr=20, tb=200, k=100, xwoba=0.340),
        }

    def test_full_three_season_prior(self):
        prior = compute_marcel_prior(
            self._three_seasons(),
            2026,
            league_xwoba=LEAGUE_XWOBA,
            league_k_rate=LEAGUE_K_PER_PA,
            league_iso=LEAGUE_ISO,
        )
        assert prior is not None
        # weighted PA = 5*600 + 4*550 + 3*500 = 6700
        self.assertEqual(prior.proj_pa, 6700)

        # Each metric regresses to league by its OWN constant; weighted PA = 6700.
        # xwOBA num = 5*600*.360 + 4*550*.350 + 3*500*.340 = 2360
        exp_xwoba = (2360 + MARCEL_REGRESSION_PA_XWOBA * LEAGUE_XWOBA) / (6700 + MARCEL_REGRESSION_PA_XWOBA)
        self.assertAlmostEqual(prior.xwoba, round(exp_xwoba, 4), places=4)

        # K rate: each season is exactly .20 (k/pa), so weighted = .20.
        exp_k = (6700 * 0.20 + MARCEL_REGRESSION_PA_K * LEAGUE_K_PER_PA) / (6700 + MARCEL_REGRESSION_PA_K)
        self.assertAlmostEqual(prior.k_rate, round(exp_k, 4), places=4)

        # ISO per season = (tb-hits)/ab: .222222, .200000, .177778
        iso_num = 3000 * ((280 - 160) / 540) + 2200 * 0.20 + 1500 * ((200 - 120) / 450)
        exp_iso = (iso_num + MARCEL_REGRESSION_PA_ISO * LEAGUE_ISO) / (6700 + MARCEL_REGRESSION_PA_ISO)
        self.assertAlmostEqual(prior.iso, round(exp_iso, 4), places=4)

    def test_single_prior_season_regresses_hard_to_league(self):
        # Only 2025 present, modest sample → heavy pull toward league.
        seasons = {
            2025: SeasonLine(pa=200, ab=180, hits=70, hr=15, tb=130, k=30, xwoba=0.420),
        }
        prior = compute_marcel_prior(
            seasons, 2026,
            league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO,
        )
        assert prior is not None
        # weighted PA = 5*200 = 1000; xwOBA regression adds its own constant of league.
        self.assertEqual(prior.proj_pa, 1000)
        exp_xwoba = (1000 * 0.420 + MARCEL_REGRESSION_PA_XWOBA * LEAGUE_XWOBA) / (1000 + MARCEL_REGRESSION_PA_XWOBA)
        self.assertAlmostEqual(prior.xwoba, round(exp_xwoba, 4), places=4)
        # Hot .420 sample lands well below itself after regression.
        self.assertLess(prior.xwoba, 0.420)
        self.assertGreater(prior.xwoba, LEAGUE_XWOBA)

    def test_no_prior_returns_none(self):
        prior = compute_marcel_prior(
            {}, 2026,
            league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO,
        )
        self.assertIsNone(prior)

    def test_zero_pa_season_ignored(self):
        # A season with pa=0 must not count as a prior year.
        prior = compute_marcel_prior(
            {2025: SeasonLine(pa=0, ab=0, hits=0, hr=0, tb=0, k=0, xwoba=None)},
            2026,
            league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO,
        )
        self.assertIsNone(prior)

    def test_missing_xwoba_falls_back_per_metric(self):
        # xwoba None for the only season → xwoba is pure league; k/iso still computed.
        seasons = {
            2025: SeasonLine(pa=600, ab=540, hits=160, hr=30, tb=280, k=120, xwoba=None),
        }
        prior = compute_marcel_prior(
            seasons, 2026,
            league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO,
        )
        assert prior is not None
        self.assertAlmostEqual(prior.xwoba, round(LEAGUE_XWOBA, 4), places=4)
        # K rate still reflects the sample (0.20 regressed toward league).
        self.assertNotAlmostEqual(prior.k_rate, LEAGUE_K_PER_PA, places=3)


if __name__ == "__main__":
    unittest.main()
