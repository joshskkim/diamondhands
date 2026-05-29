"""Shared database helpers."""
from __future__ import annotations

import os

import psycopg
from dotenv import load_dotenv


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
