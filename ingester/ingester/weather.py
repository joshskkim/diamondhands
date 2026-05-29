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
            "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "forecast_days": 3,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    hourly = data["hourly"]
    times  = hourly["time"]           # "YYYY-MM-DDTHH:MM" (UTC, no tz suffix)
    temps  = hourly["temperature_2m"]
    winds  = hourly["wind_speed_10m"]
    dirs   = hourly["wind_direction_10m"]

    best_idx = min(
        range(len(times)),
        key=lambda i: abs(
            (datetime.fromisoformat(times[i]).replace(tzinfo=timezone.utc) - target_utc)
            .total_seconds()
        ),
    )

    return {
        "temperature_f": round(temps[best_idx]),
        "wind_speed_mph": round(winds[best_idx]),
        "wind_direction_degrees": round(dirs[best_idx]),
    }
