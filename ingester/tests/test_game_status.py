"""Game-status parsing used by the in-day status refresh (daily-slate + refresh-lineups).

A game postponed after the morning slate build must be detected from the schedule payload
the afternoon quick loop already fetches, so the projector skips it and its rows clear.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from ingester.commands.daily_slate import parse_schedule_status
from ingester.projection.constants import DEAD_GAME_STATUSES


def schedule_game(abstract: str, detailed: str | None) -> dict:
    return {
        "gamePk": 12345,
        "gameDate": "2026-06-21T17:10:00Z",
        "officialDate": "2026-06-21",
        "status": {"abstractGameState": abstract, "detailedState": detailed},
    }


class TestParseScheduleStatus(unittest.TestCase):
    def test_postponed_game(self):
        status, detailed, start = parse_schedule_status(
            schedule_game("Preview", "Postponed")
        )
        self.assertEqual(status, "Preview")
        self.assertEqual(detailed, "Postponed")
        self.assertEqual(start, datetime(2026, 6, 21, 17, 10, tzinfo=timezone.utc))
        # The detailedState is what the projector / board filters key off.
        self.assertIn(detailed, DEAD_GAME_STATUSES)

    def test_scheduled_game(self):
        status, detailed, _ = parse_schedule_status(
            schedule_game("Preview", "Scheduled")
        )
        self.assertEqual(status, "Preview")
        self.assertEqual(detailed, "Scheduled")
        self.assertNotIn(detailed, DEAD_GAME_STATUSES)

    def test_delayed_is_not_dead(self):
        # A short rain delay still plays — must NOT be treated as dead.
        _, detailed, _ = parse_schedule_status(schedule_game("Live", "Delayed"))
        self.assertNotIn(detailed, DEAD_GAME_STATUSES)

    def test_missing_status_defaults_scheduled(self):
        status, detailed, _ = parse_schedule_status(
            {"gamePk": 1, "gameDate": "2026-06-21T17:10:00Z", "status": {}}
        )
        self.assertEqual(status, "Scheduled")
        self.assertIsNone(detailed)


if __name__ == "__main__":
    unittest.main()
