"""Tests for bullpen (relief) skill aggregation.

Synthetic terminal-PA frames with hand-computed expectations — no DB, no network.
"""
from __future__ import annotations

import pandas as pd

from ingester.statcast import agg_bullpen_vs_handedness
from ingester.commands.refresh_bullpen import compute_bullpen_skill_rows

# NYM=121, MIA=146 (arbitrary ids for the synthetic teams)
ABBREV_TO_ID = {"NYM": 121, "MIA": 146}


def _pa(at_bat_number, pitcher, topbot, events, stand="R", game_pk=1):
    """One synthetic terminal-PA row. HOME=NYM, AWAY=MIA throughout."""
    return {
        "game_pk": game_pk,
        "inning_topbot": topbot,
        "at_bat_number": at_bat_number,
        "pitcher": pitcher,
        "stand": stand,
        "events": events,
        "home_team": "NYM",
        "away_team": "MIA",
        "estimated_woba_using_speedangle": None,
        "woba_value": None,
    }


def _frame(rows):
    return pd.DataFrame(rows)


def test_starter_is_excluded_per_side():
    """The earliest at_bat_number pitcher on each side is the starter and is dropped."""
    rows = [
        # Top of inning => NYM (home) pitches. Starter throws first (abn=1).
        _pa(1, pitcher=900, topbot="Top", events="single"),   # starter, excluded
        _pa(5, pitcher=901, topbot="Top", events="strikeout"),  # reliever
        _pa(6, pitcher=901, topbot="Top", events="home_run"),   # reliever
        # Bot of inning => MIA (away) pitches.
        _pa(2, pitcher=800, topbot="Bot", events="walk"),     # starter, excluded
        _pa(7, pitcher=801, topbot="Bot", events="field_out"),  # reliever
    ]
    out = agg_bullpen_vs_handedness([_frame(rows)], ABBREV_TO_ID)
    by_team = {(r["team_id"], r["vs_hand"]): r for r in out}

    # NYM bullpen vs R: 2 reliever PAs (901), one K and one HR.
    nym = by_team[(121, "R")]
    assert nym["bf"] == 2
    assert nym["k_rate"] == 0.5
    assert nym["hr_per_pa"] == 0.5
    assert nym["hits_per_pa"] == 0.5  # the HR counts as a hit

    # MIA bullpen vs R: 1 reliever PA (801), a field_out.
    mia = by_team[(146, "R")]
    assert mia["bf"] == 1
    assert mia["k_rate"] == 0.0
    assert mia["hr_per_pa"] == 0.0
    assert mia["hits_per_pa"] == 0.0


def test_team_attribution_by_side():
    """Top => home team pitches; Bot => away team pitches."""
    rows = [
        _pa(1, pitcher=900, topbot="Top", events="single"),    # NYM starter
        _pa(2, pitcher=901, topbot="Top", events="single"),    # NYM reliever (home)
        _pa(1, pitcher=800, topbot="Bot", events="single"),    # MIA starter
        _pa(2, pitcher=801, topbot="Bot", events="single"),    # MIA reliever (away)
    ]
    out = agg_bullpen_vs_handedness([_frame(rows)], ABBREV_TO_ID)
    teams = {r["team_id"] for r in out}
    assert teams == {121, 146}


def test_handedness_split():
    """L and R relief PAs land in separate rows."""
    rows = [
        _pa(1, pitcher=900, topbot="Top", events="single", stand="R"),  # starter
        _pa(2, pitcher=901, topbot="Top", events="single", stand="L"),
        _pa(3, pitcher=901, topbot="Top", events="strikeout", stand="R"),
    ]
    out = agg_bullpen_vs_handedness([_frame(rows)], ABBREV_TO_ID)
    by_hand = {r["vs_hand"]: r for r in out}
    assert by_hand["L"]["bf"] == 1
    assert by_hand["R"]["bf"] == 1
    assert by_hand["R"]["k_rate"] == 1.0


def test_chunks_accumulate():
    """Per-chunk aggregation sums across chunks for the same team×hand."""
    chunk1 = _frame([
        _pa(1, pitcher=900, topbot="Top", events="single", game_pk=1),     # starter
        _pa(2, pitcher=901, topbot="Top", events="strikeout", game_pk=1),  # reliever
    ])
    chunk2 = _frame([
        _pa(1, pitcher=900, topbot="Top", events="single", game_pk=2),     # starter
        _pa(2, pitcher=902, topbot="Top", events="home_run", game_pk=2),   # reliever
    ])
    out = agg_bullpen_vs_handedness([chunk1, chunk2], ABBREV_TO_ID)
    nym = [r for r in out if r["team_id"] == 121][0]
    assert nym["bf"] == 2
    assert nym["k_rate"] == 0.5
    assert nym["hr_per_pa"] == 0.5


def test_min_bf_guard_filters_small_samples():
    """compute_bullpen_skill_rows drops team×hand below the BF minimum."""
    rows = [_pa(1, pitcher=900, topbot="Top", events="single")]  # only a starter
    rows += [
        _pa(i + 2, pitcher=901, topbot="Top", events="single")
        for i in range(3)  # 3 reliever PAs, well below MIN_BF_BULLPEN (50)
    ]
    out = compute_bullpen_skill_rows(2025, [_frame(rows)], ABBREV_TO_ID)
    assert out == []


def test_min_bf_guard_keeps_large_samples():
    """A team×hand at/above the BF minimum survives and carries season."""
    relief = [
        _pa(i + 2, pitcher=901, topbot="Top", events="strikeout")
        for i in range(60)
    ]
    rows = [_pa(1, pitcher=900, topbot="Top", events="single")] + relief
    out = compute_bullpen_skill_rows(2025, [_frame(rows)], ABBREV_TO_ID)
    assert len(out) == 1
    assert out[0]["team_id"] == 121
    assert out[0]["bf"] == 60
    assert out[0]["season"] == 2025
    assert out[0]["k_rate"] == 1.0


def test_unmapped_team_dropped():
    """A pitching team not in the abbrev map contributes nothing."""
    rows = [
        _pa(1, pitcher=900, topbot="Top", events="single"),
        _pa(2, pitcher=901, topbot="Top", events="single"),
    ]
    out = agg_bullpen_vs_handedness([_frame(rows)], {"MIA": 146})  # NYM missing
    assert out == []
