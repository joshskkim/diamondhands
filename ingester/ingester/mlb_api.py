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

# How long before first pitch we start consulting the boxscore for a batting order the
# schedule 'lineups' hydration hasn't filled in yet (see fetch_boxscore_batting_orders and
# lineups._process_date). Lineup cards post ~2-3 h out; 6 h is a generous cushion that still
# avoids hammering the per-game boxscore endpoint all afternoon for games not close to start.
LINEUP_LOOKAHEAD_HOURS = 6


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


def parse_game_first_inning(game: dict) -> tuple[int, int] | None:
    """Return (home_score_1st, away_score_1st) from a game hydrated with ``linescore``,
    or None until the first inning has completed.

    The linescore exposes per-inning runs:
        linescore.innings = [{"num": 1, "home": {"runs": 0}, "away": {"runs": 1}}, ...]
    We only trust the 1st once both halves are present (runs not None on each side),
    so an in-progress top-of-the-1st doesn't grade NRFI prematurely.
    """
    innings = ((game.get("linescore") or {}).get("innings")) or []
    first = next((i for i in innings if i.get("num") == 1), None)
    if first is None:
        return None
    h = (first.get("home") or {}).get("runs")
    a = (first.get("away") or {}).get("runs")
    if h is None or a is None:
        return None
    return int(h), int(a)


def parse_game_linescore_live(game: dict) -> dict | None:
    """Return the live in-game state from a game hydrated with ``linescore``, or None
    when there's nothing live yet (Scheduled/Preview, or no linescore present).

    Unlike ``parse_game_score`` this does NOT gate on Final — it returns the running
    state for in-progress games so the home board can track them live. Final games are
    still returned (the linescore carries the final running total), but the Final
    home_score/away_score columns remain the source of truth for grading.

    Shape returned:
        {"home": int, "away": int,            # running runs each side
         "inning": int | None,                # currentInning
         "inning_state": str | None,          # 'Top' | 'Middle' | 'Bottom' | 'End'
         "is_top": bool | None}               # isTopInning
    """
    state = (game.get("status") or {}).get("abstractGameState")
    if state in (None, "Scheduled", "Preview"):
        return None
    ls = game.get("linescore") or {}
    teams = ls.get("teams") or {}
    h = (teams.get("home") or {}).get("runs")
    a = (teams.get("away") or {}).get("runs")
    if h is None or a is None:
        return None
    return {
        "home": int(h),
        "away": int(a),
        "inning": ls.get("currentInning"),
        "inning_state": ls.get("inningState"),
        "is_top": ls.get("isTopInning"),
    }


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


def fetch_boxscore_batting_orders(game_pk: int) -> dict[bool, list[tuple[int, str]]]:
    """Confirmed batting orders from GET /game/{pk}/boxscore, as a drop-in fallback for
    ``parse_game_lineups`` (same return shape) when the schedule ``lineups`` hydration lags.

    ``teams.{home,away}.battingOrder`` is a list of personIds in batting order — populated
    when the lineup card posts (pre-game), earlier and more reliably than the schedule
    hydration, which is what strands late games behind the projector's nine-man gate. Names
    come from ``teams.{side}.players['ID{pid}'].person.fullName``.

    Returns ``{is_home: [(player_id, full_name), ...]}`` for each side that has a full nine;
    a short/missing side is omitted. Any network/shape error returns ``{}`` so the caller
    simply keeps whatever the schedule gave (one bad fetch never wipes the slate).
    """
    try:
        resp = requests.get(f"{MLB_BASE}/game/{game_pk}/boxscore", timeout=15)
        resp.raise_for_status()
        teams = (resp.json().get("teams") or {})
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't break the lineup refresh
        return {}

    result: dict[bool, list[tuple[int, str]]] = {}
    for is_home, key in ((True, "home"), (False, "away")):
        side = teams.get(key) or {}
        order = side.get("battingOrder") or []
        players = side.get("players") or {}
        slots: list[tuple[int, str]] = []
        for pid in order:
            if pid is None:
                continue
            person = (players.get(f"ID{pid}") or {}).get("person") or {}
            slots.append((int(pid), person.get("fullName") or f"Unknown#{pid}"))
        if len(slots) >= LINEUP_SLOTS:
            result[is_home] = slots[:LINEUP_SLOTS]
    return result


