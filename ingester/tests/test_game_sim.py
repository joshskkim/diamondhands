"""Unit tests for the unified Monte-Carlo game simulator."""
from __future__ import annotations

import unittest

import numpy as np

from ingester.projection.batter_model import (
    AdjustedRates,
    BatterProbabilities,
    BatterProjection,
)
from ingester.projection.constants import (
    LEAGUE_BB_PER_PA,
    LEAGUE_HIT_PER_PA,
    LEAGUE_HR_PER_PA,
    LEAGUE_K_PER_PA,
)
from ingester.projection.game_sim import (
    batter_pa_probs,
    lineup_probs,
    prob_over,
    simulate_game,
)


def _proj(hit: float, hr: float, k: float, pid: int = 1) -> BatterProjection:
    """BatterProjection whose only sim-relevant field is `adjusted`; rest are dummies."""
    rates = AdjustedRates(hit_per_pa=hit, hr_per_pa=hr, k_per_pa=k)
    probs = BatterProbabilities(p_hit_1plus=0.0, p_hit_2plus=0.0, p_hr=0.0, p_k_1plus=0.0)
    return BatterProjection(
        expected_pa=4.2,
        adjusted=rates,
        probabilities=probs,
        expected_hits=0.0,
        expected_total_bases=0.0,
        xwoba_blend=0.0,
        iso_blend=0.0,
        adj_park_hit=1.0,
        adj_pitcher_hit=1.0,
        adj_weather_hit=1.0,
        adj_weather_hr=1.0,
    )


def _league_lineup() -> list[BatterProjection]:
    return [
        _proj(LEAGUE_HIT_PER_PA, LEAGUE_HR_PER_PA, LEAGUE_K_PER_PA, pid=i)
        for i in range(9)
    ]


class TestBatterPaProbs(unittest.TestCase):
    def test_probs_sum_to_one(self) -> None:
        p = batter_pa_probs(_proj(0.230, 0.035, 0.22))
        self.assertAlmostEqual(float(p.sum()), 1.0, places=9)
        self.assertTrue((p >= 0).all())

    def test_seven_classes(self) -> None:
        p = batter_pa_probs(_proj(0.230, 0.035, 0.22))
        self.assertEqual(p.shape, (7,))

    def test_hr_matches_input(self) -> None:
        # category 6 == HR per PA, normalized; should be close to input hr rate
        p = batter_pa_probs(_proj(0.230, 0.035, 0.22))
        self.assertAlmostEqual(p[6], 0.035, delta=0.01)

    def test_bb_uses_league_rate(self) -> None:
        p = batter_pa_probs(_proj(0.230, 0.035, 0.22))
        self.assertAlmostEqual(p[2], LEAGUE_BB_PER_PA, delta=0.01)

    def test_lineup_shape(self) -> None:
        self.assertEqual(lineup_probs(_league_lineup()).shape, (9, 7))


class TestSimulateGame(unittest.TestCase):
    def test_league_runs_are_reasonable(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=1)
        # Baserunning constants are calibrated so a league-average lineup scores
        # ~4.4 R/9 (empirical 2026 league avg is 4.48).
        self.assertGreater(sim.expected_home_runs, 4.0)
        self.assertLess(sim.expected_home_runs, 4.9)

    def test_symmetric_matchup_is_coinflip(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=2)
        self.assertAlmostEqual(sim.p_home_win, 0.5, delta=0.05)

    def test_total_equals_sum_of_sides(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=1500, seed=3)
        self.assertAlmostEqual(
            sim.expected_total,
            sim.expected_home_runs + sim.expected_away_runs,
            places=6,
        )

    def test_better_lineup_wins_more(self) -> None:
        strong = [_proj(0.330, 0.080, 0.15, pid=i) for i in range(9)]
        weak = [_proj(0.180, 0.010, 0.30, pid=i) for i in range(9)]
        sim = simulate_game(strong, weak, n_sims=3000, seed=4)
        self.assertGreater(sim.p_home_win, 0.65)
        self.assertGreater(sim.expected_home_runs, sim.expected_away_runs)

    def test_yrfi_in_range(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=3000, seed=5)
        self.assertGreater(sim.p_yrfi, 0.30)
        self.assertLess(sim.p_yrfi, 0.70)

    def test_props_shape_and_bounds(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=1500, seed=6)
        self.assertEqual(len(sim.home_props), 9)
        for bp in sim.home_props:
            for prob in (bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus):
                self.assertGreaterEqual(prob, 0.0)
                self.assertLessEqual(prob, 1.0)
            self.assertGreaterEqual(bp.p_hit_1plus, bp.p_hit_2plus)
            self.assertGreater(bp.expected_tb, 0.0)

    def test_strong_hitter_higher_hit_prob(self) -> None:
        strong = [_proj(0.330, 0.080, 0.15, pid=i) for i in range(9)]
        weak = [_proj(0.180, 0.010, 0.30, pid=i) for i in range(9)]
        sim = simulate_game(strong, weak, n_sims=3000, seed=7)
        self.assertGreater(sim.home_props[0].p_hit_1plus, sim.away_props[0].p_hit_1plus)

    def test_prob_over(self) -> None:
        runs = np.array([5, 6, 7, 8, 9])
        self.assertAlmostEqual(prob_over(runs, 7.0), 0.4)  # 8,9 > 7
        self.assertAlmostEqual(prob_over(runs, 4.0), 1.0)


if __name__ == "__main__":
    unittest.main()
