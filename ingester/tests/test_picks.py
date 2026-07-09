"""Unit tests for Model's Picks recording/scoring + the degeneracy guard."""
from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from ingester.commands.picks import (
    MAX_PICKS, OUT, PICK_BUDGET, UNKNOWN, _devig_two_way, _grade, _pick_key,
    american_to_decimal, bar_recheck, build_candidates, build_picks,
    gate_candidates, plan_lineup_reeval, plan_reconcile, poisson_game_prob,
    settle_prop,
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
            play(game_id=1, model=0.60, fair=0.50, ev=0.10),       # qualifies (edge 10pt)
            play(game_id=2, model=0.55, fair=0.50, ev=0.10),       # edge 5pt < 6pt floor
            play(game_id=3, model=0.68, fair=0.55, ev=0.25),       # edge 13pt > 12.5pt cap
            play(game_id=4, model=0.60, fair=0.50, ev=0.02),       # EV < 5%
            play(game_id=5, market="pitcher_k", model=0.7, fair=0.5, ev=0.2),  # excluded
            play(game_id=6, model=0.37, fair=0.30, ev=0.10),       # longshot, edge 7 < 8
            {**play(game_id=7), "fairProb": None},                  # one-sided, no de-vig
            play(game_id=8, market="hit", model=0.60, fair=0.50, ev=0.10),  # hit excluded (interim)
        ]
        picks = build_picks(plays, sim=None)
        self.assertEqual([p["gameId"] for p in picks], [1])

    def test_bar_boundaries(self):
        # Exactly-at-threshold edges: MIN_EDGE inclusive, MAX_EDGE inclusive.
        at_min = play(game_id=1, model=0.56, fair=0.50, ev=0.10)    # edge exactly .06
        below = play(game_id=2, model=0.559, fair=0.50, ev=0.10)    # .059 fails
        at_max = play(game_id=3, model=0.625, fair=0.50, ev=0.15)   # edge exactly .125
        above = play(game_id=4, model=0.626, fair=0.50, ev=0.15)    # .126 fails
        picks = build_picks([at_min, below, at_max, above], sim=None)
        self.assertEqual(sorted(p["gameId"] for p in picks), [1, 3])

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


