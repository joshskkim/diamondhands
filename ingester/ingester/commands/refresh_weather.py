"""refresh-weather: Attach weather snapshot to today's scheduled games."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from ingester.db import eastern_today, get_connection
from ingester.weather import fetch_weather_at

# Sentinel values for fully enclosed (non-retractable) domed stadiums.
# The projector treats these as climate-controlled and applies no weather adjustments.
_DOME_TEMP_F   = 72
_DOME_WIND_SPD = 0
_DOME_WIND_DIR = 0


def cmd_refresh_weather(args: argparse.Namespace) -> None:
    """Fetch weather for the slate's Scheduled games starting within the next 24 h."""
    conn = get_connection()

    now_utc = datetime.now(tz=timezone.utc)
    cutoff  = now_utc + timedelta(hours=24)
    today   = args.date if args.date is not None else eastern_today()

    rows = conn.execute(
        """
        SELECT
            g.id,
            g.start_time_utc,
            s.latitude,
            s.longitude,
            s.is_dome,
            s.is_retractable
        FROM games g
        JOIN stadiums s ON s.id = g.stadium_id
        WHERE g.game_date     = %s
          AND g.status        = 'Scheduled'
          AND g.start_time_utc BETWEEN %s AND %s
        """,
        (today, now_utc, cutoff),
    ).fetchall()

    if not rows:
        print("[refresh-weather] No qualifying games found (Scheduled, within 24 h).")
        conn.close()
        return

    print(f"[refresh-weather] Fetching weather for {len(rows)} game(s)…")
    updated = 0

    for game_id, start_utc, lat, lon, is_dome, is_retractable in rows:
        if is_dome and not is_retractable:
            # Fully enclosed dome — no meaningful outdoor weather.
            conn.execute(
                """
                UPDATE games
                SET temperature_f          = %s,
                    wind_speed_mph         = %s,
                    wind_direction_degrees = %s,
                    weather_fetched_at     = NOW()
                WHERE id = %s
                """,
                (_DOME_TEMP_F, _DOME_WIND_SPD, _DOME_WIND_DIR, game_id),
            )
        else:
            w = fetch_weather_at(float(lat), float(lon), start_utc)
            conn.execute(
                """
                UPDATE games
                SET temperature_f          = %s,
                    wind_speed_mph         = %s,
                    wind_direction_degrees = %s,
                    weather_fetched_at     = NOW()
                WHERE id = %s
                """,
                (w["temperature_f"], w["wind_speed_mph"], w["wind_direction_degrees"], game_id),
            )
        updated += 1

    conn.commit()
    conn.close()

    print(f"[refresh-weather] Updated {updated} game(s).")
    print(
        "  Note: Open-Meteo is free for non-commercial use — no API key required.\n"
        "  Wind direction = meteorological 'from' direction (0=from N, 90=from E, …).\n"
        "  Domed stadiums (non-retractable) receive sentinel values: "
        f"{_DOME_TEMP_F}°F, {_DOME_WIND_SPD} mph, {_DOME_WIND_DIR}°."
    )
