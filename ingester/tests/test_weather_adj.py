"""Unit tests for projection weather math."""
from __future__ import annotations

import math
import unittest

from ingester.projection.weather_adj import (
    air_density,
    compute_weather_adjustments,
    density_hr_adjustment,
    pressure_at_altitude_hpa,
    pull_bearing_degrees,
    wind_component_mph,
    wind_to_degrees,
)
from ingester.projection.constants import SEA_LEVEL_PRESSURE_HPA


class TestAirDensity(unittest.TestCase):
    SEA = SEA_LEVEL_PRESSURE_HPA

    def test_warmer_air_is_less_dense(self) -> None:
        self.assertLess(air_density(95, 50, self.SEA), air_density(50, 50, self.SEA))

    def test_humid_air_is_less_dense(self) -> None:
        # Water vapor is lighter than dry air, so higher RH lowers density (same T, P).
        self.assertLess(air_density(85, 90, self.SEA), air_density(85, 10, self.SEA))

    def test_lower_pressure_is_less_dense(self) -> None:
        self.assertLess(air_density(70, 50, 830.0), air_density(70, 50, self.SEA))

    def test_pressure_drops_with_altitude(self) -> None:
        self.assertAlmostEqual(pressure_at_altitude_hpa(0.0), self.SEA, places=2)
        self.assertLess(pressure_at_altitude_hpa(5200.0), 870.0)  # Coors ~5200 ft

    def test_baseline_day_is_neutral(self) -> None:
        # 70°F / 50% RH / sea-level pressure at sea level == the park baseline → ~1.0.
        adj = density_hr_adjustment(70.0, 50.0, self.SEA, 0.0)
        self.assertAlmostEqual(adj, 1.0, places=3)

    def test_hot_day_boosts_hr_about_ten_percent(self) -> None:
        # Calibration target: 90°F sea-level day ≈ +10% HR vs the 70°F baseline.
        adj = density_hr_adjustment(90.0, 50.0, self.SEA, 0.0)
        self.assertGreater(adj, 1.0)
        self.assertAlmostEqual(adj, 1.10, delta=0.04)

    def test_altitude_does_not_double_count(self) -> None:
        # A 70°F day at Coors with the altitude-appropriate pressure must stay ~neutral —
        # the altitude HR boost lives in park_factor_hr, not here.
        coors_pressure = pressure_at_altitude_hpa(5200.0)
        adj = density_hr_adjustment(70.0, 50.0, coors_pressure, 5200.0)
        self.assertAlmostEqual(adj, 1.0, places=2)

    def test_pressure_absent_falls_back_to_temp_only(self) -> None:
        # No pressure → compute_weather_adjustments keeps the pre-v2.3 temp-only HR term.
        _, hr_density = compute_weather_adjustments(
            temperature_f=90, wind_speed_mph=0, wind_from_degrees=0,
            cf_bearing_degrees=0, bats="R", surface_pressure_hpa=self.SEA, altitude_ft=0.0,
        )
        _, hr_temp_only = compute_weather_adjustments(
            temperature_f=90, wind_speed_mph=0, wind_from_degrees=0,
            cf_bearing_degrees=0, bats="R",
        )
        self.assertNotAlmostEqual(hr_density, hr_temp_only, places=4)


class TestPullBearing(unittest.TestCase):
    CF_BEARING = 0.0  # home plate → CF is due north

    def test_rhb_pull_offset(self) -> None:
        self.assertAlmostEqual(
            pull_bearing_degrees(self.CF_BEARING, "R"),
            (self.CF_BEARING - 35) % 360,
        )

    def test_lhb_pull_offset(self) -> None:
        self.assertAlmostEqual(
            pull_bearing_degrees(self.CF_BEARING, "L"),
            (self.CF_BEARING + 35) % 360,
        )

    def test_switch_vs_rhp_bats_left(self) -> None:
        self.assertAlmostEqual(
            pull_bearing_degrees(self.CF_BEARING, "S", pitcher_throws="R"),
            pull_bearing_degrees(self.CF_BEARING, "L"),
        )


