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
from ingester.projection import constants as C
from ingester.projection.prior import (
    SeasonLine,
    aging_factor,
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


class TestBatSpeedIsoAnchor(unittest.TestCase):
    def test_hand_computed_anchor(self):
        from ingester.projection.constants import (
            BAT_SPEED_ISO_PER_Z, BAT_SPEED_MEAN, BAT_SPEED_SD,
            FAST_SWING_ISO_PER_Z, FAST_SWING_MEAN, FAST_SWING_SD,
        )
        from ingester.projection.prior import bat_speed_iso_anchor
        bs, fast = 72.49, 0.383  # +1 SD on both, exactly
        expected = (LEAGUE_ISO
                    + BAT_SPEED_ISO_PER_Z * (bs - BAT_SPEED_MEAN) / BAT_SPEED_SD
                    + FAST_SWING_ISO_PER_Z * (fast - FAST_SWING_MEAN) / FAST_SWING_SD)
        self.assertAlmostEqual(bat_speed_iso_anchor(bs, fast, LEAGUE_ISO), expected, places=9)
        self.assertIsNone(bat_speed_iso_anchor(None, 0.2, LEAGUE_ISO))
        self.assertIsNone(bat_speed_iso_anchor(70.0, None, LEAGUE_ISO))

    def test_iso_anchor_replaces_league_target(self):
        from ingester.projection.prior import bat_speed_iso_anchor as _anchor  # noqa: F401
        seasons = {2025: SeasonLine(pa=200, ab=180, hits=45, hr=5, tb=70, k=50, xwoba=0.300)}
        kw = dict(league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO)
        plain = compute_marcel_prior(seasons, 2026, **kw)
        hi = compute_marcel_prior(seasons, 2026, **kw, iso_anchor=LEAGUE_ISO + 0.05)
        lo = compute_marcel_prior(seasons, 2026, **kw, iso_anchor=LEAGUE_ISO - 0.05)
        # Thin history (1000 weighted PA vs 1800 phantom): anchor moves ISO a lot.
        self.assertGreater(hi.iso, plain.iso)
        self.assertLess(lo.iso, plain.iso)
        # Other metrics untouched.
        self.assertAlmostEqual(hi.xwoba, plain.xwoba, places=9)
        self.assertAlmostEqual(hi.k_rate, plain.k_rate, places=9)


class TestWhiffKAnchor(unittest.TestCase):
    def test_hand_computed_anchor(self):
        from ingester.projection.constants import WHIFF_K_PER_Z, WHIFF_MEAN, WHIFF_SD
        from ingester.projection.prior import whiff_k_anchor
        whiff = WHIFF_MEAN + WHIFF_SD  # exactly +1 SD
        expected = LEAGUE_K_PER_PA + WHIFF_K_PER_Z
        self.assertAlmostEqual(whiff_k_anchor(whiff, LEAGUE_K_PER_PA), expected, places=9)
        # League-average whiff -> league K (no nudge).
        self.assertAlmostEqual(whiff_k_anchor(WHIFF_MEAN, LEAGUE_K_PER_PA), LEAGUE_K_PER_PA, places=9)
        self.assertIsNone(whiff_k_anchor(None, LEAGUE_K_PER_PA))

    def test_k_anchor_replaces_league_target(self):
        seasons = {2025: SeasonLine(pa=200, ab=180, hits=45, hr=5, tb=70, k=50, xwoba=0.300)}
        kw = dict(league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA, league_iso=LEAGUE_ISO)
        plain = compute_marcel_prior(seasons, 2026, **kw)
        hi = compute_marcel_prior(seasons, 2026, **kw, k_rate_anchor=LEAGUE_K_PER_PA + 0.05)
        lo = compute_marcel_prior(seasons, 2026, **kw, k_rate_anchor=LEAGUE_K_PER_PA - 0.05)
        # Thin history leans on the anchor: a higher K anchor pulls the K prior up.
        self.assertGreater(hi.k_rate, plain.k_rate)
        self.assertLess(lo.k_rate, plain.k_rate)
        # Other metrics untouched.
        self.assertAlmostEqual(hi.xwoba, plain.xwoba, places=9)
        self.assertAlmostEqual(hi.iso, plain.iso, places=9)


class TestAgingFactor(unittest.TestCase):
    def test_neutral_at_peak(self):
        self.assertAlmostEqual(aging_factor(27, 27, 0.004, 0.006, (0.9, 1.06)), 1.0)

    def test_young_boosted_old_declined(self):
        young = aging_factor(23, 27, 0.004, 0.006, (0.9, 1.06))
        old = aging_factor(35, 27, 0.004, 0.006, (0.9, 1.06))
        self.assertGreater(young, 1.0)
        self.assertLess(old, 1.0)

    def test_clamped(self):
        # A 19-year-old would exceed the cap without clamping.
        self.assertEqual(aging_factor(10, 27, 0.004, 0.006, (0.9, 1.06)), 1.06)
        self.assertEqual(aging_factor(60, 27, 0.004, 0.006, (0.9, 1.06)), 0.9)


class TestAgingInPrior(unittest.TestCase):
    """The aging curve only applies when DIAMOND_AGING_ENABLED; toggled here."""

    def setUp(self):
        self.seasons = {
            2023: SeasonLine(pa=600, ab=540, hits=150, hr=25, tb=260, k=120, xwoba=0.350),
            2024: SeasonLine(pa=600, ab=540, hits=150, hr=25, tb=260, k=120, xwoba=0.350),
            2025: SeasonLine(pa=600, ab=540, hits=150, hr=25, tb=260, k=120, xwoba=0.350),
        }
        self.kw = dict(league_xwoba=LEAGUE_XWOBA, league_k_rate=LEAGUE_K_PER_PA,
                       league_iso=LEAGUE_ISO)

    def test_off_by_default_ignores_age(self):
        base = compute_marcel_prior(self.seasons, 2026, **self.kw)
        aged = compute_marcel_prior(self.seasons, 2026, **self.kw, age=35)
        self.assertEqual(base.xwoba, aged.xwoba)
        self.assertEqual(base.iso, aged.iso)

    def test_enabled_ages_young_up_old_down(self):
        C.AGING_ENABLED = True
        try:
            base = compute_marcel_prior(self.seasons, 2026, **self.kw)
            young = compute_marcel_prior(self.seasons, 2026, **self.kw, age=23)
            old = compute_marcel_prior(self.seasons, 2026, **self.kw, age=36)
        finally:
            C.AGING_ENABLED = False
        self.assertGreater(young.xwoba, base.xwoba)
        self.assertGreater(young.iso, base.iso)
        self.assertLess(old.xwoba, base.xwoba)
        self.assertLess(old.iso, base.iso)
        # K-rate is deliberately not aged.
        self.assertEqual(young.k_rate, base.k_rate)
        self.assertEqual(old.k_rate, base.k_rate)

    def test_enabled_neutral_at_peak_ish(self):
        # At the xwOBA peak age the xwOBA is essentially unchanged (ISO peak differs).
        C.AGING_ENABLED = True
        try:
            base = compute_marcel_prior(self.seasons, 2026, **self.kw)
            peak = compute_marcel_prior(self.seasons, 2026, **self.kw,
                                        age=C.AGING_PEAK_AGE_XWOBA)
        finally:
            C.AGING_ENABLED = False
        self.assertAlmostEqual(peak.xwoba, base.xwoba, places=4)
