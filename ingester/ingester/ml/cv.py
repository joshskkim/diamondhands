"""Walk-forward (expanding-window) time-series cross-validation, split by date.

Baseball is temporal, so folds must never let a future game inform a past one. Each fold
trains on all rows strictly before a time boundary and validates on the next time segment,
guaranteeing ``max(train game_date) < min(val game_date)``. Same-day rows are never split
across train/val (the boundary is exclusive on the train side).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def walk_forward_folds(game_dates, n_folds: int = 4) -> list[tuple[np.ndarray, np.ndarray]]:
    """Yield ``(train_idx, val_idx)`` index arrays for expanding-window folds.

    Boundaries are evenly spaced time-quantiles of the dates, producing ``n_folds``
    forward validation segments. Folds with an empty train or val side are dropped.
    """
    s = pd.to_datetime(pd.Series(list(game_dates))).reset_index(drop=True)
    if s.empty or n_folds < 1:
        return []

    # n_folds boundaries at quantiles 1/(n+1) .. n/(n+1); each fold validates the segment
    # [bound_i, bound_{i+1}) and trains on everything before bound_i.
    quantiles = [(i + 1) / (n_folds + 1) for i in range(n_folds)]
    bounds = [s.quantile(q) for q in quantiles]

    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i, lower in enumerate(bounds):
        train_idx = s.index[s < lower].to_numpy()
        if i + 1 < len(bounds):
            upper = bounds[i + 1]
            val_idx = s.index[(s >= lower) & (s < upper)].to_numpy()
        else:
            val_idx = s.index[s >= lower].to_numpy()
        if len(train_idx) and len(val_idx):
            folds.append((train_idx, val_idx))
    return folds
