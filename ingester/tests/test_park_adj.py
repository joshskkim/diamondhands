"""Unit tests for personalized park HR factors (v2.5.0)."""
from __future__ import annotations

import unittest

from ingester.projection.constants import (
    LEAGUE_CENTER_PCT,
    LEAGUE_EV_MPH,
    LEAGUE_FB_PCT,
    LEAGUE_OPPO_PCT,
    LEAGUE_PULL_PCT,
    PARK_GEO_MULT_CLAMP,
)
from ingester.projection.park_adj import (
    BattedBallProfile,
    ParkFactors,
    ParkGeometry,
    compute_park_adjustments,
    personalized_park_hr_mult,
)

# A short-porch park (shallow corners) and a cavernous one, walls standard.
SHORT_PARK = ParkGeometry(
    lf_line_ft=318, cf_ft=405, rf_line_ft=314,
    lf_wall_ft=8, cf_wall_ft=8, rf_wall_ft=8,
)
DEEP_PARK = ParkGeometry(
    lf_line_ft=355, cf_ft=420, rf_line_ft=353,
    lf_wall_ft=8, cf_wall_ft=8, rf_wall_ft=8,
)

LEAGUE_PROFILE = BattedBallProfile(
    pull_pct=LEAGUE_PULL_PCT,
    center_pct=LEAGUE_CENTER_PCT,
    oppo_pct=LEAGUE_OPPO_PCT,
    fb_pct=LEAGUE_FB_PCT,
    avg_launch_speed=LEAGUE_EV_MPH,
)

PULL_POWER = BattedBallProfile(
    pull_pct=0.55, center_pct=0.27, oppo_pct=0.18, fb_pct=0.40, avg_launch_speed=92.0,
)
WEAK_GROUNDER = BattedBallProfile(
    pull_pct=0.40, center_pct=0.30, oppo_pct=0.30, fb_pct=0.20, avg_launch_speed=83.0,
)


class TestPersonalizedParkHrMult(unittest.TestCase):
    def test_league_average_hitter_is_neutral_in_any_park(self):
        # Batter == reference ⇒ ratio 1.0 ⇒ no personalization, every park.
        for park in (SHORT_PARK, DEEP_PARK):
            for hand in ("L", "R"):
                self.assertAlmostEqual(
                    personalized_park_hr_mult(park, LEAGUE_PROFILE, hand), 1.0, places=4
                )

    def test_missing_inputs_are_neutral(self):
        self.assertEqual(personalized_park_hr_mult(None, PULL_POWER, "R"), 1.0)
        self.assertEqual(personalized_park_hr_mult(SHORT_PARK, None, "R"), 1.0)

    def test_pull_power_hitter_boosted(self):
        # A pull-heavy masher clears the fence more often than the average hitter.
        self.assertGreater(personalized_park_hr_mult(SHORT_PARK, PULL_POWER, "L"), 1.0)

    def test_weak_grounder_suppressed(self):
        self.assertLess(personalized_park_hr_mult(SHORT_PARK, WEAK_GROUNDER, "R"), 1.0)

    def test_monotonic_in_exit_velocity(self):
        def mult(ev: float) -> float:
            prof = BattedBallProfile(0.50, 0.28, 0.22, 0.40, ev)
            return personalized_park_hr_mult(SHORT_PARK, prof, "R")
        self.assertLess(mult(85.0), mult(90.0))
        self.assertLess(mult(90.0), mult(95.0))

    def test_fly_ball_gate_dampens_spray_effect(self):
        # Same EV/spray, but a ground-ball hitter's park edge is pulled toward 1.0.
        flyer = BattedBallProfile(0.55, 0.27, 0.18, 0.45, 93.0)
        grounder = BattedBallProfile(0.55, 0.27, 0.18, 0.15, 93.0)
        m_fly = personalized_park_hr_mult(SHORT_PARK, flyer, "L")
        m_grd = personalized_park_hr_mult(SHORT_PARK, grounder, "L")
        self.assertGreater(m_fly, 1.0)
        self.assertLess(abs(m_grd - 1.0), abs(m_fly - 1.0))

    def test_result_within_clamp(self):
        extreme = BattedBallProfile(0.75, 0.15, 0.10, 0.60, 99.0)
        m = personalized_park_hr_mult(SHORT_PARK, extreme, "L")
        self.assertGreaterEqual(m, PARK_GEO_MULT_CLAMP[0])
        self.assertLessEqual(m, PARK_GEO_MULT_CLAMP[1])

    def test_compute_park_adjustments_applies_to_correct_hand(self):
        factors = ParkFactors(
            park_factor_hits=1.0,
            park_factor_hr_lhb=1.10,
            park_factor_hr_rhb=0.90,
            geometry=SHORT_PARK,
        )
        # League-average profile ⇒ mult 1.0 ⇒ hr equals the raw hand factor.
        rhb = compute_park_adjustments(factors, "R", "R", profile=LEAGUE_PROFILE)
        self.assertAlmostEqual(rhb.hr, 0.90, places=4)
        lhb = compute_park_adjustments(factors, "L", "R", profile=LEAGUE_PROFILE)
        self.assertAlmostEqual(lhb.hr, 1.10, places=4)
        # No profile ⇒ also raw factor (backtest path).
        self.assertAlmostEqual(
            compute_park_adjustments(factors, "R", "R").hr, 0.90, places=4
        )

    def test_pull_power_lhb_beats_league_factor(self):
        factors = ParkFactors(
            park_factor_hits=1.0, park_factor_hr_lhb=1.00, park_factor_hr_rhb=1.00,
            geometry=SHORT_PARK,
        )
        adj = compute_park_adjustments(factors, "L", "R", profile=PULL_POWER)
        self.assertGreater(adj.hr, 1.00)


if __name__ == "__main__":
    unittest.main()
