"""MLB Stats API helpers — schedule, probable pitchers."""
from __future__ import annotations

from datetime import date

import requests

MLB_BASE = "https://statsapi.mlb.com/api/v1"

# Game types that belong on the daily slate.
# R=regular season, F/D/L/W=wildcard/division/league/world series.
SLATE_GAME_TYPES = {"R", "F", "D", "L", "W"}

# A complete batting order has nine slots. The lineups hydration only returns a full
# nine once the actual lineup is posted (~2-3 h before first pitch), so we treat
# "nine players present" as the confirmation signal.
LINEUP_SLOTS = 9


def fetch_schedule(game_date: date, hydrate: str = "probablePitcher") -> list[dict]:
    """
    Return one raw game dict per game on game_date, hydrated as requested.

    ``hydrate`` is passed straight to the MLB Stats API. Defaults to ``probablePitcher``
    (slate/backfill use). Pass ``"lineups,probablePitcher"`` to also pull confirmed
    batting orders (see ``parse_game_lineups``).

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
            "hydrate": hydrate,
        },
        timeout=15,
    )
    resp.raise_for_status()

    games: list[dict] = []
    for date_entry in resp.json().get("dates", []):
        for game in date_entry.get("games", []):
            games.append(game)
    return games


def parse_game_score(game: dict) -> tuple[int, int] | None:
    """Return (home_score, away_score) for a Final game, else None."""
    if (game.get("status") or {}).get("abstractGameState") != "Final":
        return None
    teams = game.get("teams") or {}
    h = (teams.get("home") or {}).get("score")
    a = (teams.get("away") or {}).get("score")
    if h is None or a is None:
        return None
    return int(h), int(a)


def parse_home_plate_umpire(game: dict) -> tuple[int, str] | None:
    """
    Extract the home-plate umpire from a schedule game hydrated with ``officials``.

    Returns ``(umpire_id, full_name)`` for the official whose ``officialType`` is
    "Home Plate", or None if officials aren't present (assignments post close to
    first pitch, and some historical games never expose them).

    game["officials"] shape:
        [{"official": {"id": 482631, "fullName": "Mike Estabrook", ...},
          "officialType": "Home Plate"}, ...]
    """
    for entry in game.get("officials") or []:
        if entry.get("officialType") == "Home Plate":
            official = entry.get("official") or {}
            uid = official.get("id")
            if uid is None:
                return None
            return int(uid), official.get("fullName") or f"Unknown#{uid}"
    return None


def parse_game_lineups(game: dict) -> dict[bool, list[tuple[int, str]]]:
    """
    Extract confirmed batting orders from a schedule game hydrated with ``lineups``.

    Returns ``{is_home: [(player_id, full_name), ...]}`` for each side that has a full
    nine-man lineup posted, ordered leadoff (index 0) through the nine-hole. A side
    without a posted lineup is omitted, so an empty dict means "nothing confirmed yet".
    The MLB API exposes only the *actual* posted lineup here (not a projection), which
    is exactly what we want to flag as confirmed.

    game["lineups"] shape: {"homePlayers": [{id, fullName, ...}, ...], "awayPlayers": [...]}
    """
    lineups = game.get("lineups") or {}
    result: dict[bool, list[tuple[int, str]]] = {}
    for is_home, key in ((True, "homePlayers"), (False, "awayPlayers")):
        players = lineups.get(key) or []
        slots = [
            (p["id"], p.get("fullName") or f"Unknown#{p['id']}")
            for p in players
            if p.get("id") is not None
        ]
        if len(slots) >= LINEUP_SLOTS:
            result[is_home] = slots[:LINEUP_SLOTS]
    return result
