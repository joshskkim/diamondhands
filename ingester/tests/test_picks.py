"""Unit tests for Model's Picks recording/scoring + the degeneracy guard."""
from __future__ import annotations

import unittest

from ingester.commands.picks import (
    MAX_PICKS,
    _grade,
    _pick_key,
    build_lotto,
    build_picks,
)
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

    def test_strong_uses_proportional_overlay(self):
        # Strong is conviction in the value (overlay = model/fair), not absolute
        # likelihood — so the old modelProb>=0.5 floor is gone.
        # A bare ~6pt total hugs the coinflip → overlay 1.12 < 1.15 → only a Lean.
        bare_total = play(game_id=1, market="total", side="over", line=8.5,
                          model=0.56, fair=0.50, ev=0.10, player_id=None, name=None)
        self.assertFalse(build_picks([bare_total], None)[0]["strong"])
        # The same total with a wider edge clears the overlay → Strong.
        big_total = play(game_id=2, market="total", side="over", line=8.5,
                         model=0.58, fair=0.50, ev=0.10, player_id=None, name=None)
        self.assertTrue(build_picks([big_total], None)[0]["strong"])
        # A longshot HR over that roughly doubles the fair price is a genuine value
        # conviction → Strong, even though its absolute prob is well under 0.5.
        hr_over = play(game_id=3, market="hr", side="over", model=0.15, fair=0.06, ev=0.20)
        self.assertTrue(build_picks([hr_over], None)[0]["strong"])


class TestBuildLotto(unittest.TestCase):
    def test_region_and_max_ev(self):
        # In-region longshot the model likes: prob 0.15 (≤0.30), EV 0.30, edge 0.07.
        good = play(game_id=1, market="hr", side="over", model=0.15, fair=0.08, ev=0.30)
        # A higher-EV in-region longshot should win the max-EV tiebreak.
        better = play(game_id=2, market="hr", side="over", model=0.18, fair=0.10,
                      ev=0.45, player_id=20)
        lotto = build_lotto([good, better])
        self.assertIsNotNone(lotto)
        self.assertEqual(lotto["gameId"], 2)
        self.assertTrue(lotto["lotto"])
        self.assertFalse(lotto["strong"])

    def test_favorite_excluded(self):
        # High EV but a favorite (prob > 0.30) is not a lotto — that's the board's job.
        fav = play(game_id=1, market="total", side="over", line=8.5,
                   model=0.62, fair=0.50, ev=0.30, player_id=None, name=None)
        self.assertIsNone(build_lotto([fav]))

    def test_value_and_edge_gates(self):
        low_ev = play(game_id=1, market="hr", model=0.15, fair=0.10, ev=0.10)  # EV < 0.20
        thin_edge = play(game_id=2, market="hr", model=0.12, fair=0.10, ev=0.30)  # edge < 0.03
        phantom = play(game_id=3, market="hr", model=0.02, fair=0.005, ev=0.30)  # prob < 0.05
        self.assertIsNone(build_lotto([low_ev]))
        self.assertIsNone(build_lotto([thin_edge]))
        self.assertIsNone(build_lotto([phantom]))

    def test_hit_rate_veto_and_exclusion(self):
        over = play(game_id=1, market="hr", side="over", model=0.15, fair=0.08, ev=0.30)
        red = {"10:hr": {"season": 0.05, "nSeason": 40}}  # never homers → veto over
        self.assertIsNone(build_lotto([over], red))
        # A selection already on the disciplined board is skipped.
        self.assertIsNone(build_lotto([over], None, {_pick_key(over)}))
        self.assertIsNotNone(build_lotto([over], None, set()))


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
