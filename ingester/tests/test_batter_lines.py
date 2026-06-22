"""Unit test for the batter-lines boxscore parser (field mapping + PA gate)."""
from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from ingester.commands import backfill_batter_lines


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


# Minimal boxscore shape: one batter who played (away), one who didn't (home, PA=0),
# plus a pitcher line that must be ignored (no batting block).
_BOX = {
    "teams": {
        "home": {
            "players": {
                "ID1": {
                    "person": {"id": 111, "fullName": "Did Not Bat"},
                    "stats": {"batting": {"plateAppearances": 0}},
                },
                "IDP": {
                    "person": {"id": 222, "fullName": "Pitcher Only"},
                    "stats": {"pitching": {"outs": 18}},
                },
            }
        },
        "away": {
            "players": {
                "ID3": {
                    "person": {"id": 333, "fullName": "Sal Stewart"},
                    "stats": {"batting": {
                        "plateAppearances": 4, "atBats": 4, "hits": 2,
                        "homeRuns": 1, "totalBases": 5, "strikeOuts": 1,
                        "baseOnBalls": 0,
                    }},
                },
            }
        },
    }
}


class BatterLinesParseTest(unittest.TestCase):
    def test_maps_batting_fields_and_skips_zero_pa(self):
        game = (824908, date(2026, 6, 21), 10, 20)  # game_id, date, home_id, away_id
        with mock.patch.object(backfill_batter_lines.requests, "get",
                               return_value=_FakeResp(_BOX)):
            rows = backfill_batter_lines._fetch_batter_rows(game)

        # Only the away batter with PA > 0; the 0-PA batter and the pitcher are skipped.
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["player_id"], 333)
        self.assertEqual(r["game_id"], 824908)
        self.assertEqual(r["game_date"], date(2026, 6, 21))
        self.assertFalse(r["is_home"])          # away side
        self.assertEqual(r["opponent_team_id"], 10)  # away's opponent is home_id
        self.assertEqual(r["plate_appearances"], 4)
        self.assertEqual(r["at_bats"], 4)
        self.assertEqual(r["hits"], 2)
        self.assertEqual(r["home_runs"], 1)
        self.assertEqual(r["total_bases"], 5)
        self.assertEqual(r["strikeouts"], 1)
        self.assertEqual(r["walks"], 0)

    def test_bad_fetch_returns_empty(self):
        game = (1, date(2026, 6, 21), 10, 20)
        with mock.patch.object(backfill_batter_lines.requests, "get",
                               side_effect=RuntimeError("boom")):
            self.assertEqual(backfill_batter_lines._fetch_batter_rows(game), [])


if __name__ == "__main__":
    unittest.main()
