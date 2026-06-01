"""Tests for backtest metric functions (pure, no DB required)."""
from __future__ import annotations

import math
import pytest

from ingester.commands.backtest import (
    brier_score,
    baseline_brier,
    calibration_buckets,
    mae_per_game,
)


# ---------------------------------------------------------------------------
# brier_score
# ---------------------------------------------------------------------------

class TestBrierScore:
    def test_perfect_predictions(self):
        # All correct: predicted 1.0 for actuals=1, predicted 0.0 for actuals=0
        pred = [1.0, 0.0, 1.0, 0.0]
        actual = [1, 0, 1, 0]
        assert brier_score(pred, actual) == pytest.approx(0.0)

    def test_worst_predictions(self):
        # All wrong: predicted 1.0 when actual=0, predicted 0.0 when actual=1
        pred = [1.0, 0.0, 1.0, 0.0]
        actual = [0, 1, 0, 1]
        assert brier_score(pred, actual) == pytest.approx(1.0)

    def test_hand_computed_example(self):
        # Single batter: predicted 0.7, actual 1
        # Brier = (0.7 - 1)^2 = 0.09
        assert brier_score([0.7], [1]) == pytest.approx(0.09)

    def test_two_predictions(self):
        # (0.3 - 0)^2 + (0.7 - 1)^2 = 0.09 + 0.09 = 0.18; mean = 0.09
        assert brier_score([0.3, 0.7], [0, 1]) == pytest.approx(0.09)

    def test_empty_returns_nan(self):
        assert math.isnan(brier_score([], []))

    def test_constant_half_prediction(self):
        # Always predict 0.5: Brier = 0.25 regardless of outcomes
        pred = [0.5, 0.5, 0.5, 0.5]
        actual = [0, 0, 1, 1]
        assert brier_score(pred, actual) == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# baseline_brier
# ---------------------------------------------------------------------------

class TestBaselineBrier:
    def test_half_rate(self):
        # rate = 0.5 → baseline = 0.5 * 0.5 = 0.25
        actual = [0, 1, 0, 1]
        assert baseline_brier(actual) == pytest.approx(0.25)

    def test_all_zeros(self):
        # rate = 0.0 → baseline = 0.0
        assert baseline_brier([0, 0, 0]) == pytest.approx(0.0)

    def test_all_ones(self):
        # rate = 1.0 → baseline = 0.0
        assert baseline_brier([1, 1, 1]) == pytest.approx(0.0)

    def test_typical_hit_rate(self):
        # Approx 22.5% hit rate: baseline ≈ 0.225 * 0.775 ≈ 0.1744
        actual = [1] * 9 + [0] * 31  # 9/40 = 0.225
        expected = 0.225 * (1 - 0.225)
        assert baseline_brier(actual) == pytest.approx(expected, rel=1e-6)

    def test_empty_returns_nan(self):
        assert math.isnan(baseline_brier([]))


# ---------------------------------------------------------------------------
# calibration_buckets
# ---------------------------------------------------------------------------

