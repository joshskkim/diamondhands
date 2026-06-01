"""Tests for the pitch-mix matchup model (v2.1 Sprint 2, Part 2)."""
from __future__ import annotations

from datetime import date

import pytest

from ingester.projection.matchup import (
    QUALITY_FALLBACK,
    QUALITY_MATCHUP,
    ArsenalEntry,
    BatterPitchStat,
    combine_component,
    compute_matchup,
    empirical_bayes_regress,
)

AS_OF = date(2025, 6, 1)


def _bstat(xwoba=None, k_rate=None, iso=None, n=10_000) -> BatterPitchStat:
    return BatterPitchStat(xwoba=xwoba, k_rate=k_rate, iso=iso, pitches_seen=n)


class TestEmpiricalBayesRegress:
    def test_halfway_when_n_equals_k(self):
        # n == k → weight 0.5, exactly halfway between raw and league.
        assert empirical_bayes_regress(0.5, 100, 0.3, 100) == pytest.approx(0.4)

    def test_thin_sample_pulled_toward_league(self):
        # n << k → mostly league.
        assert empirical_bayes_regress(0.500, 10, 0.300, 100) == pytest.approx(
            0.500 * (10 / 110) + 0.300 * (100 / 110)
        )

    def test_none_collapses_to_league(self):
        assert empirical_bayes_regress(None, 50, 0.318, 100) == 0.318


class TestCombineComponent:
    def test_spec_example_full_coverage(self):
        # Pitcher: 60% FF, 40% SL. Batter .400 vs FF, .250 vs SL.
        # league set == raw so regression is a no-op → 0.6*.400 + 0.4*.250 = 0.340.
        arsenal = [ArsenalEntry("FF", 0.60, 1200), ArsenalEntry("SL", 0.40, 800)]
        stats = {"FF": _bstat(xwoba=0.400), "SL": _bstat(xwoba=0.250)}
        league = {"FF": 0.400, "SL": 0.250}
        value, covered = combine_component(arsenal, stats, league, 0.320, metric="xwoba")
        assert value == pytest.approx(0.340)
        assert covered == pytest.approx(1.0)

    def test_high_partial_coverage_normalizes_over_covered(self):
        # Only FF covered (usage 0.8 ≥ 0.6 threshold) → pure covered average, no overall.
        arsenal = [ArsenalEntry("FF", 0.80, 1000), ArsenalEntry("SL", 0.20, 200)]
        stats = {"FF": _bstat(xwoba=0.400)}
        value, covered = combine_component(arsenal, stats, {"FF": 0.400}, 0.300, metric="xwoba")
        assert value == pytest.approx(0.400)  # 0.8*0.4 / 0.8
        assert covered == pytest.approx(0.80)

    def test_low_partial_coverage_backfills_with_overall(self):
        # Only FF covered (usage 0.5 < 0.6) → backfill uncovered 0.5 with overall 0.300.
        arsenal = [ArsenalEntry("FF", 0.50, 600), ArsenalEntry("SL", 0.50, 600)]
        stats = {"FF": _bstat(xwoba=0.400)}
        value, covered = combine_component(arsenal, stats, {"FF": 0.400}, 0.300, metric="xwoba")
        assert value == pytest.approx(0.50 * 0.400 + 0.50 * 0.300)  # 0.35
        assert covered == pytest.approx(0.50)

    def test_no_coverage_returns_overall(self):
        arsenal = [ArsenalEntry("FF", 0.60, 1200)]
        value, covered = combine_component(arsenal, {}, {}, 0.318, metric="xwoba")
        assert value == 0.318
        assert covered == 0.0


# ── compute_matchup with a fake connection ──────────────────────────────────
class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, arsenal, batter, baselines):
        self._arsenal = arsenal
        self._batter = batter
        self._baselines = baselines

    def execute(self, sql, params=None):
        if "FROM pitcher_arsenal" in sql:
            return _Result(self._arsenal)
        if "FROM batter_pitch_type_stats" in sql:
            return _Result(self._batter)
        if "FROM pitch_type_league_baselines" in sql:
            return _Result(self._baselines)
        raise AssertionError(f"unexpected query: {sql[:60]}")


def _matchup(conn):
    return compute_matchup(
        conn,
        batter_id=1, pitcher_id=2,
        batter_hand="R", pitcher_hand="R",
        as_of_date=AS_OF, season=2025,
        overall_xwoba=0.320, overall_k_rate=0.220, overall_iso=0.150,
    )


class TestComputeMatchup:
    def test_fallback_when_no_arsenal(self):
        res = _matchup(_FakeConn(arsenal=[], batter=[], baselines=[]))
        assert res.quality == QUALITY_FALLBACK
        assert (res.xwoba, res.k_rate, res.iso) == (0.320, 0.220, 0.150)

    def test_fallback_when_arsenal_too_thin(self):
        # 60 + 30 = 90 pitches < MATCHUP_MIN_ARSENAL_PITCHES (100).
        arsenal = [("FF", 0.67, 60), ("SL", 0.33, 30)]
        res = _matchup(_FakeConn(arsenal=arsenal, batter=[], baselines=[]))
        assert res.quality == QUALITY_FALLBACK

    def test_matchup_happy_path(self):
        # 120 FF + 80 SL = 200 pitches. Batter .400/.250 xwOBA; league == raw.
        arsenal = [("FF", 0.60, 120), ("SL", 0.40, 80)]
        batter = [
            # pitch_type, xwoba, k_rate, iso, pitches_seen
            ("FF", 0.400, 0.200, 0.180, 1500),
            ("SL", 0.250, 0.350, 0.090, 600),
        ]
        baselines = [
            ("FF", "R", 0.400, 0.200, 0.180),
            ("SL", "R", 0.250, 0.350, 0.090),
        ]
        res = _matchup(_FakeConn(arsenal, batter, baselines))
        assert res.quality == QUALITY_MATCHUP
        assert res.xwoba == pytest.approx(0.340, abs=1e-4)   # 0.6*.4 + 0.4*.25
        assert res.k_rate == pytest.approx(0.260, abs=1e-4)  # 0.6*.2 + 0.4*.35
        assert res.iso == pytest.approx(0.144, abs=1e-4)     # 0.6*.18 + 0.4*.09
