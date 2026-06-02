"""Machine-learning layer (v3 spike): per-batter-game feature rows, time-series CV,
and XGBoost models that (if they beat the mechanistic baseline) blend into projections.

Stage A (this iteration) builds the feature pipeline, the walk-forward CV harness, and a
single HR classifier, then STOPS to report whether CV Brier beats the ~0.105 baseline.
"""
