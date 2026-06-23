"""Unit tests for sim-native correlation / SGP pricing (ingester.projection.sgp).

Uses hand-crafted per-sim arrays so the joint, correlation, and lift are exact and
independent of the RNG.
"""
from __future__ import annotations

import math
import unittest

import numpy as np

from ingester.projection.game_sim import GameSim, PeriodMarket, TeamSim
from ingester.projection.sgp import (
    Leg,
    correlation,
    independent_prob,
    joint_prob,
    leg_mask,
    marginal,
    price_sgp,
)


def _team(slot_hits, slot_hr=None, slot_k=None, period_runs=None) -> TeamSim:
    n = slot_hits.shape[0]
    z = np.zeros((n, 9), dtype=np.int32)
    return TeamSim(
        runs=np.zeros(n, dtype=np.int32),
        period_runs=period_runs or {},
        slot_hits=slot_hits,
        slot_hr=slot_hr if slot_hr is not None else z.copy(),
        slot_tb=z.copy(),
        slot_k=slot_k if slot_k is not None else z.copy(),
        starter_hits=np.zeros(n, dtype=np.int32),
        starter_runs=np.zeros(n, dtype=np.int32),
    )


def _sim() -> GameSim:
    """4-sim game. Home slot 0 gets 2 hits in sims 0,1 and 0 hits in sims 2,3.
    Home scores 5,5,1,1; away scores 0,0,0,0 → total 5,5,1,1.
    So 'home slot0 2+ hits' and 'total over 3.5' are perfectly aligned."""
    home_hits = np.zeros((4, 9), dtype=np.int32)
    home_hits[:, 0] = [2, 2, 0, 0]
    home_hr = np.zeros((4, 9), dtype=np.int32)
    home_hr[:, 0] = [1, 0, 0, 0]            # slot0 HR only in sim 0
    home_runs = np.array([5, 5, 1, 1], dtype=np.int32)
    away_runs = np.array([0, 0, 0, 0], dtype=np.int32)
    home = _team(home_hits, slot_hr=home_hr, period_runs={9: home_runs, 5: home_runs})
    away = _team(np.zeros((4, 9), dtype=np.int32), period_runs={9: away_runs, 5: away_runs})
    periods = {
        9: PeriodMarket(9, home_runs, away_runs),
        5: PeriodMarket(5, home_runs, away_runs),
    }
    return GameSim(n_sims=4, periods=periods, home_props=[], away_props=[],
                   home_pitcher_props=None, away_pitcher_props=None, home=home, away=away)


class TestLegMask(unittest.TestCase):
    def test_batter_hit2plus(self):
        m = leg_mask(_sim(), Leg("batter", "over", team="home", slot=0, market="hit2plus"))
        self.assertEqual(m.tolist(), [True, True, False, False])

    def test_batter_under_negates(self):
        m = leg_mask(_sim(), Leg("batter", "under", team="home", slot=0, market="hit1plus"))
        self.assertEqual(m.tolist(), [False, False, True, True])

    def test_total_over(self):
        m = leg_mask(_sim(), Leg("total", "over", line=3.5))
        self.assertEqual(m.tolist(), [True, True, False, False])

    def test_team_total_and_moneyline(self):
        s = _sim()
        self.assertEqual(leg_mask(s, Leg("team_total", "over", team="home", line=2.5)).tolist(),
                         [True, True, False, False])
        # home always outscores away here
        self.assertTrue(leg_mask(s, Leg("moneyline", team="home")).all())

    def test_missing_arrays_raises(self):
        s = _sim()
        s.away = None
        with self.assertRaises(ValueError):
            leg_mask(s, Leg("batter", "over", team="away", slot=0, market="hr"))


class TestJointAndCorrelation(unittest.TestCase):
    def test_perfectly_correlated_joint_beats_independence(self):
        s = _sim()
        a = Leg("batter", "over", team="home", slot=0, market="hit2plus")  # marginal 0.5
        b = Leg("total", "over", line=3.5)                                 # marginal 0.5
        self.assertAlmostEqual(marginal(s, a), 0.5)
        self.assertAlmostEqual(marginal(s, b), 0.5)
        self.assertAlmostEqual(joint_prob(s, [a, b]), 0.5)        # they always co-occur
        self.assertAlmostEqual(independent_prob(s, [a, b]), 0.25)  # 0.5 * 0.5
        self.assertAlmostEqual(correlation(s, a, b), 1.0)

    def test_negative_correlation(self):
        s = _sim()
        a = Leg("batter", "over", team="home", slot=0, market="hit2plus")  # T,T,F,F
        b = Leg("total", "under", line=3.5)                                # F,F,T,T
        self.assertAlmostEqual(joint_prob(s, [a, b]), 0.0)
        self.assertAlmostEqual(correlation(s, a, b), -1.0)

    def test_empty_joint_is_nan(self):
        self.assertTrue(math.isnan(joint_prob(_sim(), [])))


class TestPriceSgp(unittest.TestCase):
    def test_correlation_lift_and_ev(self):
        s = _sim()
        legs = [Leg("batter", "over", team="home", slot=0, market="hit2plus"),
                Leg("total", "over", line=3.5)]
        # Book prices the 2-leg parlay as if independent: 0.25 → decimal 4.0.
        q = price_sgp(s, legs, book_decimal=4.0)
        self.assertAlmostEqual(q.model_joint, 0.5)
        self.assertAlmostEqual(q.independent_joint, 0.25)
        self.assertAlmostEqual(q.correlation_lift, 0.25)   # true joint is double the naive price
        self.assertAlmostEqual(q.book_implied, 0.25)
        self.assertAlmostEqual(q.ev, 1.0)                  # 0.5 * 4.0 - 1 = +1.00 per $1
        self.assertAlmostEqual(q.fair_decimal, 2.0)        # 1 / 0.5

    def test_no_book_price(self):
        s = _sim()
        q = price_sgp(s, [Leg("total", "over", line=3.5)])
        self.assertIsNone(q.ev)
        self.assertIsNone(q.book_implied)

    def test_empty_legs_raises(self):
        with self.assertRaises(ValueError):
            price_sgp(_sim(), [])


if __name__ == "__main__":
    unittest.main()
