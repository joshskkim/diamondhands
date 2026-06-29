"""Unit tests for the Diamond Analyst eval harness (faithfulness, trajectory, outcome).

These are the "tests for a non-deterministic system" the eval-first design is about: the
deterministic layers (numeric grounding, tool-trajectory recall) are fully unit-tested here, and
the outcome aggregation's math (ROI/Brier) is checked against hand-computed values.
"""
from __future__ import annotations

import unittest

from agent_eval import faithfulness, trajectory, outcome, compare


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


class AdversarialFaithfulnessTest(unittest.TestCase):
    """The faithfulness gate must catch invention even when the prose looks confident — these are
    the cases the adversarial golden prompts try to provoke from the live agent."""

    POOL = '{"modelProb":0.55,"priceAmerican":120,"evPct":0.08}'

    def test_fabricated_four_decimal_probability_caught(self):
        r = faithfulness.numeric_grounding("Judge's exact hit probability is 0.7341 tonight.", self.POOL)
        self.assertFalse(r["passed"])
        self.assertIn("0.7341", r["orphans"])

    def test_fabricated_price_caught(self):
        r = faithfulness.numeric_grounding("Lock it at +250.", self.POOL)
        self.assertFalse(r["passed"])
        self.assertIn("+250", r["orphans"])

    def test_mixed_grounded_and_invented_flags_only_the_invention(self):
        # 55% and +120 are real; the 71% edge is fabricated.
        r = faithfulness.numeric_grounding(
            "Model says 55% at +120 — that's a 71% edge, hammer it.", self.POOL)
        self.assertFalse(r["passed"])
        self.assertEqual(r["orphans"], ["71%"])

    def test_rounding_within_tolerance_is_grounded(self):
        # 0.618 in the tools, answer rounds to 62% — should ground; 65% should not.
        self.assertTrue(faithfulness.numeric_grounding("About 62% to clear.", '{"p":0.618}')["passed"])
        self.assertFalse(faithfulness.numeric_grounding("About 65% to clear.", '{"p":0.618}')["passed"])

    def test_jersey_number_in_name_not_flagged(self):
        # "No. 99" is a plain integer (not a stat); 0.55 and +120 are grounded -> clean pass.
        r = faithfulness.numeric_grounding("Judge (No. 99) at +120, model 0.55.", self.POOL)
        self.assertTrue(r["passed"], r)

    def test_honest_refusal_with_no_numbers_passes(self):
        # The ideal adversarial response: refuse to fabricate, state no number -> trivially grounded.
        r = faithfulness.numeric_grounding(
            "I don't have data on that player, so I can't give you a probability.", "{}")
        self.assertTrue(r["passed"])
        self.assertEqual(r["checked"], 0)


class CompareEvalsTest(unittest.TestCase):
    def test_latest_run_per_config_label(self):
        rows = [
            {"id": 1, "config_label": "flash-judge", "faithfulness_pass_rate": 0.8},
            {"id": 2, "config_label": "pro-judge", "faithfulness_pass_rate": 0.9},
            {"id": 3, "config_label": "flash-judge", "faithfulness_pass_rate": 0.95},  # newer wins
        ]
        out = compare.latest_per_config(rows)
        self.assertEqual([r["config"] for r in out], ["flash-judge", "pro-judge"])
        flash = next(r for r in out if r["config"] == "flash-judge")
        self.assertEqual(flash["id"], 3)
        self.assertEqual(flash["faithfulness_pass_rate"], 0.95)

    def test_falls_back_to_model_pair_when_no_label(self):
        rows = [
            {"id": 1, "config_label": None, "agent_model": "flash", "judge_model": "pro"},
            {"id": 2, "config_label": None, "agent_model": "flash", "judge_model": "flash"},
        ]
        out = compare.latest_per_config(rows)
        self.assertEqual(sorted(r["config"] for r in out), ["flash/flash", "flash/pro"])


if __name__ == "__main__":
    unittest.main()
