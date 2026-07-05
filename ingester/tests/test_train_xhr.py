"""Tests for the pure feature-matrix builder of the xHR trainer (no sklearn/DB)."""
from __future__ import annotations

import math


from ingester.commands.train_xhr import build_xy, FEATURES


class TestBuildXy:
    def test_empty(self):
        X, y = build_xy([])
        assert list(X.columns) == FEATURES
        assert len(X) == 0 and len(y) == 0

    def test_basic_columns_and_target(self):
        rows = [
            {"launch_speed": 108.0, "launch_angle": 28.0, "spray_deg": -12.0,
             "park": "NYY", "is_hr": True},
            {"launch_speed": 85.0, "launch_angle": 5.0, "spray_deg": 3.0,
             "park": "BOS", "is_hr": False},
        ]
        X, y = build_xy(rows)
        assert list(X.columns) == FEATURES
        assert y.tolist() == [1, 0]
        assert X["launch_speed"].tolist() == [108.0, 85.0]
        assert str(X["park"].dtype) == "category"

    def test_nan_spray_preserved(self):
        # HRs without a hit-coordinate carry NaN spray — must survive (HistGBM handles it).
        rows = [{"launch_speed": 110.0, "launch_angle": 30.0, "spray_deg": None,
                 "park": "LAD", "is_hr": True}]
        X, y = build_xy(rows)
        assert math.isnan(X["spray_deg"].iloc[0])
        assert y.tolist() == [1]

    def test_null_is_hr_defaults_false(self):
        rows = [{"launch_speed": 90.0, "launch_angle": 10.0, "spray_deg": 0.0,
                 "park": "SF", "is_hr": None}]
        _, y = build_xy(rows)
        assert y.tolist() == [0]
