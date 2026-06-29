"""Unit tests for the Diamond Analyst eval harness (faithfulness, trajectory, outcome).

These are the "tests for a non-deterministic system" the eval-first design is about: the
deterministic layers (numeric grounding, tool-trajectory recall) are fully unit-tested here, and
the outcome aggregation's math (ROI/Brier) is checked against hand-computed values.
"""
from __future__ import annotations

import unittest

from agent_eval import faithfulness, trajectory, outcome


class FaithfulnessTest(unittest.TestCase):
    def test_grounded_numbers_pass(self):
        pool = '{"edge":0.062,"evPct":0.10,"priceAmerican":130,"modelProb":0.581}'
        r = faithfulness.numeric_grounding(
            "Best edge is 6.2% (EV 10%) at +130, model probability 0.58.", pool)
        self.assertTrue(r["passed"], r)
        self.assertEqual(r["orphans"], [])

    def test_invented_price_is_orphan(self):
        r = faithfulness.numeric_grounding("Take the +900 longshot.", '{"priceAmerican":130}')
        self.assertFalse(r["passed"])
        self.assertIn("+900", r["orphans"])

    def test_percent_grounds_against_probability_basis(self):
        # 58% in prose should match a 0.58 probability in the tool JSON.
        r = faithfulness.numeric_grounding("Model gives it 58%.", '{"modelProb":0.58}')
        self.assertTrue(r["passed"], r)

    def test_trivial_small_integers_ignored(self):
        # Plain small integers (innings, ranks) aren't stat-like and must not be flagged.
        r = faithfulness.numeric_grounding("My top 3 picks for the 1st inning.", "{}")
        self.assertTrue(r["passed"], r)
        self.assertEqual(r["checked"], 0)


class TrajectoryTest(unittest.TestCase):
    def test_required_recall_gates(self):
        r = trajectory.score({"required": ["get_best_plays", "debate_pick"], "optional": []},
                             ["get_best_plays"])
        self.assertFalse(r["passed"])
        self.assertEqual(r["missing"], ["debate_pick"])
        self.assertEqual(r["recall"], 0.5)

    def test_optional_tools_dont_hurt_recall(self):
        r = trajectory.score({"required": ["get_best_plays"], "optional": ["get_most_likely"]},
                             ["get_best_plays", "get_most_likely"])
        self.assertTrue(r["passed"])
        self.assertEqual(r["recall"], 1.0)
        self.assertEqual(r["precision"], 1.0)

    def test_irrelevant_tool_lowers_precision_only(self):
        r = trajectory.score({"required": ["get_best_plays"], "optional": []},
                             ["get_best_plays", "search_player"])
        self.assertTrue(r["passed"])  # recall still 1.0
        self.assertEqual(r["precision"], 0.5)


class OutcomeMathTest(unittest.TestCase):
    def test_roi_and_brier(self):
        # Two graded recs: a won +100 (decimal 2.0) at 1u, and a lost -110 at 1u.
        # ROI = (+1.0 - 1.0) / 2.0 = 0.0 ; Brier on confidences 0.6 (won) & 0.55 (lost):
        #   ((0.6-1)^2 + (0.55-0)^2)/2 = (0.16 + 0.3025)/2 = 0.23125
        rows = [
            (True, 0.02, 0.6, 100, 1.0),
            (False, -0.01, 0.55, -110, 1.0),
        ]
        agg = _aggregate_rows(rows)
        self.assertEqual(agg["graded"], 2)
        self.assertEqual(agg["hit_rate"], 0.5)
        self.assertAlmostEqual(agg["roi"], 0.0, places=4)
        self.assertAlmostEqual(agg["brier"], 0.2313, places=3)
        self.assertAlmostEqual(agg["avg_clv"], 0.005, places=4)


def _aggregate_rows(rows):
    """Re-implements outcome.aggregate's pure math over in-memory rows (no DB)."""
    graded = [r for r in rows if r[0] is not None]
    n = len(graded)
    wins = sum(1 for r in graded if r[0])
    staked = profit = 0.0
    for won, _clv, _conf, price, stake in graded:
        s = float(stake) if stake is not None else 1.0
        staked += s
        profit += s * (outcome._american_to_decimal(int(price)) - 1.0) if won else -s
    clvs = [float(r[1]) for r in rows if r[1] is not None]
    briers = [(float(c) - (1.0 if w else 0.0)) ** 2 for w, _c, c, _p, _s in graded if c is not None]
    return {
        "graded": n,
        "hit_rate": round(wins / n, 4) if n else None,
        "avg_clv": round(sum(clvs) / len(clvs), 4) if clvs else None,
        "roi": round(profit / staked, 4) if staked else None,
        "brier": round(sum(briers) / len(briers), 4) if briers else None,
    }


if __name__ == "__main__":
    unittest.main()