class TestPlanReconcile(unittest.TestCase):
    """The lock + budget regime: no displacement, inserts gated by the slate budget."""

    NOW = datetime(2026, 6, 23, 18, 0, tzinfo=timezone.utc)

    def existing(self, picks, active=True, start=None, bump_reason=None):
        """Build an existing-rows map keyed like the DB read (id starts at 100)."""
        return {
            _pick_key(p): (100 + i, active, start, bump_reason)
            for i, p in enumerate(picks)
        }

    def test_first_run_all_insert(self):
        picks = [play(game_id=1), play(game_id=2, player_id=20)]
        ops = plan_reconcile(picks, {}, self.NOW, board_loaded=True, budget=PICK_BUDGET)
        self.assertEqual([o[0] for o in ops], ["insert", "insert"])
        self.assertEqual([o[1] for o in ops], [1, 2])  # ranks

    def test_active_pick_is_locked_no_op(self):
        p = play(game_id=1)
        ops = plan_reconcile([p], self.existing([p]), self.NOW,
                             board_loaded=True, budget=2)
        self.assertEqual(ops, [])

    def test_better_late_pick_never_displaces(self):
        early = play(game_id=1)
        existing = self.existing([early])           # already on record, active
        late = play(game_id=2, player_id=20)        # different game now tops the board
        ops = plan_reconcile([late], existing, self.NOW, board_loaded=True, budget=2)
        # The late play may still be ADDED (budget remains) but the early pick stays.
        self.assertEqual([o[0] for o in ops], ["insert"])

    def test_budget_blocks_fourth_row(self):
        recorded = [play(game_id=g, player_id=g) for g in (1, 2, 3)]
        # One was lineup-bumped: the row still counts, budget is spent.
        existing = self.existing(recorded)
        key3 = _pick_key(recorded[2])
        existing[key3] = (102, False, None, "lineup")
        newcomer = play(game_id=4, player_id=40)
        ops = plan_reconcile([newcomer], existing, self.NOW,
                             board_loaded=True, budget=PICK_BUDGET - len(existing))
        self.assertEqual(ops, [])

    def test_late_fill_within_budget(self):
        # Morning qualified only 2; a later tick may add the 3rd (bar, not clock, gates).
        recorded = [play(game_id=1), play(game_id=2, player_id=20)]
        existing = self.existing(recorded)
        newcomer = play(game_id=3, player_id=30)
        ops = plan_reconcile([newcomer], existing, self.NOW,
                             board_loaded=True, budget=PICK_BUDGET - len(existing))
        self.assertEqual([o[0] for o in ops], ["insert"])
        self.assertEqual(ops[0][1], 3)  # rank continues after the recorded rows

    def test_lineup_bumped_row_not_repromoted_by_reconcile(self):
        p = play(game_id=1)
        existing = self.existing([p], active=False, bump_reason="lineup")
        # The same selection re-qualifies on the board — only re-eval may un-bump it.
        ops = plan_reconcile([p], existing, self.NOW, board_loaded=True, budget=2)
        self.assertEqual(ops, [])

    def test_legacy_displaced_row_repromoted(self):
        p = play(game_id=1)
        existing = self.existing([p], active=False, bump_reason="displaced")
        ops = plan_reconcile([p], existing, self.NOW, board_loaded=True, budget=2)
        self.assertEqual(ops, [("keep", 100)])

    def test_legacy_displaced_started_game_stays_frozen(self):
        p = play(game_id=1)
        existing = self.existing([p], active=False, start=self.NOW - timedelta(hours=1),
                                 bump_reason="displaced")
        ops = plan_reconcile([p], existing, self.NOW, board_loaded=True, budget=2)
        self.assertEqual(ops, [])

    def test_empty_board_is_no_op(self):
        # Board didn't load (odds expired) → leave the record untouched.
        existing = self.existing([play(game_id=1)])
        ops = plan_reconcile([], existing, self.NOW, board_loaded=False, budget=2)
        self.assertEqual(ops, [])

    def test_board_with_no_qualifiers_leaves_record_alone(self):
        # Board loaded but nothing clears the bar now → the locked pick still stands.
        existing = self.existing([play(game_id=1)])
        ops = plan_reconcile([], existing, self.NOW, board_loaded=True, budget=2)
        self.assertEqual(ops, [])

    def test_active_cap_holds_even_with_budget(self):
        # 3 active + budget quirk (shouldn't happen, but the cap is belt-and-braces).
        recorded = [play(game_id=g, player_id=g) for g in (1, 2, 3)]
        existing = self.existing(recorded)
        newcomer = play(game_id=4, player_id=40)
        ops = plan_reconcile([newcomer], existing, self.NOW, board_loaded=True, budget=5)
        self.assertEqual(ops, [])


def reeval_row(pick_id=100, active=True, bump_reason=None, start=None,
               stored="aaa", current="bbb", model=0.60, fair=0.50, price=-110):
    return {
        "pick_id": pick_id, "active": active, "bump_reason": bump_reason,
        "start_time": start, "stored_hash": stored, "current_hash": current,
        "model_prob_now": model, "locked_fair_prob": fair,
        "locked_price_decimal": american_to_decimal(price),
    }


class TestBarRecheck(unittest.TestCase):
    def test_floors(self):
        # -110 → decimal 1.909: model .60 vs fair .50 = edge .10, EV ≈ .145 → clears.
        self.assertTrue(bar_recheck(0.60, 0.50, american_to_decimal(-110)))
        # Model sagged to .54: edge .04 < .06 → fails.
        self.assertFalse(bar_recheck(0.54, 0.50, american_to_decimal(-110)))
        # Model .57: edge .07 clears but EV = .57×1.909−1 ≈ .088... clears too;
        # push EV under the floor with a worse price: .55 at -125 → EV = −.01.
        self.assertFalse(bar_recheck(0.55, 0.48, american_to_decimal(-125)))

    def test_no_max_edge_ceiling(self):
        # The model moving FURTHER our way (edge .30 > MAX_EDGE) must NOT fail.
        self.assertTrue(bar_recheck(0.80, 0.50, american_to_decimal(-110)))

    def test_longshot_rule(self):
        # Below MIN_MODEL_PROB with edge under LONGSHOT_EDGE → fails...
        self.assertFalse(bar_recheck(0.36, 0.295, american_to_decimal(+250)))
        # ...but an outsized edge keeps a longshot alive.
        self.assertTrue(bar_recheck(0.39, 0.30, american_to_decimal(+250)))

    def test_market_isolation_by_signature(self):
        # The recheck takes only the LOCKED fair prob and price — there is no
        # parameter through which a current market number could enter.
        self.assertTrue(bar_recheck(0.60, 0.50, 1.909))


