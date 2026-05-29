"""refresh-weather: Attach weather snapshot to today's scheduled games."""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.weather import fetch_weather_at

# Sentinel values for domed stadiums (no Open-Meteo call).
# The projector treats dome + closed retractable as climate-controlled.
_DOME_TEMP_F = 72
_DOME_WIND_SPD = 0
_DOME_WIND_DIR = 0

# Skip finished, cancelled, or in-progress games (NOT IN filter — anything else qualifies).
# ``Live`` is the abstractGameState daily-slate stores for in-progress games.
_WEATHER_SKIP_STATUSES: tuple[str, ...] = (
    "Final",
    "Game Over",
    "Postponed",
    "Suspended",
    "Cancelled",
    "In Progress",
    "Live",
)


def cmd_refresh_weather(args: argparse.Namespace) -> None:
    """Fetch weather for slate games on ``--date`` that have not started or finished."""
    conn = get_connection()
    slate_date = args.date if args.date is not None else eastern_today()

    rows = conn.execute(
        """
        SELECT
            g.id,
            g.start_time_utc,
            s.latitude,
            s.longitude,
            s.is_dome
        FROM games g
        JOIN stadiums s ON s.id = g.stadium_id
        WHERE g.game_date = %s
          AND (g.status IS NULL OR g.status <> ALL(%s))
        """,
        (slate_date, list(_WEATHER_SKIP_STATUSES)),
    ).fetchall()

    if not rows:
        print(
            f"[refresh-weather] No qualifying games for {slate_date} "
            f"(excluded statuses: {', '.join(_WEATHER_SKIP_STATUSES)})."
        )
        conn.close()
        return

    print(f"[refresh-weather] Updating weather for {len(rows)} game(s) on {slate_date}…")
    updated = 0
    dome_sentinel = 0
    api_fetched = 0

    for game_id, start_utc, lat, lon, is_dome in rows:
        if is_dome:
            # All domes: sentinel values, no API call (projector neutralizes weather).
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
            dome_sentinel += 1
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
            api_fetched += 1
        updated += 1

    conn.commit()
    conn.close()

    print(f"[refresh-weather] Updated {updated} game(s) ({dome_sentinel} dome sentinel, {api_fetched} Open-Meteo).")
    print(
        "  Note: Open-Meteo is free for non-commercial use — no API key required.\n"
        "  Wind direction = meteorological 'from' direction (0=from N, 90=from E, …).\n"
        f"  Domed stadiums (is_dome=true) receive sentinel values: "
        f"{_DOME_TEMP_F}°F, {_DOME_WIND_SPD} mph, {_DOME_WIND_DIR}°."
    )
