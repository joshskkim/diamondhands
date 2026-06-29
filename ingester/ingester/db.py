"""Shared database helpers."""
from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv

_EASTERN = ZoneInfo("America/New_York")


def eastern_today() -> date:
    """Return today's date in US/Eastern (MLB schedules are Eastern-based)."""
    return datetime.now(tz=_EASTERN).date()


def active_slate_date(conn: psycopg.Connection) -> date:
    """The slate the boards are showing right now: the latest game_date with games, capped
    at today (Eastern). Mirrors the API's SlateService.activeSlateDate.

    Why not just eastern_today(): a late West-Coast game (officialDate = yesterday) is still
    being played after midnight ET, but eastern_today() flips to the new calendar day at
    midnight and the schedule for the new day doesn't contain it — so live-refresh would
    stop ticking it and never finalize it until the 9am slate build. Holding yesterday's
    slate until today's games rows exist keeps those late games tracked through to Final.
    Falls back to today when no games exist yet."""
    et = eastern_today()
    row = conn.execute(
        "SELECT MAX(game_date) FROM games WHERE game_date <= %s", (et,)
    ).fetchone()
    return row[0] if row and row[0] is not None else et


def get_connection() -> psycopg.Connection:
    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set in .env")
    return psycopg.connect(url)


def build_team_abbrev_map(conn: psycopg.Connection) -> dict[str, int]:
    """Return {abbreviation: team_id} from the teams table."""
    rows = conn.execute("SELECT id, abbreviation FROM teams").fetchall()
    return {abbrev: tid for tid, abbrev in rows}
