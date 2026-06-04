"""backfill-weather: attach ACTUAL historical weather to past games (Open-Meteo archive).

Live refresh-weather only forecasts today's slate, so historical games have no weather
snapshot and the backtest neutralizes weather for them. This backfills real conditions
(temperature, wind, humidity, barometric pressure) at each game's start time so the
backtest can score the weather / air-density HR model against what actually happened.

Domed stadiums get the same climate-controlled sentinel as refresh-weather (the
projector neutralizes weather there anyway).
"""
from __future__ import annotations

import argparse

from ingester.db import get_connection
from ingester.weather import fetch_weather_archive

# Mirror refresh-weather's dome sentinel (projector treats closed roofs as neutral).
_DOME_TEMP_F = 72
_DOME_WIND_SPD = 0
_DOME_WIND_DIR = 0


def cmd_backfill_weather(args: argparse.Namespace) -> None:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT g.id, g.start_time_utc, s.latitude, s.longitude, s.is_dome
        FROM games g
        JOIN stadiums s ON s.id = g.stadium_id
        WHERE g.game_date BETWEEN %s AND %s
          AND g.stadium_id IS NOT NULL
          AND g.start_time_utc IS NOT NULL
        ORDER BY g.game_date, g.start_time_utc
        """,
        (args.start, args.end),
    ).fetchall()

    if not rows:
        print(f"[backfill-weather] No games with stadium + start time in {args.start}..{args.end}.")
        conn.close()
        return

    print(f"[backfill-weather] Backfilling weather for {len(rows)} game(s)…")
    api_fetched = dome_sentinel = failed = 0

    for game_id, start_utc, lat, lon, is_dome in rows:
        try:
            if is_dome:
                t, ws, wd, hum, pr = _DOME_TEMP_F, _DOME_WIND_SPD, _DOME_WIND_DIR, None, None
                dome_sentinel += 1
            else:
                w = fetch_weather_archive(float(lat), float(lon), start_utc)
                t, ws, wd = w["temperature_f"], w["wind_speed_mph"], w["wind_direction_degrees"]
                hum, pr = w.get("relative_humidity_pct"), w.get("surface_pressure_hpa")
                api_fetched += 1
        except Exception as exc:  # noqa: BLE001 — skip a game we can't fetch, keep going
            print(f"  game {game_id}: archive fetch failed ({exc}); skipping")
            failed += 1
            continue

        conn.execute(
            """
            UPDATE games
            SET temperature_f          = %s,
                wind_speed_mph         = %s,
                wind_direction_degrees = %s,
                relative_humidity_pct  = %s,
                surface_pressure_hpa   = %s,
                weather_fetched_at     = NOW()
            WHERE id = %s
            """,
            (t, ws, wd, hum, pr, game_id),
        )

    conn.commit()
    conn.close()
    print(
        f"[backfill-weather] Done — {api_fetched} archive, {dome_sentinel} dome sentinel"
        + (f", {failed} failed" if failed else "")
    )
