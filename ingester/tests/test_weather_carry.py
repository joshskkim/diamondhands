"""Unit tests for the v2.6 trajectory-level weather model (carry → HR)."""
from __future__ import annotations

import unittest

from ingester.projection.constants import (
    LEAGUE_EV_MPH,
    WEATHER_CARRY_HR_CLAMP,
    WEATHER_TEMP_BASELINE_F,
)
from ingester.projection.park_adj import (
    BattedBallProfile,
    LEAGUE_AVERAGE_PROFILE,
    ParkGeometry,
    weather_carry_hr_mult,
)
from ingester.projection.weather_adj import carry_delta_ft

NEUTRAL_PARK = ParkGeometry(
    lf_line_ft=335, cf_ft=405, rf_line_ft=335,
    lf_wall_ft=8, cf_wall_ft=8, rf_wall_ft=8,
)
POWER = BattedBallProfile(0.55, 0.27, 0.18, 0.40, 94.0)
SLAP = BattedBallProfile(0.40, 0.30, 0.30, 0.15, 84.0)

# A still, 70°F, sea-level day = the baseline → zero carry delta.
BASELINE_KW = dict(
    temperature_f=WEATHER_TEMP_BASELINE_F,
    wind_speed_mph=0.0,
    wind_from_degrees=0.0,
    cf_bearing_degrees=0.0,
    bats="R",
    humidity_pct=50.0,
    surface_pressure_hpa=None,  # → standard pressure at altitude
    altitude_ft=0.0,
)


class TestCarryDelta(unittest.TestCase):
    def test_baseline_is_zero(self):
        self.assertAlmostEqual(carry_delta_ft(**BASELINE_KW), 0.0, places=2)

    def test_hot_air_adds_carry(self):
        kw = {**BASELINE_KW, "temperature_f": 95.0}
        self.assertGreater(carry_delta_ft(**kw), 0.0)

    def test_cold_air_subtracts_carry(self):
        kw = {**BASELINE_KW, "temperature_f": 45.0}
        self.assertLess(carry_delta_ft(**kw), 0.0)

    def test_altitude_cancels_at_baseline(self):
        # By design the park's STATIC altitude is in the empirical park_factor_hr, so
        # the carry model uses the park's own altitude baseline → altitude alone (at
        # baseline temp/RH) nets zero; only the day's weather deviation drives carry.
        kw = {**BASELINE_KW, "altitude_ft": 5200.0}
        self.assertAlmostEqual(carry_delta_ft(**kw), 0.0, places=2)

    def test_hot_day_at_altitude_adds_carry(self):
        # A hot day at Coors still adds carry — via temperature, not the static altitude.
        kw = {**BASELINE_KW, "altitude_ft": 5200.0, "temperature_f": 92.0}
        self.assertGreater(carry_delta_ft(**kw), 0.0)

    def test_tailwind_adds_headwind_subtracts(self):
        # CF bearing 0 (north); RHB pulls to LF. Wind blowing toward the pull field
        # (out) adds carry; blowing in subtracts it.
        pull_out = {**BASELINE_KW, "wind_speed_mph": 15.0, "wind_from_degrees": 215.0}
        pull_in = {**BASELINE_KW, "wind_speed_mph": 15.0, "wind_from_degrees": 35.0}
        self.assertGreater(carry_delta_ft(**pull_out), 0.0)
        self.assertLess(carry_delta_ft(**pull_in), 0.0)

    def test_dome_is_zero(self):
        kw = {**BASELINE_KW, "temperature_f": 95.0, "is_dome": True}
        self.assertEqual(carry_delta_ft(**kw), 0.0)


class TestWeatherCarryHrMult(unittest.TestCase):
    def test_zero_delta_is_neutral(self):
        self.assertEqual(weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", 0.0), 1.0)

    def test_missing_inputs_neutral(self):
        self.assertEqual(weather_carry_hr_mult(None, POWER, "R", 12.0), 1.0)
        self.assertEqual(weather_carry_hr_mult(NEUTRAL_PARK, None, "R", 12.0), 1.0)

    def test_added_carry_boosts_reduced_carry_suppresses(self):
        self.assertGreater(weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", 12.0), 1.0)
        self.assertLess(weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", -12.0), 1.0)

    def test_slap_hitter_damped_below_power(self):
        # The power gate must kill the logistic-tail inversion: a soft hitter's HR
        # rate is far less weather-sensitive than a masher's.
        m_power = weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", 15.0)
        m_slap = weather_carry_hr_mult(NEUTRAL_PARK, SLAP, "R", 15.0)
        self.assertGreater(m_power, 1.0)
        self.assertLess(m_slap - 1.0, m_power - 1.0)

    def test_league_average_profile_responds(self):
        # The fallback profile (EV = league) still gets a real weather effect.
        m = weather_carry_hr_mult(NEUTRAL_PARK, LEAGUE_AVERAGE_PROFILE, "R", 12.0)
        self.assertGreater(m, 1.0)

    def test_within_clamp(self):
        big = weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", 60.0)
        small = weather_carry_hr_mult(NEUTRAL_PARK, POWER, "R", -60.0)
        self.assertLessEqual(big, WEATHER_CARRY_HR_CLAMP[1])
        self.assertGreaterEqual(small, WEATHER_CARRY_HR_CLAMP[0])


if __name__ == "__main__":
    unittest.main()
