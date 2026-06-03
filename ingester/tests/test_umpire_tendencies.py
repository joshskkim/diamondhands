"""Unit tests for umpire tendency aggregation (synthetic data, no network/DB)."""
from __future__ import annotations

import unittest

from ingester.commands.refresh_umpires import (
    MIN_GAMES_SAMPLED,
    compute_umpire_tendencies,
    parse_home_plate_umpire,
)


class TestComputeTendencies(unittest.TestCase):
    def test_qualified_umpire_gets_tendencies(self):
        # A pitcher-friendly ump: high K rate, low scoring, well over the games guard.
        rows = [
            {
                "umpire_id": 1,
                "full_name": "Strict Zone",
                "games": 30,
                "total_pa": 2400,   # 80 PA/game
                "total_k": 600,     # 25% K rate (above the 22% league avg below)
                "total_runs": 240,  # 8.0 runs/game (below 8.8 league avg)
            }
        ]
        out = compute_umpire_tendencies(rows, league_k_rate=0.22, league_runs_per_game=8.8)
        self.assertEqual(len(out), 1)
        u = out[0]
        self.assertEqual(u["games_sampled"], 30)
        self.assertAlmostEqual(u["k_rate_tendency"], 0.25, places=4)
        self.assertAlmostEqual(u["runs_above_avg"], 8.0 - 8.8, places=3)
        # Sanity bounds: K rate near league ~0.22, runs delta small.
        self.assertTrue(0.10 <= u["k_rate_tendency"] <= 0.35)
        self.assertTrue(-3.0 <= u["runs_above_avg"] <= 3.0)

    def test_hitter_friendly_ump_positive_runs(self):
        rows = [
            {
                "umpire_id": 2,
                "full_name": "Wide Zone",
                "games": 25,
                "total_pa": 2000,
                "total_k": 360,     # 18% K rate (below league)
                "total_runs": 245,  # 9.8 runs/game (above league)
            }
        ]
        out = compute_umpire_tendencies(rows, league_k_rate=0.22, league_runs_per_game=8.8)
        u = out[0]
        self.assertLess(u["k_rate_tendency"], 0.22)
        self.assertGreater(u["runs_above_avg"], 0.0)

    def test_below_min_games_is_neutral_null(self):
        rows = [
            {
                "umpire_id": 3,
                "full_name": "Rookie Ump",
                "games": MIN_GAMES_SAMPLED - 1,
                "total_pa": 500,
                "total_k": 200,     # extreme rate, but should NOT be trusted
                "total_runs": 200,
            }
        ]
        out = compute_umpire_tendencies(rows, league_k_rate=0.22, league_runs_per_game=8.8)
        u = out[0]
        self.assertEqual(u["games_sampled"], MIN_GAMES_SAMPLED - 1)
        self.assertIsNone(u["k_rate_tendency"])
        self.assertIsNone(u["runs_above_avg"])

    def test_exactly_min_games_qualifies(self):
        rows = [
            {
                "umpire_id": 4,
                "full_name": "Boundary Ump",
                "games": MIN_GAMES_SAMPLED,
                "total_pa": 1600,
                "total_k": 352,
                "total_runs": 140,
            }
        ]
        out = compute_umpire_tendencies(rows, league_k_rate=0.22, league_runs_per_game=8.8)
        self.assertIsNotNone(out[0]["k_rate_tendency"])

    def test_zero_pa_is_neutral_even_if_games_high(self):
        # Games present but no batter rows -> can't compute a K rate; stay neutral.
        rows = [
            {
                "umpire_id": 5,
                "full_name": "No PA Ump",
                "games": 40,
                "total_pa": 0,
                "total_k": 0,
                "total_runs": 320,
            }
        ]
        out = compute_umpire_tendencies(rows, league_k_rate=0.22, league_runs_per_game=8.8)
        self.assertIsNone(out[0]["k_rate_tendency"])
        self.assertIsNone(out[0]["runs_above_avg"])

    def test_custom_min_games_override(self):
        rows = [{"umpire_id": 6, "full_name": "X", "games": 5,
                 "total_pa": 400, "total_k": 80, "total_runs": 40}]
        out = compute_umpire_tendencies(rows, 0.22, 8.8, min_games=5)
        self.assertIsNotNone(out[0]["k_rate_tendency"])


class TestParseHomePlateUmpire(unittest.TestCase):
    def test_extracts_home_plate(self):
        game = {
            "officials": [
                {"official": {"id": 427113, "fullName": "Laz Diaz"}, "officialType": "First Base"},
                {"official": {"id": 482631, "fullName": "Mike Estabrook"}, "officialType": "Home Plate"},
                {"official": {"id": 623938, "fullName": "Erich Bacchus"}, "officialType": "Second Base"},
            ]
        }
        self.assertEqual(parse_home_plate_umpire(game), (482631, "Mike Estabrook"))

    def test_missing_officials_returns_none(self):
        self.assertIsNone(parse_home_plate_umpire({}))
        self.assertIsNone(parse_home_plate_umpire({"officials": []}))

    def test_no_home_plate_among_officials(self):
        game = {"officials": [{"official": {"id": 1, "fullName": "X"}, "officialType": "First Base"}]}
        self.assertIsNone(parse_home_plate_umpire(game))

    def test_missing_id_returns_none(self):
        game = {"officials": [{"official": {"fullName": "No Id"}, "officialType": "Home Plate"}]}
        self.assertIsNone(parse_home_plate_umpire(game))


if __name__ == "__main__":
    unittest.main()
