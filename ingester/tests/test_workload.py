"""Hand-computed unit tests for the starter workload model."""
from __future__ import annotations

import unittest

from ingester.projection.workload import (
    WorkloadParams,
    expected_outs,
    fit_bf_given_outs,
    k_rate_blend,
    outs_distribution,
    p_outs_over,
    p_strikeouts_over,
    walk_forward_residuals,
    weighted_mean,
)

PARAMS = WorkloadParams(
    league_mean_outs=15.5,
    league_k_per_bf=0.22,
    residuals=(-6.0, -3.0, 0.0, 0.0, 3.0, 6.0),
    bf_intercept=4.0,
    bf_slope=1.3,
)


class TestExpectedOuts(unittest.TestCase):
    def test_weighted_mean_recency(self):
        # most-recent-first [18, 12]: (1*18 + .9*12) / 1.9
        mean, n_eff = weighted_mean([18.0, 12.0])
        self.assertAlmostEqual(mean, (18 + 0.9 * 12) / 1.9, places=6)
        self.assertAlmostEqual(n_eff, 1.9, places=6)

    def test_empty_history_is_pure_league(self):
        self.assertAlmostEqual(expected_outs([], 15.5), 15.5, places=6)

    def test_eb_blend(self):
        # One 18-out start: (1*18 + 3*15.5) / 4
        self.assertAlmostEqual(expected_outs([18], 15.5), (18 + 3 * 15.5) / 4, places=6)

    def test_long_history_dominates_prior(self):
        workhorse = expected_outs([20] * 10, 15.5)
        self.assertGreater(workhorse, 18.0)  # pulled well above league


class TestDistributions(unittest.TestCase):
    def test_outs_distribution_sums_to_one(self):
        dist = outs_distribution(16.0, PARAMS)
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=9)

    def test_p_outs_over_matches_hand_count(self):
        # mu=16: shifted outcomes {10,13,16,16,19,22} → over 16.5: {19,22} = 2/6
        self.assertAlmostEqual(p_outs_over(16.5, 16.0, PARAMS), 2 / 6, places=9)
        # over 15.5: {16,16,19,22} = 4/6
        self.assertAlmostEqual(p_outs_over(15.5, 16.0, PARAMS), 4 / 6, places=9)

    def test_deeper_pitcher_clears_more(self):
        self.assertGreater(p_outs_over(16.5, 19.0, PARAMS), p_outs_over(16.5, 14.0, PARAMS))

    def test_clamping_at_physical_bounds(self):
        dist = outs_distribution(26.0, PARAMS)  # residual +6 would exceed 27
        self.assertTrue(all(0 <= o <= 27 for o in dist))
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=9)


class TestStrikeouts(unittest.TestCase):
    def test_k_rate_blend_thin_history_near_league(self):
        self.assertAlmostEqual(k_rate_blend([], 0.22), 0.22, places=6)
        # 40 BF of elite K work only nudges off league with 100 phantom BF.
        blended = k_rate_blend([(16, 40)], 0.22)
        self.assertGreater(blended, 0.22)
        self.assertLess(blended, 0.30)

    def test_blowup_start_weighs_by_bf(self):
        # (0 K, 0 BF) entries are ignored entirely.
        self.assertAlmostEqual(k_rate_blend([(0, 0)], 0.22), 0.22, places=6)

    def test_p_strikeouts_monotone_in_rate_and_depth(self):
        lo = p_strikeouts_over(5.5, 16.0, 0.18, PARAMS)
        hi = p_strikeouts_over(5.5, 16.0, 0.30, PARAMS)
        self.assertGreater(hi, lo)
        shallow = p_strikeouts_over(5.5, 13.0, 0.25, PARAMS)
        deep = p_strikeouts_over(5.5, 19.0, 0.25, PARAMS)
        self.assertGreater(deep, shallow)


class TestFitting(unittest.TestCase):
    def test_bf_fit_recovers_line(self):
        pairs = [(o, int(round(4 + 1.3 * o))) for o in range(6, 28, 3)]
        a, b = fit_bf_given_outs(pairs)
        self.assertAlmostEqual(a, 4.0, delta=0.6)
        self.assertAlmostEqual(b, 1.3, delta=0.05)

    def test_walk_forward_residuals_no_leakage(self):
        # First start's residual is vs pure league (no history yet).
        res = walk_forward_residuals({1: [18, 12]}, 15.5)
        self.assertAlmostEqual(res[0], 18 - 15.5, places=6)
        # Second start's expectation uses only the first start.
        self.assertAlmostEqual(res[1], 12 - expected_outs([18], 15.5), places=6)


