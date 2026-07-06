"""Tests for analyze-picks helpers (pure, no DB required)."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from ingester.commands.pick_analysis import (
    SliceAcc,
    american_to_decimal,
    classify_miss,
    classify_outcome,
    clv_histogram,
    edge_bucket,
    hours_to_close_bucket,
    mean_ci95,
    quartile_labels,
    shown_cohort,
    units_for,
    wilson_ci,
)

_ET = ZoneInfo("America/New_York")


class TestAmericanToDecimal:
    def test_plus(self):
        assert american_to_decimal(150) == pytest.approx(2.50)

    def test_minus(self):
        assert american_to_decimal(-120) == pytest.approx(1.8333, abs=1e-4)

    def test_even(self):
        assert american_to_decimal(100) == pytest.approx(2.0)


class TestOutcomeAndUnits:
    def test_win_loss(self):
        assert classify_outcome(True, 9.0) == "win"
        assert classify_outcome(False, 9.0) == "loss"

    def test_push_has_result_value(self):
        assert classify_outcome(None, 8.0) == "push"

    def test_void_has_none(self):
        assert classify_outcome(None, None) == "void"

    def test_units_mirror_track_record_service(self):
        # WIN pays decimal-1, LOSS -1, PUSH 0 — must match TrackRecordService.unitsFor.
        assert units_for("win", 150) == pytest.approx(1.5)
        assert units_for("win", -120) == pytest.approx(0.8333, abs=1e-4)
        assert units_for("loss", 150) == -1.0
        assert units_for("push", -110) == 0.0


class TestEdgeBucket:
    def test_bar_thresholds(self):
        # Aligned to MIN_EDGE .04 / STRONG_EDGE .06 / LONGSHOT_EDGE .08 / MAX_EDGE .15.
        assert edge_bucket(0.039) == "<.04"
        assert edge_bucket(0.04) == "[.04,.06)"
        assert edge_bucket(0.0599) == "[.04,.06)"
        assert edge_bucket(0.06) == "[.06,.08)"
        assert edge_bucket(0.08) == "[.08,.15]"
        assert edge_bucket(0.15) == "[.08,.15]"
        assert edge_bucket(0.151) == ">.15"


class TestWilsonCi:
    def test_empty(self):
        assert wilson_ci(0, 0) is None

    def test_contains_point_estimate(self):
        lo, hi = wilson_ci(3, 51)
        assert lo < 3 / 51 < hi

    def test_bounds(self):
        lo, hi = wilson_ci(0, 10)
        assert lo == 0.0 and 0 < hi < 0.35
        lo, hi = wilson_ci(10, 10)
        assert hi == 1.0 and 0.65 < lo < 1

    def test_narrows_with_n(self):
        lo1, hi1 = wilson_ci(5, 10)
        lo2, hi2 = wilson_ci(500, 1000)
        assert (hi2 - lo2) < (hi1 - lo1)


class TestMeanCi95:
    def test_empty(self):
        assert mean_ci95([]) is None

    def test_single_value_degenerate(self):
        assert mean_ci95([0.01]) == (0.01, 0.01, 0.01)

    def test_symmetric_around_mean(self):
        m, lo, hi = mean_ci95([-0.02, 0.0, 0.02])
        assert m == pytest.approx(0.0)
        assert lo == pytest.approx(-hi)


class TestClassifyMiss:
    def test_captured(self):
        assert classify_miss(0.01, -110, False) == "captured"
        assert classify_miss(0.0, None, False) == "captured"  # zero CLV is captured

    def test_one_sided_close(self):
        # _closing_quote found our side at close but not the opposite side.
        assert classify_miss(None, -115, False) == "one_sided"

    def test_line_moved(self):
        assert classify_miss(None, None, True) == "line_moved"

    def test_no_quote(self):
        assert classify_miss(None, None, False) == "no_quote"


class TestTimingCohorts:
    def test_morning_vs_intraday(self):
        nine_am = datetime(2026, 7, 1, 9, 5, tzinfo=_ET)
        assert shown_cohort(nine_am) == "morning"
        one_pm = datetime(2026, 7, 1, 13, 0, tzinfo=_ET)
        assert shown_cohort(one_pm) == "intraday"
        assert shown_cohort(None) == "unknown"

    def test_utc_input_converted_to_eastern(self):
        # 13:05 UTC = 9:05 ET in July (DST) — must classify as morning.
        utc = datetime(2026, 7, 1, 13, 5, tzinfo=timezone.utc)
        assert shown_cohort(utc) == "morning"

    def test_hours_to_close_bucket(self):
        shown = datetime(2026, 7, 1, 9, 0, tzinfo=_ET)
        assert hours_to_close_bucket(shown, datetime(2026, 7, 1, 11, 0, tzinfo=_ET)) == "<3h"
        assert hours_to_close_bucket(shown, datetime(2026, 7, 1, 13, 0, tzinfo=_ET)) == "3-6h"
        assert hours_to_close_bucket(shown, datetime(2026, 7, 1, 19, 0, tzinfo=_ET)) == "6-12h"
        assert hours_to_close_bucket(shown, datetime(2026, 7, 2, 9, 0, tzinfo=_ET)) == "12h+"
        assert hours_to_close_bucket(None, shown) == "unknown"


class TestQuartileLabels:
    def test_even_split(self):
        assert quartile_labels(8) == [0, 0, 1, 1, 2, 2, 3, 3]

    def test_remainder_goes_to_early_quartiles(self):
        labels = quartile_labels(10)
        assert len(labels) == 10
        assert [labels.count(q) for q in range(4)] == [3, 3, 2, 2]

    def test_empty(self):
        assert quartile_labels(0) == []


class TestClvHistogram:
    def test_bins_and_outliers(self):
        bins = clv_histogram([-0.06, -0.005, 0.0, 0.004, 0.049, 0.07])
        as_dict = dict(bins)
        assert as_dict["<-0.05"] == 1
        assert as_dict[">=+0.05"] == 1
        assert sum(c for _, c in bins) == 6
        # 0.0 and 0.004 share the [+0.00,+0.01) bin.
        assert as_dict["[+0.00,+0.01)"] == 2


class TestSliceAcc:
    def test_mirrors_track_record_math(self):
        a = SliceAcc("x")
        a.add("win", 1.5, 0.01)    # +150 winner that beat the close
        a.add("loss", -1.0, -0.02)
        a.add("push", 0.0, None)
        assert a.n == 3
        row = a.row()
        # label, n, W-L-P, win%, units, ROI, clvN, avgCLV, beat%, beat/tie%, ci, noCLV
        assert row[1] == "3"
        assert row[2] == "1-1-1"
        assert row[3] == "50.0%"      # decided-only
        assert row[4] == "+0.50"
        assert row[5] == "+16.7%"     # units / n
        assert row[6] == "2"
        assert row[7] == "-0.0050"
        assert row[11] == "1"

    def test_tie_counted_in_beat_or_tie_only(self):
        a = SliceAcc("x")
        a.add("win", 1.0, 0.0)
        row = a.row()
        assert row[8] == "0%"      # strict beat
        assert row[9] == "100%"    # beat-or-tie
