"""Tests for batter platoon-split aggregation (U5).

Synthetic PA-level frames with hand-computed expectations — no DB, no network.
The aggregation splits a batter by the OPPOSING PITCHER's throwing hand
(`p_throws`), producing batter_platoon_skill rows.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ingester.commands.refresh_skills import (
    MIN_PA_PLATOON,
    compute_batter_platoon_rows,
)
from ingester.projection.constants import (
    LEAGUE_ISO,
    LEAGUE_K_PER_PA,
    LEAGUE_XWOBA,
    REGRESSION_K_PA,
)
from ingester.statcast import agg_batter_vs_pitcher_hand

SEASON = 2025


def _pa(event: str, *, p_throws: str, xwoba: float, batter: int = 100,
        game_date: str = "2025-05-01") -> dict:
    """One synthetic terminal-PA row (events set → counts as a PA)."""
    return {
        "batter": batter,
        "p_throws": p_throws,
        "stand": "L",
        "events": event,
        "estimated_woba_using_speedangle": xwoba,
        "woba_value": xwoba,
        "game_date": game_date,
    }


def _block(p_throws: str, *, batter: int, n: int) -> list[dict]:
    """n PAs vs a given pitcher hand: 1/5 HR, 1/5 single, 1/5 K, 2/5 field_out.

    Per PA: TB = (4 + 1)/5 = 1.0; H = 2/5; AB = all 5 events are AB events.
    iso = (TB - H) / AB = (5n - 2*(n/5)*... )  computed explicitly in tests.
    """
    rows: list[dict] = []
    unit = n // 5
    rows += [_pa("home_run", p_throws=p_throws, xwoba=2.0, batter=batter) for _ in range(unit)]
    rows += [_pa("single", p_throws=p_throws, xwoba=0.9, batter=batter) for _ in range(unit)]
    rows += [_pa("strikeout", p_throws=p_throws, xwoba=0.0, batter=batter) for _ in range(unit)]
    rows += [_pa("field_out", p_throws=p_throws, xwoba=0.0, batter=batter) for _ in range(2 * unit)]
    return rows


class TestAggBatterVsPitcherHand:
    def test_raw_split_counts_and_rates(self):
        # 25 PA vs RHP (p_throws='R'): 5 HR, 5 1B, 5 K, 10 field_out.
        df = pd.DataFrame(_block("R", batter=100, n=25))
        rows = agg_batter_vs_pitcher_hand([df])
        r = next(x for x in rows if x["player_id"] == 100 and x["vs_hand"] == "R")

        assert r["pa"] == 25
        assert r["k_rate"] == 0.2  # 5 K / 25 PA
        # xwoba = (5*2.0 + 5*0.9) / 25 = 14.5/25 = 0.58
        assert r["xwoba"] == 0.58
        # TB = 5*4 + 5*1 = 25; H = 10; AB = 25 → iso = (25-10)/25 = 0.6
        assert r["iso"] == 0.6

    def test_split_by_pitcher_hand(self):
        # Same batter, two hands — must produce two distinct rows.
        df = pd.DataFrame(_block("R", batter=100, n=25) + _block("L", batter=100, n=25))
        rows = agg_batter_vs_pitcher_hand([df])
        hands = {x["vs_hand"] for x in rows if x["player_id"] == 100}
        assert hands == {"L", "R"}

    def test_ignores_unknown_hand(self):
        df = pd.DataFrame(
            _block("R", batter=100, n=25)
            + [_pa("single", p_throws="", xwoba=0.9, batter=100)]
        )
        rows = agg_batter_vs_pitcher_hand([df])
        # The blank-hand PA is dropped; only the 25 'R' PAs remain.
        assert {x["vs_hand"] for x in rows} == {"R"}
        assert next(x for x in rows if x["vs_hand"] == "R")["pa"] == 25


class TestComputeBatterPlatoonRows:
    def test_below_min_pa_dropped(self):
        # 20 PA vs L (< MIN_PA_PLATOON) alongside 25 vs R (qualifies).
        assert MIN_PA_PLATOON == 25
        df = pd.DataFrame(_block("R", batter=100, n=25) + _block("L", batter=100, n=20))
        rows = compute_batter_platoon_rows(SEASON, [df])
        hands = {x["vs_hand"] for x in rows if x["player_id"] == 100}
        assert hands == {"R"}

    def test_regression_toward_league_mean(self):
        # A 25-PA split is regressed hard toward league: weight = 25/(25+K).
        df = pd.DataFrame(_block("R", batter=100, n=25))
        rows = compute_batter_platoon_rows(SEASON, [df])
        r = next(x for x in rows if x["player_id"] == 100 and x["vs_hand"] == "R")

        assert r["season"] == SEASON
        weight = 25 / (25 + REGRESSION_K_PA)
        exp_xwoba = round(weight * 0.58 + (1 - weight) * LEAGUE_XWOBA, 4)
        exp_k = round(weight * 0.2 + (1 - weight) * LEAGUE_K_PER_PA, 4)
        exp_iso = round(weight * 0.6 + (1 - weight) * LEAGUE_ISO, 4)
        assert r["xwoba"] == exp_xwoba
        assert r["k_rate"] == exp_k
        assert r["iso"] == exp_iso
        # Regressed xwoba sits between raw (0.58) and league (0.318).
        assert LEAGUE_XWOBA < r["xwoba"] < 0.58

    def test_cutoff_excludes_future_pas(self):
        # 25 May PAs (kept) + 30 July PAs (excluded by the June-1 cutoff).
        may = pd.DataFrame(_block("R", batter=100, n=25))
        july = pd.DataFrame(
            [_pa("single", p_throws="R", xwoba=0.9, batter=100, game_date="2025-07-04")
             for _ in range(30)]
        )
        rows = compute_batter_platoon_rows(
            SEASON, [may, july], cutoff_date=date(2025, 6, 1),
        )
        r = next(x for x in rows if x["player_id"] == 100 and x["vs_hand"] == "R")
        assert r["pa"] == 25  # July PAs excluded by cutoff

    def test_known_platoon_gap(self):
        # Lefty bat: strong vs RHP, weak vs LHP. Both above the PA floor.
        strong = [_pa("home_run", p_throws="R", xwoba=2.0, batter=7) for _ in range(10)]
        strong += [_pa("single", p_throws="R", xwoba=0.9, batter=7) for _ in range(20)]
        strong += [_pa("field_out", p_throws="R", xwoba=0.0, batter=7) for _ in range(20)]
        weak = [_pa("strikeout", p_throws="L", xwoba=0.0, batter=7) for _ in range(25)]
        weak += [_pa("field_out", p_throws="L", xwoba=0.0, batter=7) for _ in range(25)]
        rows = compute_batter_platoon_rows(SEASON, [pd.DataFrame(strong + weak)])
        by_hand = {x["vs_hand"]: x for x in rows if x["player_id"] == 7}
        assert by_hand["R"]["xwoba"] > by_hand["L"]["xwoba"]
        assert by_hand["R"]["iso"] > by_hand["L"]["iso"]
