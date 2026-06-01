"""Tests for pitch-level aggregation (v2.1 Sprint 2, Part 1).

Synthetic pitch-level frames with hand-computed expectations — no DB, no network.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ingester.statcast_pitch import (
    MIN_PITCHES_BATTER,
    MIN_PITCHES_PITCHER,
    aggregate_batter_pitch_stats,
    aggregate_pitcher_arsenal,
    compute_league_baselines,
    normalize_pitch_type,
)

SEASON = 2025
AS_OF = date(2025, 6, 1)


def _pitch(**kw) -> dict:
    """One synthetic Statcast pitch row with sensible defaults."""
    row = {
        "pitch_type": "FF",
        "game_date": "2025-05-01",
        "stand": "R",
        "p_throws": "R",
        "description": "ball",
        "release_speed": 94.0,
        "events": None,
        "estimated_woba_using_speedangle": None,
        "woba_value": None,
        "woba_denom": None,
        "batter": 100,
        "pitcher": 200,
    }
    row.update(kw)
    return row


def _terminal(event: str, *, desc: str, xwoba: float | None, **kw) -> dict:
    """A PA-ending pitch with woba_denom=1 and a given estimated xwOBA."""
    return _pitch(
        events=event,
        description=desc,
        estimated_woba_using_speedangle=xwoba,
        woba_value=xwoba if xwoba is not None else 0.0,
        woba_denom=1.0,
        **kw,
    )


# ── batter FF block: 40 pitches, 10 PA-ending, vs RHP ───────────────────────
def _batter_ff_block(batter: int = 100) -> list[dict]:
    rows: list[dict] = []
    # 30 non-terminal: 10 called_strike, 10 ball, 10 foul (foul = a swing)
    rows += [_pitch(batter=batter, description="called_strike") for _ in range(10)]
    rows += [_pitch(batter=batter, description="ball") for _ in range(10)]
    rows += [_pitch(batter=batter, description="foul") for _ in range(10)]
    # 10 terminal: 4 singles, 1 HR, 2 field_out (all hit_into_play = swings),
    # 3 strikeouts (swinging_strike = swing + whiff)
    rows += [_terminal("single", desc="hit_into_play", xwoba=0.9, batter=batter) for _ in range(4)]
    rows += [_terminal("home_run", desc="hit_into_play", xwoba=2.0, batter=batter)]
    rows += [_terminal("field_out", desc="hit_into_play", xwoba=0.0, batter=batter) for _ in range(2)]
    rows += [_terminal("strikeout", desc="swinging_strike", xwoba=0.0, batter=batter) for _ in range(3)]
    return rows


class TestNormalizePitchType:
    @pytest.mark.parametrize("raw,expected", [
        ("FF", "FF"), ("FA", "FF"),
        ("SI", "SI"), ("FT", "SI"),
        ("FC", "FC"),
        ("SL", "SL"), ("ST", "SL"),
        ("CU", "CU"), ("KC", "CU"),
        ("CH", "CH"),
        ("FS", "FS"),
        ("ff", "FF"), (" sl ", "SL"),  # case / whitespace tolerant
    ])
    def test_known_codes(self, raw, expected):
        assert normalize_pitch_type(raw) == expected

    @pytest.mark.parametrize("raw", ["KN", "EP", "SC", "PO", "UN", "", None])
    def test_dropped_codes(self, raw):
        assert normalize_pitch_type(raw) is None


class TestAggregateBatterPitchStats:
    def test_ff_block_counts_and_rates(self):
        df = pd.DataFrame(_batter_ff_block())
        rows = aggregate_batter_pitch_stats(df, AS_OF, SEASON)

        # All pitchers are RHP → 'R' and 'A' rows, never 'L'.
        ff_r = next(r for r in rows if r["pitch_type"] == "FF" and r["vs_handedness"] == "R")
        assert ff_r["pitches_seen"] == 40
        assert ff_r["pa_ended_on_type"] == 10
        assert ff_r["k_rate"] == 0.3          # 3 K / 10 PA
        assert ff_r["hr_rate"] == 0.1         # 1 HR / 10 PA
        assert ff_r["iso"] == 0.3             # (TB 8 - H 5) / AB 10
        assert ff_r["xwoba"] == 0.56          # (3.6 + 2.0) / 10
        assert ff_r["swing_rate"] == 0.5      # (10 foul + 7 HIP + 3 SS) / 40
        assert ff_r["whiff_rate"] == 0.15     # 3 whiffs / 20 swings

        assert not any(r["vs_handedness"] == "L" for r in rows)
        assert any(r["vs_handedness"] == "A" for r in rows)

    def test_below_min_pitches_dropped(self):
        # 20 SL pitches (< MIN_PITCHES_BATTER) alongside the 40-pitch FF block.
        df = pd.DataFrame(
            _batter_ff_block()
            + [_pitch(pitch_type="SL", description="ball") for _ in range(20)]
        )
        rows = aggregate_batter_pitch_stats(df, AS_OF, SEASON)
        assert MIN_PITCHES_BATTER == 30
        assert not any(r["pitch_type"] == "SL" for r in rows)
        assert any(r["pitch_type"] == "FF" for r in rows)

    def test_as_of_date_excludes_future_pitches(self):
        df = pd.DataFrame(
            _batter_ff_block()
            + [_pitch(pitch_type="FF", game_date="2025-07-04") for _ in range(40)]
        )
        rows = aggregate_batter_pitch_stats(df, AS_OF, SEASON)
        ff_r = next(r for r in rows if r["pitch_type"] == "FF" and r["vs_handedness"] == "R")
        assert ff_r["pitches_seen"] == 40  # July pitches excluded by as_of 2025-06-01


class TestAggregatePitcherArsenal:
    def test_usage_rates_vs_rhb(self):
        # Pitcher 200 vs RHB: 60 FF + 50 SL = 110 pitches (both above the 50 floor).
        df = pd.DataFrame(
            [_pitch(pitcher=200, pitch_type="FF", stand="R") for _ in range(60)]
            + [_pitch(pitcher=200, pitch_type="SL", stand="R", release_speed=85.0) for _ in range(50)]
        )
        rows = aggregate_pitcher_arsenal(df, AS_OF, SEASON)
        ff = next(r for r in rows if r["pitch_type"] == "FF" and r["vs_handedness"] == "R")
        sl = next(r for r in rows if r["pitch_type"] == "SL" and r["vs_handedness"] == "R")
        assert ff["pitches_thrown"] == 60
        assert ff["usage_rate"] == round(60 / 110, 4)
        assert sl["usage_rate"] == round(50 / 110, 4)
        assert ff["avg_velocity"] == 94.0
        assert sl["avg_velocity"] == 85.0
        assert MIN_PITCHES_PITCHER == 50

    def test_below_min_pitches_dropped(self):
        df = pd.DataFrame([_pitch(pitcher=200, pitch_type="FF") for _ in range(40)])
        assert aggregate_pitcher_arsenal(df, AS_OF, SEASON) == []


class TestLeagueBaselines:
    def test_baseline_rows_present(self):
        df = pd.DataFrame(_batter_ff_block())
        rows = compute_league_baselines(df, SEASON, AS_OF)
        ff_r = next(r for r in rows if r["pitch_type"] == "FF" and r["vs_handedness"] == "R")
        assert ff_r["league_xwoba"] == 0.56
        assert ff_r["league_k_rate"] == 0.3
        assert ff_r["league_usage_rate"] == 1.0  # only FF in this frame
        assert any(r["vs_handedness"] == "A" for r in rows)
