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
from ingester.projection import constants as C
from ingester.projection.game_sim import (
    _apply_tto_probs,
    batter_pa_probs,
    lineup_probs,
    prob_over,
    simulate_game,
    tto_multipliers,
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


class TestPeriodMarkets(unittest.TestCase):
    def test_all_periods_present(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=1000, seed=8)
        self.assertEqual(set(sim.periods), {1, 3, 5, 7, 9})

    def test_period_totals_monotonic(self) -> None:
        # Cumulative runs only grow, so expected period totals must be non-decreasing.
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=9)
        totals = [sim.periods[p].expected_total for p in (1, 3, 5, 7, 9)]
        for a, b in zip(totals, totals[1:]):
            self.assertLessEqual(a, b + 1e-9)

    def test_full_period_matches_convenience(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=2000, seed=10)
        self.assertEqual(sim.expected_total, sim.periods[9].expected_total)
        self.assertTrue((sim.home_runs == sim.periods[9].home_runs).all())

    def test_f5_total_is_about_half(self) -> None:
        # ~5/9 of a game; F5 total should be a bit over half the full-game total.
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=6000, seed=11)
        ratio = sim.f5.expected_total / sim.full.expected_total
        self.assertGreater(ratio, 0.45)
        self.assertLess(ratio, 0.65)

    def test_period_moneyline_probs_sum_to_one(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=12)
        f5 = sim.f5
        self.assertAlmostEqual(f5.p_home_lead + f5.p_away_lead + f5.p_tie, 1.0, places=6)
        # symmetric lineups -> F5 lead probs roughly equal
        self.assertAlmostEqual(f5.p_home_lead, f5.p_away_lead, delta=0.05)

    def test_f5_tie_more_likely_than_full_game(self) -> None:
        # Fewer innings -> more pushes (ties).
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=8000, seed=13)
        self.assertGreater(sim.f5.p_tie, sim.full.p_tie)

    def test_yrfi_equals_period1_over_zero(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=14)
        self.assertEqual(sim.p_yrfi, sim.periods[1].prob_over(0))
        self.assertGreater(sim.p_yrfi, 0.30)
        self.assertLess(sim.p_yrfi, 0.70)

    def test_total_hist_sums_to_nsims(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=3000, seed=15)
        hist = sim.f5.total_hist(15)
        self.assertEqual(sum(hist), 3000)
        self.assertEqual(len(hist), 16)


class TestBullpenTransition(unittest.TestCase):
    def test_f5_identical_with_or_without_bullpen(self) -> None:
        # Same seed: the first 5 innings face the starter either way, so F5 is identical.
        league = _league_lineup()
        weak_pen = [_proj(0.180, 0.010, 0.30, pid=i) for i in range(9)]
        a = simulate_game(league, league, n_sims=4000, seed=20)
        b = simulate_game(league, league, n_sims=4000, seed=20,
                          home_bullpen=weak_pen, away_bullpen=weak_pen)
        self.assertEqual(a.f5.expected_total, b.f5.expected_total)
        self.assertTrue((a.f5.home_runs == b.f5.home_runs).all())

    def test_weaker_bullpen_lowers_full_game_total(self) -> None:
        league = _league_lineup()
        weak_pen = [_proj(0.150, 0.005, 0.32, pid=i) for i in range(9)]
        base = simulate_game(league, league, n_sims=6000, seed=21)
        withpen = simulate_game(league, league, n_sims=6000, seed=21,
                                home_bullpen=weak_pen, away_bullpen=weak_pen)
        # Stingier bullpen in innings 6-9 -> fewer full-game runs, F5 unchanged.
        self.assertLess(withpen.full.expected_total, base.full.expected_total)


class TestPitcherProps(unittest.TestCase):
    def test_hists_sum_to_nsims_and_match_expected(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=4000, seed=30)
        for pp in (sim.home_pitcher_props, sim.away_pitcher_props):
            self.assertEqual(sum(pp.hits_hist), 4000)
            self.assertEqual(sum(pp.er_hist), 4000)
            # Expected value reconstructed from the histogram matches the stored mean
            # (within the >=max clipping — league hits/ER stay well under the ceilings).
            mean_h = sum(i * c for i, c in enumerate(pp.hits_hist)) / 4000
            self.assertAlmostEqual(mean_h, pp.expected_hits, delta=0.05)

    def test_league_starter_allows_reasonable_hits_and_er(self) -> None:
        # A league-average lineup vs a ~5-inning starter: a handful of hits, ~2-3 ER.
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=5000, seed=31)
        pp = sim.home_pitcher_props
        self.assertGreater(pp.expected_hits, 3.0)
        self.assertLess(pp.expected_hits, 7.0)
        self.assertGreater(pp.expected_er, 1.0)
        self.assertLess(pp.expected_er, 4.0)

    def test_weaker_lineup_tags_the_starter_less(self) -> None:
        # The home starter faces the AWAY lineup; a weak away lineup => fewer hits/ER.
        strong = [_proj(0.330, 0.080, 0.15, pid=i) for i in range(9)]
        weak = [_proj(0.180, 0.010, 0.30, pid=i) for i in range(9)]
        sim = simulate_game(strong, weak, n_sims=4000, seed=32)
        self.assertLess(sim.home_pitcher_props.expected_hits,
                        sim.away_pitcher_props.expected_hits)
        self.assertLess(sim.home_pitcher_props.expected_er,
                        sim.away_pitcher_props.expected_er)

    def test_shorter_starter_allows_fewer_runs(self) -> None:
        # Pulling the starter an inning earlier can only lower his runs/hits allowed.
        league = _league_lineup()
        deep = simulate_game(league, league, n_sims=6000, seed=33,
                             home_starter_innings=6, away_starter_innings=6)
        short = simulate_game(league, league, n_sims=6000, seed=33,
                              home_starter_innings=3, away_starter_innings=3)
        self.assertLess(short.home_pitcher_props.expected_er,
                        deep.home_pitcher_props.expected_er)


