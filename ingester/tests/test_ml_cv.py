"""Walk-forward CV must never leak the future into the past."""
from __future__ import annotations

import pandas as pd

from ingester.ml.cv import walk_forward_folds


def _season_dates(n=400):
    # ~6 months of daily games, several rows per day.
    days = pd.date_range("2025-04-01", "2025-09-28", freq="D")
    return pd.Series([days[i % len(days)] for i in range(n)])


def test_train_strictly_precedes_validation():
    dates = _season_dates(600)
    folds = walk_forward_folds(dates, n_folds=4)
    assert len(folds) == 4
    for tr_idx, val_idx in folds:
        train_max = dates.iloc[tr_idx].max()
        val_min = dates.iloc[val_idx].min()
        assert train_max < val_min, f"leak: train_max {train_max} >= val_min {val_min}"


def test_expanding_window_train_grows():
    dates = _season_dates(600)
    folds = walk_forward_folds(dates, n_folds=4)
    sizes = [len(tr) for tr, _ in folds]
    assert sizes == sorted(sizes)  # each fold trains on at least as much as the prior
    assert all(len(val) > 0 for _, val in folds)


def test_same_day_rows_not_split_across_train_val():
    dates = _season_dates(600)
    for tr_idx, val_idx in walk_forward_folds(dates, n_folds=4):
        train_days = set(dates.iloc[tr_idx].dt.normalize())
        val_days = set(dates.iloc[val_idx].dt.normalize())
        assert train_days.isdisjoint(val_days)


def test_degenerate_inputs():
    assert walk_forward_folds(pd.Series([], dtype="datetime64[ns]"), n_folds=4) == []
    assert walk_forward_folds(_season_dates(10), n_folds=0) == []
