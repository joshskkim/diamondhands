"""Forward-looking playing-time / start-probability model (Phase 2c).

A projection is worthless if the player sits or bats 9th, and the confirmed lineup
often posts late. This estimates, from each player's RECENT usage (the team's last
`PT_WINDOW` games of `game_lineups`), the probability he starts today and his expected
plate appearances — recency-weighted so a player just promoted to leadoff (or benched)
is reflected fast. It lets us project before lineups drop and replaces the flat 4.0-PA
fallback with a usage-aware number.

Pure helpers are unit-tested; `project_playing_time` is the thin DB-backed entry point.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from ingester.projection.constants import (
    EXPECTED_PA_PER_STARTER,
    PA_BY_ORDER,
    PT_RECENCY_DECAY,
    PT_WINDOW,
)


@dataclass(frozen=True)
class PlayingTime:
    player_id: int
    p_start: float                 # recency-weighted P(in the starting lineup today)
    expected_slot: float | None    # weighted-avg batting-order slot when starting (None if never)
    expected_pa: float             # unconditional expected PA = p_start * E[PA | start]


def _weights(n: int, decay: float) -> list[float]:
    """Geometric recency weights, index 0 = most recent game (weight 1)."""
    return [decay ** i for i in range(n)]


def start_probability(started: list[bool], decay: float = PT_RECENCY_DECAY) -> float:
    """Recency-weighted fraction of recent team games the player started.

    `started[i]` is True iff he was in the lineup i games ago (0 = most recent).
    """
    if not started:
        return 0.0
    w = _weights(len(started), decay)
    return sum(wi * si for wi, si in zip(w, started)) / sum(w)


def _slot_pa_when_starting(
    slots_recent: list[int | None], decay: float
) -> tuple[float | None, float]:
    """(weighted expected slot, weighted E[PA]) over the games he actually started."""
    pairs = [(decay ** i, s) for i, s in enumerate(slots_recent) if s is not None]
    if not pairs:
        return None, EXPECTED_PA_PER_STARTER
    wsum = sum(w for w, _ in pairs)
    slot = sum(w * s for w, s in pairs) / wsum
    pa = sum(w * PA_BY_ORDER.get(s, EXPECTED_PA_PER_STARTER) for w, s in pairs) / wsum
    return slot, pa


def compute_playing_time(
    player_id: int, slots_recent: list[int | None], decay: float = PT_RECENCY_DECAY
) -> PlayingTime:
    """Build a PlayingTime from a player's recent slot sequence (0 = most recent game).

    `slots_recent[i]` = batting-order slot (1-9) i games ago, or None if he didn't start.
    """
    started = [s is not None for s in slots_recent]
    p_start = start_probability(started, decay)
    slot, pa_when_start = _slot_pa_when_starting(slots_recent, decay)
    return PlayingTime(
        player_id=player_id,
        p_start=round(p_start, 3),
        expected_slot=round(slot, 2) if slot is not None else None,
        expected_pa=round(p_start * pa_when_start, 2),
    )


def _load_recent_slots(
    conn: psycopg.Connection, team_id: int, as_of, window: int
) -> dict[int, list[int | None]]:
    """For each player who has appeared, his batting-order slot in the team's last
    `window` games before `as_of` (most-recent-first), None where he didn't start."""
    rows = conn.execute(
        """
        WITH recent_games AS (
            SELECT DISTINCT g.id, g.game_date, gl.is_home
            FROM game_lineups gl
            JOIN games g ON g.id = gl.game_id
            WHERE g.game_date < %(as_of)s
              AND ((g.home_team_id = %(team)s AND gl.is_home)
                   OR (g.away_team_id = %(team)s AND NOT gl.is_home))
            ORDER BY g.game_date DESC, g.id DESC  -- g.id tiebreak: deterministic for doubleheaders
            LIMIT %(window)s
        )
        SELECT rg.id, rg.game_date, gl.player_id, gl.batting_order
        FROM recent_games rg
        JOIN game_lineups gl ON gl.game_id = rg.id AND gl.is_home = rg.is_home
        ORDER BY rg.game_date DESC, rg.id DESC
        """,
        {"team": team_id, "as_of": as_of, "window": window},
    ).fetchall()

    # Establish the recent game order (most recent first) and each player's slot per game.
    game_order: list[int] = []
    seen: set[int] = set()
    by_game: dict[int, dict[int, int]] = {}
    for game_id, _date, player_id, slot in rows:
        if game_id not in seen:
            seen.add(game_id)
            game_order.append(game_id)
        by_game.setdefault(game_id, {})[int(player_id)] = int(slot)

    players = {pid for slots in by_game.values() for pid in slots}
    return {
        pid: [by_game[g].get(pid) for g in game_order]
        for pid in players
    }


def project_playing_time(
    conn: psycopg.Connection, team_id: int, as_of, window: int = PT_WINDOW,
    decay: float = PT_RECENCY_DECAY,
) -> dict[int, PlayingTime]:
    """Per-player PlayingTime for a team from recent lineup usage before `as_of`."""
    recent = _load_recent_slots(conn, team_id, as_of, window)
    return {pid: compute_playing_time(pid, slots, decay) for pid, slots in recent.items()}
