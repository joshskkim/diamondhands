"""daily-slate probable-pitcher persistence.

daily-slate is the only command that writes games.{home,away}_probable_pitcher_id, and the
afternoon quick loop re-runs it every 30 min. A transient schedule fetch that omits the
probable must NOT null out an already-stored one, or the projector would skip the game on
the next tick ("missing probable pitcher") — the exact failure that dropped late/West-Coast
games. The UPSERT guards this with COALESCE(EXCLUDED.…, games.…).
"""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from ingester.commands import daily_slate
from ingester.commands.daily_slate import cmd_daily_slate

HOME_TEAM_ID = 147
AWAY_TEAM_ID = 111
STADIUM_ID = 3313


def schedule_game(*, with_probables: bool) -> dict:
    """A minimal regular-season schedule game; probables present or omitted."""
    home: dict = {"team": {"id": HOME_TEAM_ID}}
    away: dict = {"team": {"id": AWAY_TEAM_ID}}
    if with_probables:
        home["probablePitcher"] = {"id": 605483, "fullName": "Home Ace"}
        away["probablePitcher"] = {"id": 592789, "fullName": "Away Ace"}
    return {
        "gamePk": 778899,
        "gameType": "R",
        "gameDate": "2026-06-27T23:10:00Z",
        "officialDate": "2026-06-27",
        "status": {"abstractGameState": "Preview", "detailedState": "Scheduled"},
        "teams": {"home": home, "away": away},
    }


class _FakeConn:
    """Records the games UPSERT (sql, params); answers the teams→stadium SELECT."""

    def __init__(self) -> None:
        self.game_upserts: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        if "home_stadium_id" in sql:  # team_to_stadium lookup
            return mock.Mock(fetchall=lambda: [(HOME_TEAM_ID, STADIUM_ID)])
        if "INSERT INTO games" in sql:
            self.game_upserts.append((sql, params))
        return mock.Mock()  # players insert / anything else — result unused

    def commit(self) -> None:  # pragma: no cover - trivial
        pass

    def close(self) -> None:  # pragma: no cover - trivial
        pass


def _run_slate(*, with_probables: bool) -> _FakeConn:
    conn = _FakeConn()
    args = mock.Mock(date=date(2026, 6, 27))
    with mock.patch.object(
        daily_slate, "fetch_schedule",
        return_value=[schedule_game(with_probables=with_probables)],
    ), mock.patch.object(
        daily_slate, "get_connection", return_value=conn,
    ), mock.patch.object(
        # Season-role fetch hits the network; not under test here.
        daily_slate, "fetch_pitcher_season_stats", return_value=None,
    ):
        cmd_daily_slate(args)
    return conn


class TestDailySlateProbablePersistence(unittest.TestCase):
    def test_present_probables_are_passed_to_upsert(self):
        conn = _run_slate(with_probables=True)
        self.assertEqual(len(conn.game_upserts), 1)
        _, params = conn.game_upserts[0]
        # params tail: (..., home_probable_pitcher_id, away_probable_pitcher_id)
        self.assertEqual(params[-2], 605483)
        self.assertEqual(params[-1], 592789)

    def test_missing_probable_forwards_null_and_upsert_coalesces(self):
        conn = _run_slate(with_probables=False)
        self.assertEqual(len(conn.game_upserts), 1)
        sql, params = conn.game_upserts[0]
        # A fetch without probables forwards NULL params...
        self.assertIsNone(params[-2])
        self.assertIsNone(params[-1])
        # ...and the UPSERT keeps any already-stored probable rather than nulling it,
        # so a flaky tick can't un-project a late game.
        self.assertIn(
            "home_probable_pitcher_id = COALESCE(EXCLUDED.home_probable_pitcher_id,", sql
        )
        self.assertIn(
            "away_probable_pitcher_id = COALESCE(EXCLUDED.away_probable_pitcher_id,", sql
        )


if __name__ == "__main__":
    unittest.main()