class TestCalibrationBuckets:
    def test_empty_input(self):
        assert calibration_buckets([], []) == []

    def test_single_bucket_populated(self):
        # All predictions around 0.15 → should land in bucket [0.1, 0.2)
        pred = [0.12, 0.15, 0.18]
        actual = [0, 1, 1]
        buckets = calibration_buckets(pred, actual)
        assert len(buckets) == 1
        b = buckets[0]
        assert b["lo"] == pytest.approx(0.1)
        assert b["hi"] == pytest.approx(0.2)
        assert b["n"] == 3
        assert b["predicted_mean"] == pytest.approx((0.12 + 0.15 + 0.18) / 3, rel=1e-3)
        assert b["actual_rate"] == pytest.approx(2 / 3, rel=1e-3)

    def test_last_bucket_includes_one(self):
        # prediction = 1.0 should be in the last bucket [0.9, 1.0]
        pred = [1.0]
        actual = [1]
        buckets = calibration_buckets(pred, actual)
        assert len(buckets) == 1
        assert buckets[0]["lo"] == pytest.approx(0.9)
        assert buckets[0]["hi"] == pytest.approx(1.0)

    def test_empty_buckets_omitted(self):
        # Two predictions far apart → 2 buckets, middle buckets omitted
        pred = [0.05, 0.95]
        actual = [0, 1]
        buckets = calibration_buckets(pred, actual)
        assert len(buckets) == 2
        los = [b["lo"] for b in buckets]
        assert 0.0 in los
        assert 0.9 in los

    def test_split_across_two_buckets(self):
        pred = [0.05, 0.15]
        actual = [1, 0]
        buckets = calibration_buckets(pred, actual)
        assert len(buckets) == 2
        for b in buckets:
            assert b["n"] == 1

    def test_actual_rate_and_predicted_mean_keys_present(self):
        # Both land in [0.3, 0.4) → single bucket
        pred = [0.32, 0.37]
        actual = [0, 1]
        buckets = calibration_buckets(pred, actual)
        assert len(buckets) == 1
        b = buckets[0]
        assert "actual_rate" in b
        assert "predicted_mean" in b
        assert "n" in b
        assert "lo" in b
        assert "hi" in b

    def test_custom_n_buckets(self):
        # 5 buckets → width = 0.2
        pred = [0.1, 0.5, 0.9]
        actual = [0, 1, 1]
        buckets = calibration_buckets(pred, actual, n_buckets=5)
        # 0.1 → bucket [0.0, 0.2), 0.5 → [0.4, 0.6), 0.9 → [0.8, 1.0]
        assert len(buckets) == 3
        assert all(b["hi"] - b["lo"] == pytest.approx(0.2) for b in buckets)


# ---------------------------------------------------------------------------
# mae_per_game
# ---------------------------------------------------------------------------

class TestMaePerGame:
    def test_empty_returns_nan(self):
        assert math.isnan(mae_per_game({}))

    def test_perfect_match(self):
        # Expected and actual exactly equal for all games
        game_hits = {1: (3.5, 3), 2: (2.0, 2), 3: (4.0, 4)}
        # errors: |3.5-3|=0.5, |2.0-2|=0.0, |4.0-4|=0.0 → mean=0.5/3
        assert mae_per_game(game_hits) == pytest.approx(0.5 / 3, rel=1e-6)

    def test_single_game(self):
        # Expected 2.7, actual 3 → error = 0.3
        assert mae_per_game({42: (2.7, 3)}) == pytest.approx(0.3, rel=1e-6)

    def test_symmetric_errors(self):
        # One game over, one under by same amount
        game_hits = {1: (5.0, 3), 2: (3.0, 5)}  # |5-3|=2, |3-5|=2 → MAE=2
        assert mae_per_game(game_hits) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Integration: single-batter hand-computed scenario
# ---------------------------------------------------------------------------

class TestSingleBatterIntegration:
    """
    Feed one predicted/actual pair and verify Brier + calibration are consistent.
    Predicted: 0.7 (hit1plus), Actual: 1
    Expected Brier = (0.7 - 1)^2 = 0.09
    Expected baseline Brier = 1.0 * (1 - 1.0) = 0.0  (100% actual rate)
    Expected calibration: single bucket at [0.6, 0.7), n=1, pred_mean=0.7, actual_rate=1.0
    """

    def setup_method(self):
        self.pred = [0.7]
        self.actual = [1]

    def test_brier_single_batter(self):
        assert brier_score(self.pred, self.actual) == pytest.approx(0.09)

    def test_baseline_single_batter(self):
        # All actuals = 1 → rate = 1.0 → baseline = 0.0
        assert baseline_brier(self.actual) == pytest.approx(0.0)

    def test_calibration_single_batter(self):
        buckets = calibration_buckets(self.pred, self.actual)
        assert len(buckets) == 1
        b = buckets[0]
        assert b["lo"] == pytest.approx(0.6)
        assert b["hi"] == pytest.approx(0.7)
        assert b["n"] == 1
        assert b["predicted_mean"] == pytest.approx(0.7)
        assert b["actual_rate"] == pytest.approx(1.0)

    def test_mae_single_game(self):
        # expected_hits = 0.7, actual_hits = 1 → error = 0.3
        game_hits = {1: (0.7, 1)}
        assert mae_per_game(game_hits) == pytest.approx(0.3, rel=1e-6)
