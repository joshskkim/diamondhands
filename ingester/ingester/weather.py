"""Open-Meteo weather wrapper — free, no API key required.

Wind direction convention
-------------------------
Open-Meteo returns ``wind_direction_10m`` as the compass direction the wind is
coming FROM (standard meteorological convention):

    0° = wind from North  (blowing southward)
    90° = wind from East  (blowing westward)
    180° = wind from South (blowing northward)
    270° = wind from West  (blowing eastward)

This is stored as-is in ``games.wind_direction_degrees``.  The projector must
compare this against ``stadiums.cf_bearing_degrees`` (home plate → CF) to
determine whether wind is blowing toward or away from the plate:

    carry_angle = (wind_dir - cf_bearing + 180) % 360
    # 0° → directly blowing to CF (boosts HR), 180° → directly into CF (suppresses HR)
"""
from __future__ import annotations

from datetime import datetime, timezone

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
# Historical actuals (for backfilling past games so the backtest can use weather).
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_HOURLY_FIELDS = (
    "temperature_2m,wind_speed_10m,wind_direction_10m,"
    "relative_humidity_2m,surface_pressure"
)


def _select_hour(hourly: dict, target_utc: datetime) -> dict:
    """Pick the hourly row closest to target_utc and shape it into our weather dict."""
    times = hourly["time"]  # "YYYY-MM-DDTHH:MM" (GMT, no tz suffix)
    best_idx = min(
        range(len(times)),
        key=lambda i: abs(
            (datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target_utc)
            .total_seconds()
        ),
    )

    def _at(seq):
        v = seq[best_idx] if seq and best_idx < len(seq) else None
        return round(v, 1) if v is not None else None

    return {
        "temperature_f": round(hourly["temperature_2m"][best_idx]),
        "wind_speed_mph": round(hourly["wind_speed_10m"][best_idx]),
        "wind_direction_degrees": round(hourly["wind_direction_10m"][best_idx]),
        "relative_humidity_pct": _at(hourly.get("relative_humidity_2m")),
        "surface_pressure_hpa": _at(hourly.get("surface_pressure")),
    }


def fetch_weather_archive(lat: float, lon: float, target_utc: datetime) -> dict:
    """Historical (actual) weather from the Open-Meteo archive for a past game time.

    Same shape as fetch_weather_at. Used by backfill-weather so the backtest can score
    weather/air-density effects against real conditions instead of neutralizing them.
    """
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)
    day = target_utc.date().isoformat()
    resp = requests.get(
        OPEN_METEO_ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "start_date": day,
            "end_date": day,
            "hourly": _HOURLY_FIELDS,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
        },
        timeout=20,
    )
    resp.raise_for_status()
    return _select_hour(resp.json()["hourly"], target_utc)


def fetch_weather_at(lat: float, lon: float, target_utc: datetime) -> dict[str, int]:
    """
    Fetch the Open-Meteo hourly forecast and return the row closest to target_utc.

    Args:
        lat:        Stadium latitude.
        lon:        Stadium longitude.
        target_utc: Game start time in UTC (tz-aware or naïve treated as UTC).

    Returns:
        {
            "temperature_f": int,          # Fahrenheit
            "wind_speed_mph": int,         # mph
            "wind_direction_degrees": int, # meteorological 'from' direction, 0-359
        }
    """
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=timezone.utc)

    resp = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": _HOURLY_FIELDS,
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "forecast_days": 3,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return _select_hour(resp.json()["hourly"], target_utc)
