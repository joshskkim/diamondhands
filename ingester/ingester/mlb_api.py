"""MLB Stats API helpers — schedule, probable pitchers."""
from __future__ import annotations

from datetime import date

import requests

MLB_BASE = "https://statsapi.mlb.com/api/v1"

# Game types that belong on the daily slate.
# R=regular season, F/D/L/W=wildcard/division/league/world series.
SLATE_GAME_TYPES = {"R", "F", "D", "L", "W"}


def fetch_schedule(game_date: date) -> list[dict]:
    """
    Return one raw game dict per game on game_date, hydrated with probablePitcher.

    Each dict is the raw MLB Stats API game object. Key paths used downstream:
        gamePk                             — MLBAM game ID (primary key)
        gameType                           — 'R', 'F', 'D', 'L', 'W', 'S', etc.
        officialDate                       — YYYY-MM-DD local date
        gameDate                           — ISO 8601 UTC start time (e.g. "2025-05-28T17:10:00Z")
        status.abstractGameState           — 'Scheduled', 'Live', 'Final', …
        teams.home.team.id                 — home team MLBAM ID
        teams.away.team.id                 — away team MLBAM ID
        teams.home.probablePitcher.id      — home starter MLBAM ID (absent if TBA)
        teams.home.probablePitcher.fullName
        teams.away.probablePitcher.id
        teams.away.probablePitcher.fullName

    Doubleheaders appear as two separate game objects with distinct gamePk values.
    """
    resp = requests.get(
        f"{MLB_BASE}/schedule",
        params={
            "sportId": 1,
            "date": game_date.strftime("%Y-%m-%d"),
            "hydrate": "probablePitcher",
        },
        timeout=15,
    )
    resp.raise_for_status()

    games: list[dict] = []
    for date_entry in resp.json().get("dates", []):
        for game in date_entry.get("games", []):
            games.append(game)
    return games