class TestPlanLineupReeval(unittest.TestCase):
    NOW = datetime(2026, 6, 23, 18, 0, tzinfo=timezone.utc)

    def test_unchanged_hash_is_no_op(self):
        rows = [reeval_row(stored="same", current="same", model=0.40)]
        self.assertEqual(plan_lineup_reeval(rows, self.NOW), [])

    def test_model_drop_bumps(self):
        rows = [reeval_row(model=0.52)]  # edge .02 at locked fair .50 → fails
        ops = plan_lineup_reeval(rows, self.NOW)
        self.assertEqual(ops, [("lineup_bump", 100, "bbb")])

    def test_player_out_bumps(self):
        rows = [reeval_row(model=OUT)]
        ops = plan_lineup_reeval(rows, self.NOW)
        self.assertEqual(ops, [("lineup_bump", 100, "bbb")])

    def test_still_clears_refreshes_hash(self):
        rows = [reeval_row(model=0.60)]
        ops = plan_lineup_reeval(rows, self.NOW)
        self.assertEqual(ops, [("refresh_hash", 100, "bbb")])

    def test_unknown_skips_without_hash_refresh(self):
        # No usable model number this tick → do nothing, so the next tick retries.
        rows = [reeval_row(model=UNKNOWN)]
        self.assertEqual(plan_lineup_reeval(rows, self.NOW), [])

    def test_started_game_is_frozen(self):
        rows = [reeval_row(model=0.40, start=self.NOW - timedelta(hours=1))]
        self.assertEqual(plan_lineup_reeval(rows, self.NOW), [])

    def test_unbump_when_lineup_restores(self):
        rows = [reeval_row(active=False, bump_reason="lineup", model=0.60)]
        ops = plan_lineup_reeval(rows, self.NOW)
        self.assertEqual(ops, [("unbump", 100, "bbb")])

    def test_unbump_respects_active_cap(self):
        actives = [reeval_row(pick_id=i, stored="s", current="s") for i in (1, 2, 3)]
        bumped = reeval_row(pick_id=4, active=False, bump_reason="lineup", model=0.60)
        ops = plan_lineup_reeval(actives + [bumped], self.NOW)
        # Board is full → the bumped row just notes the new lineup.
        self.assertEqual(ops, [("refresh_hash", 4, "bbb")])

    def test_bump_frees_slot_for_unbump_same_tick(self):
        actives = [reeval_row(pick_id=i, stored="s", current="s") for i in (1, 2)]
        failing = reeval_row(pick_id=3, model=OUT)
        restored = reeval_row(pick_id=4, active=False, bump_reason="lineup", model=0.60)
        ops = plan_lineup_reeval(actives + [failing, restored], self.NOW)
        self.assertIn(("lineup_bump", 3, "bbb"), ops)
        self.assertIn(("unbump", 4, "bbb"), ops)

    def test_displaced_legacy_rows_ignored(self):
        rows = [reeval_row(active=False, bump_reason="displaced", model=0.60)]
        self.assertEqual(plan_lineup_reeval(rows, self.NOW), [])

    def test_market_move_cannot_bump(self):
        # A market move changes NOTHING here: same lineup hash → no re-eval at all,
        # regardless of how far the current price has drifted from the locked one.
        rows = [reeval_row(stored="same", current="same", model=0.60, fair=0.50)]
        self.assertEqual(plan_lineup_reeval(rows, self.NOW), [])


