"""Live linescore parsing used by `live-refresh` to write games.live_* mid-game.

Unlike parse_game_score, this returns the running state for in-progress games (and does
NOT gate on Final), so the home board can track a game while it's being played.
"""
from __future__ import annotations

import unittest

from ingester.commands.live import _box_player_rows, _live_game_tuples, _update_live
from ingester.mlb_api import parse_game_linescore_live


def live_game(abstract: str, linescore: dict | None) -> dict:
    g = {"gamePk": 777, "status": {"abstractGameState": abstract}}
    if linescore is not None:
        g["linescore"] = linescore
    return g


def linescore(home: int | None, away: int | None, inning=5, state="Top", is_top=True) -> dict:
    return {
        "currentInning": inning,
        "inningState": state,
        "isTopInning": is_top,
        "teams": {"home": {"runs": home}, "away": {"runs": away}},
    }


class TestParseGameLinescoreLive(unittest.TestCase):
    def test_in_progress_returns_running_state(self):
        live = parse_game_linescore_live(
            live_game("Live", linescore(3, 2, inning=6, state="Bottom", is_top=False))
        )
        self.assertEqual(
            live,
            {"home": 3, "away": 2, "inning": 6, "inning_state": "Bottom", "is_top": False},
        )

    def test_final_still_returns_running_total(self):
        # Final games carry the final running total in the linescore; grading uses the
        # Final score columns, but the live read shouldn't error or drop it.
        live = parse_game_linescore_live(live_game("Final", linescore(5, 4)))
        self.assertIsNotNone(live)
        self.assertEqual(live["home"], 5)
        self.assertEqual(live["away"], 4)

    def test_scheduled_returns_none(self):
        self.assertIsNone(parse_game_linescore_live(live_game("Scheduled", None)))
        self.assertIsNone(parse_game_linescore_live(live_game("Preview", linescore(0, 0))))

    def test_missing_runs_returns_none(self):
        # Top of the 1st before any score posts — runs are None, nothing to write yet.
        self.assertIsNone(
            parse_game_linescore_live(live_game("Live", linescore(None, None)))
        )

    def test_no_linescore_returns_none(self):
        self.assertIsNone(parse_game_linescore_live(live_game("Live", None)))


class TestBoxPlayerRows(unittest.TestCase):
    def _box(self):
        return {
            "teams": {
                "home": {
                    "players": {
                        "ID1": {  # batter mid-game
                            "person": {"id": 101},
                            "stats": {"batting": {
                                "plateAppearances": 3, "atBats": 3, "hits": 2,
                                "homeRuns": 1, "totalBases": 5, "strikeOuts": 1,
                                "baseOnBalls": 0,
                            }},
                        },
                        "ID2": {  # starter mid-game
                            "person": {"id": 201},
                            "stats": {"pitching": {
                                "gamesStarted": 1, "outs": 15, "battersFaced": 20,
                                "strikeOuts": 7, "hits": 4, "earnedRuns": 2,
                            }},
                        },
                    }
                },
                "away": {
                    "players": {
                        "ID3": {  # reliever — not a starter, skipped
                            "person": {"id": 301},
                            "stats": {"pitching": {"gamesStarted": 0, "outs": 3}},
                        },
                        "ID4": {  # batter who hasn't come up — no PA, skipped
                            "person": {"id": 401},
                            "stats": {"batting": {"plateAppearances": 0}},
                        },
                    }
                },
            }
        }

    def test_extracts_batters_and_starters(self):
        batters, pitchers = _box_player_rows(self._box(), 555, "2026-06-28")
        self.assertEqual([b["player_id"] for b in batters], [101])
        self.assertEqual(batters[0]["hits"], 2)
        self.assertEqual(batters[0]["home_runs"], 1)
        self.assertEqual([p["player_id"] for p in pitchers], [201])
        self.assertEqual(pitchers[0]["outs"], 15)
        self.assertEqual(pitchers[0]["pitcher_strikeouts"], 7)
        self.assertEqual(pitchers[0]["earned_runs"], 2)

    def test_skips_relievers_and_no_pa_batters(self):
        batters, pitchers = _box_player_rows(self._box(), 555, "2026-06-28")
        ids = {b["player_id"] for b in batters} | {p["player_id"] for p in pitchers}
        self.assertNotIn(301, ids)  # reliever
        self.assertNotIn(401, ids)  # no plate appearance yet


class TestLiveGameTuples(unittest.TestCase):
    def test_only_in_progress_games(self):
        games = [
            {  # live
                "gamePk": 1, "officialDate": "2026-06-28",
                "status": {"abstractGameState": "Live"},
                "linescore": {"currentInning": 5, "teams": {"home": {"runs": 1}, "away": {"runs": 2}}},
                "teams": {"home": {"team": {"id": 10}}, "away": {"team": {"id": 20}}},
            },
            {  # final — excluded (handled by the live-state pass)
                "gamePk": 2, "officialDate": "2026-06-28",
                "status": {"abstractGameState": "Final"},
                "linescore": {"teams": {"home": {"runs": 3}, "away": {"runs": 1}}},
                "teams": {
                    "home": {"team": {"id": 11}, "score": 3},
                    "away": {"team": {"id": 21}, "score": 1},
                },
            },
            {  # scheduled — excluded
                "gamePk": 3, "officialDate": "2026-06-28",
                "status": {"abstractGameState": "Preview"},
                "teams": {"home": {"team": {"id": 12}}, "away": {"team": {"id": 22}}},
            },
        ]
        tuples = _live_game_tuples(games)
        self.assertEqual(tuples, [(1, "2026-06-28", 10, 20)])


class _FakeResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeConn:
    """Captures execute(sql, params) calls so we can assert on the UPDATE payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> _FakeResult:
        self.calls.append((sql, params))
        return _FakeResult(1)


def _live_raw(inning: int, first_home, first_away, run_home=3, run_away=2) -> dict:
    """A live game whose linescore carries the running total, current inning, and per-inning
    runs (innings[0] drives first-inning persistence)."""
    innings = [{"num": 1, "home": {"runs": first_home}, "away": {"runs": first_away}}]
    return {
        "gamePk": 777,
        "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
        "linescore": {
            "currentInning": inning,
            "inningState": "Top",
            "isTopInning": True,
            "teams": {"home": {"runs": run_home}, "away": {"runs": run_away}},
            "innings": innings,
        },
    }


class TestUpdateLiveFirstInning(unittest.TestCase):
    def test_persists_first_inning_runs_once_the_1st_completes(self):
        conn = _FakeConn()
        _update_live(conn, [_live_raw(inning=6, first_home=1, first_away=0)])
        self.assertEqual(len(conn.calls), 1)
        sql, params = conn.calls[0]
        self.assertIn("home_score_1st = COALESCE", sql)
        self.assertIn("away_score_1st = COALESCE", sql)
        # params: (status, home, away, inning, inning_state, is_top, home_1st, away_1st, game_pk)
        self.assertEqual(params[6], 1)
        self.assertEqual(params[7], 0)
        self.assertEqual(params[-1], 777)

    def test_no_first_inning_runs_while_1st_still_in_progress(self):
        # Top of the 1st: home half not played yet (runs None) → pass None so COALESCE keeps
        # whatever's already stored instead of clobbering it.
        conn = _FakeConn()
        _update_live(conn, [_live_raw(inning=1, first_home=None, first_away=None)])
        _, params = conn.calls[0]
        self.assertIsNone(params[6])
        self.assertIsNone(params[7])


if __name__ == "__main__":
    unittest.main()
