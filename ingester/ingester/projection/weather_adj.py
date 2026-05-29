"""Weather adjustments: pull bearing, wind component, temperature scaling.

Wind convention matches ``ingester.weather``: ``wind_from_degrees`` is the
meteorological direction the wind is coming FROM. We convert to blow-TOWARD
before comparing to the batter's pull bearing.
"""
from __future__ import annotations

import math

from ingester.projection.constants import (
    DOME_WEATHER_ADJ,
    PULL_BEARING_OFFSET_DEG,
    TEMP_HIT_CLAMP,
    TEMP_HIT_COEFF_PER_F,
    TEMP_HR_CLAMP,
    TEMP_HR_COEFF_PER_F,
    WEATHER_TEMP_BASELINE_F,
    WIND_HR_CLAMP,
    WIND_HR_COEFF_PER_MPH,
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _normalize_degrees(degrees: float) -> float:
    return degrees % 360.0


def effective_bats(bats: str, pitcher_throws: str | None = None) -> str:
    """
    Batting side used for pull direction and park HR factor.

    Switch hitters bat opposite the pitcher's throwing hand (v1 rule).
    """
    side = bats.strip().upper()
    if side == "S":
        if pitcher_throws is None:
            raise ValueError("pitcher_throws required for switch hitters")
        throws = pitcher_throws.strip().upper()
        if throws == "R":
            return "L"
        if throws == "L":
            return "R"
        raise ValueError(f"invalid pitcher_throws: {pitcher_throws!r}")
    if side not in ("L", "R"):
        raise ValueError(f"invalid bats: {bats!r}")
    return side


def pull_bearing_degrees(
    cf_bearing_degrees: float,
    bats: str,
    pitcher_throws: str | None = None,
) -> float:
    """
    Compass bearing (degrees, clockwise from north) toward the batter's pull field.

    RHB pulls toward LF: ``cf_bearing - offset``.
    LHB pulls toward RF: ``cf_bearing + offset``.
    """
    hand = effective_bats(bats, pitcher_throws)
    cf = _normalize_degrees(cf_bearing_degrees)
    if hand == "R":
        return _normalize_degrees(cf - PULL_BEARING_OFFSET_DEG)
    return _normalize_degrees(cf + PULL_BEARING_OFFSET_DEG)


def wind_to_degrees(wind_from_degrees: float) -> float:
    """Direction the wind is blowing toward (opposite of meteorological 'from')."""
    return _normalize_degrees(wind_from_degrees + 180.0)


def smallest_angle_degrees(a_degrees: float, b_degrees: float) -> float:
    """Smallest angle between two compass bearings, in [0, 180]."""
    delta = abs(_normalize_degrees(a_degrees) - _normalize_degrees(b_degrees))
    if delta > 180.0:
        delta = 360.0 - delta
    return delta


def wind_component_mph(
    wind_speed_mph: float,
    wind_from_degrees: float,
    pull_bearing: float,
) -> float:
    """
    Wind speed projected onto the pull direction.

    Positive = tailwind blowing out toward the pull field; negative = blowing in.
    """
    wind_to = wind_to_degrees(wind_from_degrees)
    delta = smallest_angle_degrees(wind_to, pull_bearing)
    return wind_speed_mph * math.cos(math.radians(delta))


def temperature_hr_adjustment(temperature_f: float) -> float:
    adj = 1.0 + (temperature_f - WEATHER_TEMP_BASELINE_F) * TEMP_HR_COEFF_PER_F
    return _clamp(adj, *TEMP_HR_CLAMP)


def temperature_hit_adjustment(temperature_f: float) -> float:
    adj = 1.0 + (temperature_f - WEATHER_TEMP_BASELINE_F) * TEMP_HIT_COEFF_PER_F
    return _clamp(adj, *TEMP_HIT_CLAMP)


def wind_hr_adjustment(wind_component_mph: float) -> float:
    adj = 1.0 + wind_component_mph * WIND_HR_COEFF_PER_MPH
    return _clamp(adj, *WIND_HR_CLAMP)


def weather_is_neutral(*, is_dome: bool, is_retractable_open: bool) -> bool:
    """True when roof/dome blocks weather effects (v1: closed dome or closed retractable)."""
    return is_dome and not is_retractable_open


def compute_weather_adjustments(
    *,
    temperature_f: float,
    wind_speed_mph: float,
    wind_from_degrees: float,
    cf_bearing_degrees: float,
    bats: str,
    pitcher_throws: str | None = None,
    is_dome: bool = False,
    is_retractable_open: bool = False,
) -> tuple[float, float]:
    """
    Return ``(adj_weather_hit, adj_weather_hr)`` multipliers for rate blending.

    Dome / closed retractable: both 1.0. Otherwise temp affects hits and HR;
    wind affects HR only at v1 (hit adj is temperature-only).
    """
    if weather_is_neutral(is_dome=is_dome, is_retractable_open=is_retractable_open):
        return DOME_WEATHER_ADJ, DOME_WEATHER_ADJ

    pull = pull_bearing_degrees(cf_bearing_degrees, bats, pitcher_throws)
    component = wind_component_mph(wind_speed_mph, wind_from_degrees, pull)

    adj_temp_hit = temperature_hit_adjustment(temperature_f)
    adj_temp_hr = temperature_hr_adjustment(temperature_f)
    adj_wind_hr = wind_hr_adjustment(component)

    return adj_temp_hit, adj_temp_hr * adj_wind_hr