class TestPoissonGameProbs(unittest.TestCase):
    """Parity with OddsModel: independent Poissons on a 0..30 grid."""

    def test_moneyline_symmetric(self):
        # Equal lambdas → pHomeWin = .5 exactly (ties split 50/50).
        self.assertAlmostEqual(
            poisson_game_prob("moneyline", "home", None, 4.5, 4.5), 0.5, places=9)
        home = poisson_game_prob("moneyline", "home", None, 5.2, 3.8)
        away = poisson_game_prob("moneyline", "away", None, 5.2, 3.8)
        self.assertGreater(home, 0.5)
        self.assertAlmostEqual(home + away, 1.0, places=9)

    def test_total_hand_value(self):
        # λh=λa=1: P(total > 1.5) = 1 − P(N=0) − P(N=1) with N ~ Poisson(2)
        #        = 1 − e⁻² − 2e⁻² = 1 − 3e⁻² ≈ 0.593994.
        over = poisson_game_prob("total", "over", 1.5, 1.0, 1.0)
        self.assertAlmostEqual(over, 1 - 3 * math.exp(-2), places=6)
        under = poisson_game_prob("total", "under", 1.5, 1.0, 1.0)
        self.assertAlmostEqual(over + under, 1.0, places=9)

    def test_run_line_signed_spread(self):
        # home −1.5 covers iff margin ≥ 2; away +1.5 covers iff away loses by ≤ 1 or wins.
        home_cover = poisson_game_prob("run_line", "home", -1.5, 5.0, 4.0)
        away_cover = poisson_game_prob("run_line", "away", 1.5, 5.0, 4.0)
        self.assertAlmostEqual(home_cover + away_cover, 1.0, places=9)
        # A big favorite covers −1.5 more often than a coin flip loses...
        self.assertGreater(poisson_game_prob("run_line", "home", -1.5, 7.0, 2.0), 0.5)

    def test_unknown_market_or_missing_line(self):
        self.assertIsNone(poisson_game_prob("total", "over", None, 4.0, 4.0))
        self.assertIsNone(poisson_game_prob("first_inning", "over", 0.5, 4.0, 4.0))


class TestSettleProp(unittest.TestCase):
    def test_pending_until_final(self):
        self.assertEqual(settle_prop(None, False, False), "pending")

    def test_grades_when_value_present(self):
        self.assertEqual(settle_prop(1, True, True), "grade")

    def test_void_on_dnp(self):
        # Game final, the game's player stats landed, our player has none → DNP.
        self.assertEqual(settle_prop(None, True, True), "void")

    def test_pending_when_stats_not_ingested(self):
        self.assertEqual(settle_prop(None, True, False), "pending")


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


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _FakeConn:
    """Stands in for a DB connection: serves cached verdicts, records no writes."""
    def __init__(self, cached):
        self.cached = cached  # {(game, market, side, player): verdict}

    def execute(self, sql, params=None):
        if sql.strip().startswith("SELECT verdict"):
            _slate, game, market, side, player = params
            v = self.cached.get((game, market, side, player))
            return _Result([(v,)] if v is not None else [])
        return _Result([])


class TestAnalystGate(unittest.TestCase):
    """gate_candidates promotes only bet/lean; pass demotes; None (gate off) promotes mechanically.
    INTERNAL_KEY is unset in tests, so an uncached candidate never hits the network (returns None)."""

    def test_pass_demotes_and_endorsed_promote(self):
        cands = [play(game_id=1), play(game_id=2), play(game_id=3)]
        conn = _FakeConn({
            (1, "hr", "over", 10): "pass",
            (2, "hr", "over", 10): "bet",
            (3, "hr", "over", 10): "lean",
        })
        picks = gate_candidates(conn, "http://x", "2026-06-29", cands)
        self.assertEqual([p["gameId"] for p in picks], [2, 3])

    def test_gate_off_promotes_mechanically(self):
        cands = [play(game_id=g) for g in (1, 2, 3, 4)]
        picks = gate_candidates(_FakeConn({}), "http://x", "2026-06-29", cands)
        # No cache, no key → all None → first MAX_PICKS promoted in order.
        self.assertEqual([p["gameId"] for p in picks], [1, 2, 3])

    def test_caps_at_max_picks(self):
        cands = [play(game_id=g) for g in (1, 2, 3, 4, 5)]
        conn = _FakeConn({(g, "hr", "over", 10): "bet" for g in (1, 2, 3, 4, 5)})
        picks = gate_candidates(conn, "http://x", "2026-06-29", cands)
        self.assertEqual(len(picks), MAX_PICKS)

    def test_build_candidates_wider_than_picks(self):
        plays = [play(game_id=g, model=0.60, fair=0.50, ev=0.10) for g in range(1, 7)]
        self.assertEqual(len(build_picks(plays, sim=None)), MAX_PICKS)
        self.assertEqual(len(build_candidates(plays, sim=None)), 6)


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
