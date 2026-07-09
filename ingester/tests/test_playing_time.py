"""Unit tests for the playing-time / start-probability model (pure helpers, no DB)."""
from __future__ import annotations

import unittest

from ingester.projection.constants import PA_BY_ORDER
from ingester.projection.playing_time import (
    PlayingTime,
    build_predicted_lineup,
    compute_playing_time,
    start_probability,
)


class TestStartProbability(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(start_probability([]), 0.0)

    def test_always_started_is_one(self):
        self.assertAlmostEqual(start_probability([True] * 10), 1.0)

    def test_never_started_is_zero(self):
        self.assertEqual(start_probability([False] * 10), 0.0)

    def test_recent_weighted_more(self):
        # Started the 3 most recent, sat the 3 before → > 0.5 because recent counts more.
        p = start_probability([True, True, True, False, False, False], decay=0.9)
        self.assertGreater(p, 0.5)

    def test_recency_direction(self):
        # Same count of starts, but more recent → higher probability.
        recent = start_probability([True, True, False, False], decay=0.8)
        stale = start_probability([False, False, True, True], decay=0.8)
        self.assertGreater(recent, stale)

    def test_no_decay_is_plain_fraction(self):
        self.assertAlmostEqual(start_probability([True, False, True, False], decay=1.0), 0.5)


class TestComputePlayingTime(unittest.TestCase):
    def test_everyday_leadoff(self):
        pt = compute_playing_time(1, [1, 1, 1, 1, 1])
        self.assertAlmostEqual(pt.p_start, 1.0)
        self.assertAlmostEqual(pt.expected_slot, 1.0)
        self.assertAlmostEqual(pt.expected_pa, PA_BY_ORDER[1])  # full PA at slot 1

    def test_bench_player_low_pa(self):
        pt = compute_playing_time(2, [None, None, None, None, None])
        self.assertEqual(pt.p_start, 0.0)
        self.assertIsNone(pt.expected_slot)
        self.assertEqual(pt.expected_pa, 0.0)

    def test_platoon_partial_start(self):
        # Starts roughly half, batting 6th when he does.
        pt = compute_playing_time(3, [6, None, 6, None, 6, None], decay=1.0)
        self.assertAlmostEqual(pt.p_start, 0.5)
        self.assertAlmostEqual(pt.expected_slot, 6.0)
        # unconditional PA = p_start * PA at slot 6
        self.assertAlmostEqual(pt.expected_pa, round(0.5 * PA_BY_ORDER[6], 2))

    def test_expected_pa_scales_with_start_prob(self):
        everyday = compute_playing_time(4, [3, 3, 3, 3])
        sometimes = compute_playing_time(5, [3, None, 3, None])
        self.assertGreater(everyday.expected_pa, sometimes.expected_pa)

    def test_returns_dataclass(self):
        self.assertIsInstance(compute_playing_time(6, [2, 2]), PlayingTime)


def pt(player_id, p_start, slot, pa=4.0):
    return PlayingTime(player_id=player_id, p_start=p_start,
                       expected_slot=slot, expected_pa=pa)


class TestBuildPredictedLineup(unittest.TestCase):
    def test_everyday_nine_in_slot_order(self):
        # Nine everyday starters plus two bench bats; lineup = the nine, by slot.
        times = {i: pt(i, 0.95, float(i)) for i in range(1, 10)}
        times[20] = pt(20, 0.20, 7.5)
        times[21] = pt(21, 0.0, None)
        lineup = build_predicted_lineup(times)
        self.assertEqual(lineup, [(order, order) for order in range(1, 10)])

    def test_selection_by_start_prob_not_slot(self):
        # A ninth-slot everyday catcher beats a leadoff-slotted part-timer.
        times = {i: pt(i, 0.95, float(i)) for i in range(1, 9)}          # 8 regulars
        times[9] = pt(9, 0.90, 9.0)      # everyday, bats 9th → in
        times[10] = pt(10, 0.30, 1.0)    # platoon leadoff → out
        lineup = build_predicted_lineup(times)
        chosen = {pid for _order, pid in lineup}
        self.assertIn(9, chosen)
        self.assertNotIn(10, chosen)

    def test_never_started_sorts_last_and_ties_deterministic(self):
        times = {i: pt(i, 0.9, float(i)) for i in range(1, 9)}
        # Equal p_start, no slot history (None) → sorts to the 9-hole.
        times[30] = pt(30, 0.9, None)
        lineup = build_predicted_lineup(times)
        self.assertEqual(lineup[-1], (9, 30))

    def test_insufficient_history_returns_empty(self):
        times = {i: pt(i, 0.9, float(i)) for i in range(1, 9)}  # only 8 startable
        times[40] = pt(40, 0.0, None)                            # never starts
        self.assertEqual(build_predicted_lineup(times), [])

    def test_orders_are_one_through_nine(self):
        times = {i: pt(i, 0.5 + i * 0.01, float(10 - i)) for i in range(1, 12)}
        lineup = build_predicted_lineup(times)
        self.assertEqual([order for order, _pid in lineup], list(range(1, 10)))


if __name__ == "__main__":
    unittest.main()
