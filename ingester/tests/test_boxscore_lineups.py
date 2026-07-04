"""Boxscore battingOrder fallback for confirmed-lineup ingest.

refresh-lineups populates game_lineups (which clears the projector's nine-man gate,
runner._any_lineup_posted). Its primary source is the schedule 'lineups' hydration, which
lags pre-game and strands late games. When a side is missing there, _process_date backfills
it from the boxscore battingOrder — the earlier/more-reliable source — but only pre-game and
near first pitch, so the historical backfill (Final games) never fires a per-game boxscore call.
"""
from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from ingester.commands import lineups
from ingester.commands.lineups import _process_date
from ingester.mlb_api import fetch_boxscore_batting_orders

GAME_PK = 778899


def _boxscore(home_n: int, away_n: int) -> dict:
    """A boxscore payload with `home_n`/`away_n` batters in each battingOrder."""
    def side(prefix: str, n: int) -> dict:
        order = [int(f"{prefix}{i:02d}") for i in range(1, n + 1)]
        players = {f"ID{pid}": {"person": {"fullName": f"{prefix}-{pid}"}} for pid in order}
        return {"battingOrder": order, "players": players}
    return {"teams": {"home": side("1", home_n), "away": side("2", away_n)}}


def _schedule_players(prefix: str, n: int) -> list[dict]:
    return [{"id": int(f"{prefix}{i:02d}"), "fullName": f"{prefix}-{i}"} for i in range(1, n + 1)]


def _schedule_game(*, home_n: int, away_n: int, state: str, hours_out: float = 2.0) -> dict:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_out)
    return {
        "gamePk": GAME_PK,
        "gameType": "R",
        "gameDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "officialDate": "2026-07-02",
        "status": {"abstractGameState": state, "detailedState": "Scheduled"},
        "lineups": {
            "homePlayers": _schedule_players("1", home_n),
            "awayPlayers": _schedule_players("2", away_n),
        },
    }


class _FakeConn:
    """Records game_lineups inserts + which sides got a confirmed_at stamp."""

    def __init__(self) -> None:
        self.lineup_inserts: list[tuple] = []
        self.confirmed: set[str] = set()

    def execute(self, sql, params=None):
        if "SELECT id FROM games WHERE game_date" in sql:
            return mock.Mock(fetchall=lambda: [(GAME_PK,)])
        if "INSERT INTO game_lineups" in sql:
            self.lineup_inserts.append(params)
        elif "home_lineup_confirmed_at" in sql:
            self.confirmed.add("home")
        elif "away_lineup_confirmed_at" in sql:
            self.confirmed.add("away")
        return mock.Mock()

    def commit(self) -> None:  # pragma: no cover - trivial
        pass

    def close(self) -> None:  # pragma: no cover - trivial
        pass


class TestFetchBoxscoreBattingOrders(unittest.TestCase):
    def _get(self, payload):
        resp = mock.Mock()
        resp.json.return_value = payload
        resp.raise_for_status = lambda: None
        return resp

    def test_full_nine_both_sides(self):
        with mock.patch("ingester.mlb_api.requests.get", return_value=self._get(_boxscore(9, 9))):
            out = fetch_boxscore_batting_orders(GAME_PK)
        self.assertEqual(set(out), {True, False})
        self.assertEqual(len(out[True]), 9)
        self.assertEqual(out[True][0], (101, "1-101"))

    def test_short_side_omitted(self):
        with mock.patch("ingester.mlb_api.requests.get", return_value=self._get(_boxscore(9, 5))):
            out = fetch_boxscore_batting_orders(GAME_PK)
        self.assertEqual(set(out), {True})  # away had only 5 → dropped

    def test_network_error_returns_empty(self):
        with mock.patch("ingester.mlb_api.requests.get", side_effect=RuntimeError("boom")):
            self.assertEqual(fetch_boxscore_batting_orders(GAME_PK), {})


class TestProcessDateFallback(unittest.TestCase):
    def test_missing_side_backfilled_from_boxscore(self):
        # Schedule posted only the home nine; away is empty (the lagging-hydration case).
        g = _schedule_game(home_n=9, away_n=0, state="Preview")
        conn = _FakeConn()
        with mock.patch.object(
            lineups, "fetch_boxscore_batting_orders",
            return_value={False: [(int(f"2{i:02d}"), f"2-{i}") for i in range(1, 10)]},
        ) as box:
            sides, games, via_sched, via_box = _process_date(conn, date(2026, 7, 2), [g])
        box.assert_called_once_with(GAME_PK)
        self.assertEqual((sides, games, via_sched, via_box), (2, 1, 1, 1))
        self.assertEqual(len(conn.lineup_inserts), 18)  # 9 home + 9 away
        self.assertEqual(conn.confirmed, {"home", "away"})

    def test_no_boxscore_call_for_final_game(self):
        # Backfill protection: a Final game with an empty schedule side must NOT hit the
        # per-game boxscore endpoint (would be a request per historical game).
        g = _schedule_game(home_n=0, away_n=0, state="Final")
        conn = _FakeConn()
        with mock.patch.object(lineups, "fetch_boxscore_batting_orders") as box:
            sides, games, via_sched, via_box = _process_date(conn, date(2026, 7, 2), [g])
        box.assert_not_called()
        self.assertEqual((sides, games, via_sched, via_box), (0, 0, 0, 0))

    def test_schedule_side_not_overwritten_by_fallback(self):
        # Home posted on the schedule; only the missing away is sourced from the boxscore.
        g = _schedule_game(home_n=9, away_n=0, state="Preview")
        conn = _FakeConn()
        with mock.patch.object(
            lineups, "fetch_boxscore_batting_orders",
            return_value={True: [(999, "SHOULD-NOT-USE")] * 9,
                          False: [(int(f"2{i:02d}"), f"2-{i}") for i in range(1, 10)]},
        ):
            _process_date(conn, date(2026, 7, 2), [g])
        # Home batting_order slot 1 must be the schedule's player 101, not the boxscore's 999.
        home_slot1 = next(p for p in conn.lineup_inserts if p[1] is True and p[2] == 1)
        self.assertEqual(home_slot1[3], 101)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