def fetch_people_birthdates(player_ids: list[int], chunk: int = 100) -> dict[int, str]:
    """{player_id: birthDate 'YYYY-MM-DD'} from the MLB Stats API /people batch endpoint.

    Players missing a birthDate (or absent from the response) are simply omitted.
    """
    out: dict[int, str] = {}
    for i in range(0, len(player_ids), chunk):
        ids = player_ids[i : i + chunk]
        resp = requests.get(
            f"{MLB_BASE}/people",
            params={"personIds": ",".join(str(pid) for pid in ids)},
            timeout=20,
        )
        resp.raise_for_status()
        for person in resp.json().get("people", []):
            pid = person.get("id")
            bd = person.get("birthDate")
            if pid is not None and bd:
                out[int(pid)] = bd
    return out


def _parse_innings(ip: str | float | None) -> float:
    """MLB reports innings as a string like '42.1' meaning 42⅓ (the decimal is OUTS,
    not a fraction). '42.1' → 42 + 1/3, '42.2' → 42 + 2/3. Returns 0.0 on bad input."""
    if ip is None:
        return 0.0
    try:
        whole, _, frac = str(ip).partition(".")
        outs = int(frac[:1]) if frac else 0
        return int(whole) + outs / 3.0
    except (ValueError, TypeError):
        return 0.0


def fetch_pitcher_season_stats(player_id: int, season: int) -> dict | None:
    """Season pitching role stats for one pitcher, or None if no pitching split exists
    (e.g. a position player, a true debut with no MLB innings, or a network error).

    Returns {games_started, games_pitched, innings_pitched, games_finished}. Innings is
    converted from MLB's outs-decimal string (see _parse_innings). Callers treat None as
    "no season role info" and fall back to a project-anyway default.
    """
    try:
        resp = requests.get(
            f"{MLB_BASE}/people/{player_id}/stats",
            params={"stats": "season", "group": "pitching", "season": season},
            timeout=20,
        )
        resp.raise_for_status()
        splits = (resp.json().get("stats") or [{}])[0].get("splits") or []
        if not splits:
            return None
        stat = splits[0].get("stat", {})
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't break the slate
        return None
    return {
        "games_started": stat.get("gamesStarted"),
        "games_pitched": stat.get("gamesPitched"),
        "innings_pitched": _parse_innings(stat.get("inningsPitched")),
        "games_finished": stat.get("gamesFinished"),
    }


def fetch_minor_league_hitting(player_id: int, season: int, sport_id: int) -> dict | None:
    """One player's minor-league hitting line for a season at a level (sportId).

    sportId codes: 11 AAA, 12 AA, 13 High-A, 14 Low-A, 16 Rookie (see mle.LEVEL_BY_SPORT_ID).
    Returns the counting totals {pa, ab, hits, hr, tb, k} or None when the player has no
    hitting split at that level/season (or on a network error). Used by the MLE pipeline
    to project call-ups with no MLB history.
    """
    try:
        resp = requests.get(
            f"{MLB_BASE}/people/{player_id}/stats",
            params={"stats": "season", "group": "hitting",
                    "season": season, "sportId": sport_id},
            timeout=20,
        )
        resp.raise_for_status()
        splits = (resp.json().get("stats") or [{}])[0].get("splits") or []
        if not splits:
            return None
        stat = splits[0].get("stat", {})
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't break the pipeline
        return None
    pa = stat.get("plateAppearances")
    if not pa:
        return None
    return {
        "pa": pa,
        "ab": stat.get("atBats"),
        "hits": stat.get("hits"),
        "hr": stat.get("homeRuns"),
        "tb": stat.get("totalBases"),
        "k": stat.get("strikeOuts"),
    }