class TestRunLineCover(unittest.TestCase):
    def test_symmetric_cover_probs_balanced(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=8000, seed=40)
        # No push at a .5 line: a side's -1.5 and the other's +1.5 partition the space.
        self.assertAlmostEqual(
            sim.full.p_home_cover(-1.5) + sim.full.p_away_cover(1.5), 1.0, places=6)
        self.assertAlmostEqual(sim.p_home_cover_1_5, sim.full.p_home_cover(-1.5), places=9)
        # Symmetric lineups => home -1.5 cover roughly equals away +1.5 underdog cover's
        # complement; the favorite-side cover should sit below 0.5.
        self.assertLess(sim.p_home_cover_1_5, 0.5)

    def test_strong_home_covers_more(self) -> None:
        strong = [_proj(0.330, 0.080, 0.15, pid=i) for i in range(9)]
        weak = [_proj(0.180, 0.010, 0.30, pid=i) for i in range(9)]
        sim = simulate_game(strong, weak, n_sims=4000, seed=41)
        self.assertGreater(sim.p_home_cover_1_5, 0.5)
        self.assertGreater(sim.p_home_cover_1_5, sim.p_away_cover_1_5)


class TestRetainTeams(unittest.TestCase):
    def test_default_does_not_retain_arrays(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=200, seed=5)
        self.assertIsNone(sim.home)
        self.assertIsNone(sim.away)

    def test_opt_in_retains_arrays_for_sgp(self) -> None:
        sim = simulate_game(_league_lineup(), _league_lineup(), n_sims=200, seed=5,
                            retain_teams=True)
        self.assertIsNotNone(sim.home)
        self.assertIsNotNone(sim.away)
        self.assertEqual(sim.home.slot_hits.shape, (200, 9))


class TestTtoPenalty(unittest.TestCase):
    def test_first_time_through_is_neutral(self) -> None:
        self.assertEqual(tto_multipliers(0, 0.55), (1.0, 1.0))

    def test_later_turns_raise_offense_and_lower_k(self) -> None:
        om2, km2 = tto_multipliers(1, C.TTO_FB_REFERENCE)
        om3, km3 = tto_multipliers(2, C.TTO_FB_REFERENCE)
        self.assertGreater(om2, 1.0)
        self.assertLess(km2, 1.0)
        self.assertGreater(om3, om2)   # 3rd time through hurts more than 2nd
        self.assertLess(km3, km2)

    def test_fastball_heavy_starter_decays_more(self) -> None:
        om_hi, _ = tto_multipliers(2, 0.75)
        om_lo, _ = tto_multipliers(2, 0.40)
        self.assertGreater(om_hi, om_lo)

    def test_fb_factor_is_clamped(self) -> None:
        # An absurd fb share saturates at the clamp, not unbounded.
        om_extreme, _ = tto_multipliers(2, 5.0)
        om_clamped = 1.0 + C.TTO_OFFENSE_DELTA_3RD * C.TTO_FB_FACTOR_MAX
        self.assertAlmostEqual(om_extreme, om_clamped)

    def test_apply_tto_keeps_rows_normalized_and_raises_hits(self) -> None:
        base = lineup_probs(_league_lineup())
        out = _apply_tto_probs(base, 1.10, 0.95)
        np.testing.assert_allclose(out.sum(axis=1), 1.0, atol=1e-9)
        self.assertGreater(out[:, 3:7].sum(), base[:, 3:7].sum())  # more hits+HR
        self.assertLess(out[:, 1].sum(), base[:, 1].sum())          # fewer K

    def test_off_by_default_ignores_fb_share(self) -> None:
        # With TTO disabled (default), passing a fb share must change nothing.
        lineup = _league_lineup()
        a = simulate_game(lineup, lineup, n_sims=600, seed=7,
                          home_starter_fb_share=0.55, away_starter_fb_share=0.55)
        b = simulate_game(lineup, lineup, n_sims=600, seed=7)
        self.assertEqual(a.expected_total, b.expected_total)

    def test_enabled_raises_offense(self) -> None:
        lineup = _league_lineup()
        base = simulate_game(lineup, lineup, n_sims=3000, seed=11)
        C.TTO_ENABLED = True
        try:
            boosted = simulate_game(lineup, lineup, n_sims=3000, seed=11,
                                    home_starter_fb_share=0.55, away_starter_fb_share=0.55)
        finally:
            C.TTO_ENABLED = False
        # Later-turn batters score more, so the run environment rises.
        self.assertGreater(boosted.expected_total, base.expected_total)
        # F1 (first inning, always 1st time through) is essentially untouched.
        self.assertAlmostEqual(base.periods[1].expected_total,
                               boosted.periods[1].expected_total, delta=0.05)


if __name__ == "__main__":
    unittest.main()