class TestWindComponent(unittest.TestCase):
    CF_BEARING = 0.0
    SPEED = 10.0

    def test_straight_out_to_cf_rhb(self) -> None:
        """Wind toward CF; RHB pull is 35° off → cos(35°) ≈ 0.82 of wind speed."""
        pull = pull_bearing_degrees(self.CF_BEARING, "R")
        # Wind blowing to CF: wind_to == cf_bearing → wind_from == 180
        wind_from = 180.0
        self.assertAlmostEqual(wind_to_degrees(wind_from), self.CF_BEARING)
        component = wind_component_mph(self.SPEED, wind_from, pull)
        expected = self.SPEED * math.cos(math.radians(35.0))
        self.assertAlmostEqual(component, expected, places=2)
        self.assertAlmostEqual(component / self.SPEED, 0.82, places=2)

    def test_straight_in_from_cf_rhb(self) -> None:
        """Wind from CF toward plate → negative pull-side component for RHB."""
        pull = pull_bearing_degrees(self.CF_BEARING, "R")
        wind_from = self.CF_BEARING  # from north / from CF when cf_bearing is 0
        component = wind_component_mph(self.SPEED, wind_from, pull)
        self.assertLess(component, 0.0)
        expected = self.SPEED * math.cos(math.radians(145.0))
        self.assertAlmostEqual(component, expected, places=2)

    def test_cardinal_wind_directions(self) -> None:
        """Known components for wind from N/E/S/W with cf_bearing=0, RHB pull."""
        pull = pull_bearing_degrees(self.CF_BEARING, "R")
        cases = {
            0.0: 145.0,    # from N → toward S; angle to pull (325°) is 145°
            90.0: 55.0,
            180.0: 35.0,   # out to CF
            270.0: 125.0,
        }
        for wind_from, expected_angle in cases.items():
            with self.subTest(wind_from=wind_from):
                component = wind_component_mph(self.SPEED, wind_from, pull)
                expected = self.SPEED * math.cos(math.radians(expected_angle))
                self.assertAlmostEqual(component, expected, places=4)


class TestWeatherAdjustments(unittest.TestCase):
    def test_dome_neutral(self) -> None:
        adj_hit, adj_hr = compute_weather_adjustments(
            temperature_f=40,
            wind_speed_mph=25,
            wind_from_degrees=180,
            cf_bearing_degrees=90,
            bats="R",
            is_dome=True,
            is_retractable_open=False,
        )
        self.assertEqual(adj_hit, 1.0)
        self.assertEqual(adj_hr, 1.0)

    def test_retractable_open_uses_weather(self) -> None:
        """Open retractable in a dome still applies outdoor adjustments."""
        _, adj_hr_dome = compute_weather_adjustments(
            temperature_f=70,
            wind_speed_mph=0,
            wind_from_degrees=0,
            cf_bearing_degrees=0,
            bats="R",
            is_dome=True,
            is_retractable_open=False,
        )
        _, adj_hr_open = compute_weather_adjustments(
            temperature_f=90,
            wind_speed_mph=0,
            wind_from_degrees=0,
            cf_bearing_degrees=0,
            bats="R",
            is_dome=True,
            is_retractable_open=True,
        )
        self.assertEqual(adj_hr_dome, 1.0)
        self.assertGreater(adj_hr_open, 1.0)

    def test_hot_day_increases_hr_adj(self) -> None:
        adj_hit, adj_hr = compute_weather_adjustments(
            temperature_f=90,
            wind_speed_mph=0,
            wind_from_degrees=0,
            cf_bearing_degrees=0,
            bats="R",
            is_dome=False,
        )
        self.assertGreater(adj_hr, 1.0)
        self.assertGreater(adj_hit, 1.0)


if __name__ == "__main__":
    unittest.main()
