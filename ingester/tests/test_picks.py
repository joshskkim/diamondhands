"""Unit tests for Model's Picks recording/scoring + the degeneracy guard."""
from __future__ import annotations

import unittest

from ingester.commands.picks import MAX_PICKS, _devig_two_way, _grade, build_picks
from ingester.projection.runner import DEGENERACY_MIN_ROWS, is_degenerate_slate


def play(game_id=1, market="hr", side="over", line=0.5, model=0.60, fair=0.50,
         ev=0.10, player_id=10, name="A B"):
    return {
        "gameId": game_id, "market": market, "side": side, "line": line,
        "modelProb": model, "fairProb": fair, "evPct": ev,
        "playerId": player_id, "playerName": name, "matchup": "AWY @ HOM",
        "priceAmerican": -110, "bestBook": "betrivers",
    }


class TestBuildPicks(unittest.TestCase):
    def test_bar_filters(self):
        plays = [
            play(game_id=1, model=0.60, fair=0.50, ev=0.10),       # qualifies
            play(game_id=2, model=0.52, fair=0.50, ev=0.10),       # edge 2pt < 4pt
            play(game_id=3, model=0.73, fair=0.55, ev=0.30),       # edge 18pt > 15pt cap
            play(game_id=4, model=0.60, fair=0.50, ev=0.02),       # EV < 5%
            play(game_id=5, market="pitcher_k", model=0.7, fair=0.5, ev=0.2),  # excluded
            play(game_id=6, model=0.35, fair=0.30, ev=0.10),       # longshot, edge 5 < 8
            {**play(game_id=7), "fairProb": None},                  # one-sided, no de-vig
            play(game_id=8, market="hit", model=0.60, fair=0.50, ev=0.10),  # hit excluded (interim)
        ]
        picks = build_picks(plays, sim=None)
        self.assertEqual([p["gameId"] for p in picks], [1])

    def test_hit_rate_veto(self):
        # Bands are PER MARKET: hr uses (0.08, 0.50), not the hit bands — a normal
        # slugger's ~25% HR clear-rate must NOT veto an over (the original single-
        # threshold veto would have banned every HR over on the board).
        over = play(game_id=1, side="over", model=0.60, fair=0.50, ev=0.10)
        under = play(game_id=2, side="under", model=0.60, fair=0.50, ev=0.10)
        slugger = {"10:hr": {"season": 0.26, "nSeason": 40}}   # normal slugger → fine
        red = {"10:hr": {"season": 0.05, "nSeason": 40}}       # never homers → veto over
        green = {"10:hr": {"season": 0.55, "nSeason": 40}}     # >0.50 → veto under
        thin = {"10:hr": {"season": 0.05, "nSeason": 5}}       # below MIN_N → no veto

        self.assertEqual(len(build_picks([over], None, slugger)), 1)
        self.assertEqual(build_picks([over], None, red), [])
        self.assertEqual(build_picks([under], None, green), [])
        self.assertEqual(len(build_picks([over], None, thin)), 1)
        self.assertEqual(len(build_picks([over], None, None)), 1)  # no data → no veto
        # Unbanded market (total) never vetoes regardless of rates.
        total = play(game_id=3, market="total", side="under", line=9.0,
                     model=0.60, fair=0.50, ev=0.10, player_id=None, name=None)
        self.assertEqual(len(build_picks([total], None, red)), 1)

    def test_one_per_game_and_max(self):
        plays = [play(game_id=g, model=0.60 + g * 0.001, fair=0.50, ev=0.10,
                      player_id=g) for g in range(1, 6)]
        plays.append(play(game_id=1, model=0.70, fair=0.55, ev=0.20, player_id=99))
        picks = build_picks(plays, sim=None)
        self.assertEqual(len(picks), MAX_PICKS)
        self.assertEqual(len({p["gameId"] for p in picks}), MAX_PICKS)

    def test_sim_totals_veto(self):
        total = play(game_id=1, market="total", side="under", line=9.0,
                     model=0.62, fair=0.50, ev=0.15, player_id=None, name=None)
        sim_against = {"totals": [{"gameId": 1, "simTotal": 9.8}], "props": {}}
        sim_with = {"totals": [{"gameId": 1, "simTotal": 8.1}], "props": {}}
        self.assertEqual(build_picks([total], sim_against), [])
        self.assertEqual(len(build_picks([total], sim_with)), 1)


class TestGrade(unittest.TestCase):
    def test_total(self):
        self.assertEqual(_grade("total", "under", 9.0, 6, 4, None), (10.0, False))
        self.assertEqual(_grade("total", "under", 9.0, 4, 4, None), (8.0, True))
        self.assertEqual(_grade("total", "over", 9.0, 5, 4, None), (9.0, None))  # push

    def test_moneyline_and_run_line(self):
        self.assertEqual(_grade("moneyline", "away", None, 3, 4, None), (1.0, True))
        # home -1.5 covers only on a 2+ run win
        self.assertEqual(_grade("run_line", "home", -1.5, 5, 3, None)[1], True)
        self.assertEqual(_grade("run_line", "home", -1.5, 4, 3, None)[1], False)
        # away +1.5 covers a 1-run loss
        self.assertEqual(_grade("run_line", "away", 1.5, 4, 3, None)[1], True)

    def test_props(self):
        self.assertEqual(_grade("hit", "under", 1.5, 0, 0, 2), (2.0, False))
        self.assertEqual(_grade("hr", "over", 0.5, 0, 0, 1), (1.0, True))
        self.assertEqual(_grade("hit", "over", 0.5, 0, 0, None), (None, None))


class TestDevigForClv(unittest.TestCase):
    def test_balanced_book_is_half(self):
        # Both sides -110 (decimal 1.909): a fair coin after stripping vig.
        fair = _devig_two_way(1.909, 1.909)
        self.assertAlmostEqual(fair, 0.5, places=4)

    def test_favorite_above_half(self):
        # -200 (1.5) vs +170 (2.7): the favorite's fair prob exceeds 0.5.
        fair = _devig_two_way(1.5, 2.7)
        self.assertGreater(fair, 0.5)
        # implied 0.6667 / (0.6667 + 0.3704) ≈ 0.643
        self.assertAlmostEqual(fair, 0.6428, places=3)

    def test_two_sides_sum_to_one(self):
        side = _devig_two_way(1.8, 2.1)
        opp = _devig_two_way(2.1, 1.8)
        self.assertAlmostEqual(side + opp, 1.0, places=6)

    def test_nonpositive_returns_none(self):
        self.assertIsNone(_devig_two_way(0.0, 1.9))
        self.assertIsNone(_devig_two_way(1.9, -1.0))


class TestDegeneracyGuard(unittest.TestCase):
    def test_thresholds(self):
        # Yesterday's actual blend slate: 72 of 267 on one value → degenerate.
        self.assertTrue(is_degenerate_slate(267, 72))
        # A healthy mechanistic slate: top duplicate is a handful of rows.
        self.assertFalse(is_degenerate_slate(267, 9))
        # Small slates are never judged.
        self.assertFalse(is_degenerate_slate(DEGENERACY_MIN_ROWS - 1, 40))


if __name__ == "__main__":
    unittest.main()
