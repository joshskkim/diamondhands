"""Live linescore parsing used by `live-refresh` to write games.live_* mid-game.

Unlike parse_game_score, this returns the running state for in-progress games (and does
NOT gate on Final), so the home board can track a game while it's being played.
"""
from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