class TestComputeStarterWorkload(unittest.TestCase):
    def test_bundle_shape_and_innings_clamp(self):
        from ingester.projection.workload import (
            compute_starter_workload, WORKLOAD_OUTS_LINES, WORKLOAD_K_LINES,
            WORKLOAD_SIM_MIN_INNINGS, WORKLOAD_SIM_MAX_INNINGS,
        )
        wl = compute_starter_workload([18, 17, 19], [(7, 24), (6, 22), (8, 25)], PARAMS)
        self.assertIn("mu_outs", wl)
        self.assertEqual(set(wl["p_outs"]), {f"{L}" for L in WORKLOAD_OUTS_LINES})
        self.assertEqual(set(wl["p_k"]), {f"{L}" for L in WORKLOAD_K_LINES})
        self.assertTrue(WORKLOAD_SIM_MIN_INNINGS <= wl["innings"] <= WORKLOAD_SIM_MAX_INNINGS)
        # All probabilities in [0,1].
        for p in list(wl["p_outs"].values()) + list(wl["p_k"].values()):
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    def test_deeper_pitcher_more_outs_prob(self):
        from ingester.projection.workload import compute_starter_workload
        deep = compute_starter_workload([21, 20, 22], [(6, 26)] * 3, PARAMS)
        shallow = compute_starter_workload([12, 11, 13], [(2, 18)] * 3, PARAMS)
        self.assertGreater(float(deep["p_outs"]["17.5"]), float(shallow["p_outs"]["17.5"]))
        self.assertGreaterEqual(deep["innings"], shallow["innings"])

    def test_empty_history_falls_to_league(self):
        # runner.py computes a workload even for a starter with no recorded starts (relying
        # on the league-prior fallback) so his props don't blank. Assert the full bundle —
        # not just mu — is usable: populated K/outs ladders in [0,1] and a clamped innings.
        from ingester.projection.workload import (
            compute_starter_workload, WORKLOAD_OUTS_LINES, WORKLOAD_K_LINES,
            WORKLOAD_SIM_MIN_INNINGS, WORKLOAD_SIM_MAX_INNINGS,
        )
        wl = compute_starter_workload([], [], PARAMS)
        self.assertAlmostEqual(wl["mu_outs"], PARAMS.league_mean_outs, places=2)
        self.assertEqual(set(wl["p_outs"]), {f"{L}" for L in WORKLOAD_OUTS_LINES})
        self.assertEqual(set(wl["p_k"]), {f"{L}" for L in WORKLOAD_K_LINES})
        self.assertTrue(WORKLOAD_SIM_MIN_INNINGS <= wl["innings"] <= WORKLOAD_SIM_MAX_INNINGS)
        for p in list(wl["p_outs"].values()) + list(wl["p_k"].values()):
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)


class TestLineGrid(unittest.TestCase):
    """The stored grid decides which book lines get a model probability at all — a line
    off the grid is served as "no model". These pin the range books actually quote."""

    def test_grid_covers_quoted_book_lines(self):
        from ingester.projection.workload import compute_starter_workload
        wl = compute_starter_workload([18, 17, 19], [(7, 24)] * 3, PARAMS)
        # Observed in player_prop_odds: outs 12.5–18.5, K 3.5–9.5.
        for line in (12.5, 13.5, 14.5, 15.5, 16.5, 17.5, 18.5):
            self.assertIn(f"{line}", wl["p_outs"])
        for line in (3.5, 4.5, 5.5, 6.5, 7.5, 9.5):
            self.assertIn(f"{line}", wl["p_k"])

    def test_keys_are_plain_half_line_strings(self):
        # The API looks these up by a normalized line key ("15.5"), so no "15.50"/"15".
        from ingester.projection.workload import WORKLOAD_K_LINES, WORKLOAD_OUTS_LINES
        for line in (*WORKLOAD_OUTS_LINES, *WORKLOAD_K_LINES):
            self.assertRegex(f"{line}", r"^\d+\.5$")

    def test_p_over_decreases_across_the_grid(self):
        from ingester.projection.workload import (
            WORKLOAD_K_LINES, WORKLOAD_OUTS_LINES, compute_starter_workload,
        )
        wl = compute_starter_workload([18, 17, 19], [(7, 24)] * 3, PARAMS)
        for lines, key in ((WORKLOAD_OUTS_LINES, "p_outs"), (WORKLOAD_K_LINES, "p_k")):
            probs = [wl[key][f"{L}"] for L in sorted(lines)]
            for lo, hi in zip(probs, probs[1:]):
                self.assertGreaterEqual(lo, hi)


if __name__ == "__main__":
    unittest.main()
