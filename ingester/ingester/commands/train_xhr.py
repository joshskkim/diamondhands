"""train-xhr: train the learned xHR model on batted_ball_events (Phase 2.2).

Learns P(HR | launch_speed, launch_angle, spray_deg, park) with a calibrated
HistGradientBoostingClassifier — chosen because it handles the NaN spray on
no-coordinate HRs and the categorical park natively, no imputation/one-hot.

Guardrails against the ML scar ([[live-blend-degeneracy]]):
  * batted-ball-level target (~130k rows/season) — hard to overfit 4 features.
  * LEAK-FREE temporal split: fit on prior seasons, isotonic-calibrate on a held-out
    slice of them, evaluate FULLY out-of-time on the target season.
  * mandatory isotonic calibration, with ECE reported before/after.
  * permutation-importance export for explainability (shap not installed).

Writes a joblib artifact + a metadata json to models/ (gitignored). This step only
produces/evaluates the artifact; it does NOT touch live projections.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ingester.db import eastern_today, get_connection
from ingester.metrics import (
    average_precision,
    calibration_buckets,
    expected_calibration_error,
    log_loss,
    roc_auc,
)

NUMERIC_FEATURES = ["launch_speed", "launch_angle", "spray_deg"]
CATEGORICAL_FEATURES = ["park"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

_DEFAULT_OUT = "models/xhr_gbm.pkl"


def build_xy(rows: list[dict]) -> tuple[pd.DataFrame, np.ndarray]:
    """Feature matrix + target from batted_ball_events rows (pure, unit-testable).

    Numeric features stay float with NaN preserved (HistGBM handles it); park is a
    pandas category. y is the is_hr target as int {0,1}.
    """
    df = pd.DataFrame(rows, columns=[*FEATURES, "is_hr"]) if rows else \
        pd.DataFrame(columns=[*FEATURES, "is_hr"])
    X = pd.DataFrame({
        "launch_speed": pd.to_numeric(df["launch_speed"], errors="coerce"),
        "launch_angle": pd.to_numeric(df["launch_angle"], errors="coerce"),
        "spray_deg": pd.to_numeric(df["spray_deg"], errors="coerce"),
        "park": df["park"].astype("category"),
    })
    y = df["is_hr"].fillna(False).astype(int).to_numpy()
    return X, y


def _load_events(conn, seasons: list[int]) -> list[dict]:
    rows = conn.execute(
        """
        SELECT launch_speed, launch_angle, spray_deg, park, is_hr
        FROM batted_ball_events
        WHERE season = ANY(%s)
        """,
        (seasons,),
    ).fetchall()
    return [
        {"launch_speed": r[0], "launch_angle": r[1], "spray_deg": r[2],
         "park": r[3], "is_hr": r[4]}
        for r in rows
    ]


def _eval(name: str, p: np.ndarray, y: np.ndarray) -> dict:
    pl, yl = p.tolist(), y.tolist()
    buckets = calibration_buckets(pl, yl, n_buckets=20)
    m = {
        "log_loss": round(log_loss(pl, yl), 5),
        "roc_auc": round(roc_auc(pl, yl), 4),
        "pr_auc": round(average_precision(pl, yl), 4),
        "ece": round(expected_calibration_error(buckets), 4),
        "base_rate": round(float(y.mean()), 4),
        "n": int(len(y)),
    }
    print(f"  {name:<18} logloss={m['log_loss']:.5f}  AUC={m['roc_auc']:.4f}  "
          f"PR-AUC={m['pr_auc']:.4f}  ECE={m['ece']:.4f}  (n={m['n']:,})")
    return m


def cmd_train_xhr(args: argparse.Namespace) -> None:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.isotonic import IsotonicRegression
    from sklearn.model_selection import train_test_split
    import joblib

    test_season = getattr(args, "test_season", None) or eastern_today().year
    conn = get_connection()
    try:
        if getattr(args, "train_seasons", None):
            train_seasons = [int(s) for s in args.train_seasons.split(",")]
        else:  # every season strictly before the test season (leak-free by construction)
            all_seasons = [r[0] for r in conn.execute(
                "SELECT DISTINCT season FROM batted_ball_events ORDER BY season"
            ).fetchall()]
            train_seasons = [s for s in all_seasons if s < test_season]
        if not train_seasons:
            raise SystemExit(f"No batted_ball_events seasons before {test_season} to train on.")

        print(f"[train-xhr] train seasons {train_seasons} → test season {test_season}")
        X_tr_all, y_tr_all = build_xy(_load_events(conn, train_seasons))
        X_te, y_te = build_xy(_load_events(conn, [test_season]))
        if len(y_te) == 0:
            raise SystemExit(f"No batted_ball_events rows for test season {test_season}.")
        print(f"[train-xhr] train n={len(y_tr_all):,} ({y_tr_all.mean():.3%} HR)  "
              f"test n={len(y_te):,} ({y_te.mean():.3%} HR)")
    finally:
        conn.close()

    # Split train into fit / calibration (calibration never seen by the GBM).
    X_fit, X_cal, y_fit, y_cal = train_test_split(
        X_tr_all, y_tr_all, test_size=0.2, random_state=0, stratify=y_tr_all
    )
    gbm = HistGradientBoostingClassifier(
        categorical_features=CATEGORICAL_FEATURES,
        learning_rate=0.05, max_iter=400, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0,
        early_stopping=True, validation_fraction=0.1, random_state=0,
    )
    gbm.fit(X_fit, y_fit)

    # Isotonic calibration fit on the held-out calibration slice (prior seasons only).
    p_cal = gbm.predict_proba(X_cal)[:, 1]
    iso = IsotonicRegression(out_of_bounds="clip").fit(p_cal, y_cal)

    def predict(X: pd.DataFrame) -> np.ndarray:
        return iso.transform(gbm.predict_proba(X)[:, 1])

    print("[train-xhr] out-of-time evaluation on the test season:")
    raw_te = gbm.predict_proba(X_te)[:, 1]
    cal_te = predict(X_te)
    metrics = {
        "test_raw": _eval("test (raw GBM)", raw_te, y_te),
        "test_calibrated": _eval("test (calibrated)", cal_te, y_te),
    }

    # Explainability: permutation importance on a capped sample of the test set.
    n_imp = min(20000, len(y_te))
    idx = np.random.RandomState(0).choice(len(y_te), n_imp, replace=False)
    imp = permutation_importance(
        gbm, X_te.iloc[idx], y_te[idx], n_repeats=5,
        random_state=0, scoring="neg_log_loss",
    )
    importances = sorted(
        ({"feature": f, "importance": round(float(m), 5)}
         for f, m in zip(FEATURES, imp.importances_mean)),
        key=lambda d: d["importance"], reverse=True,
    )
    print("[train-xhr] permutation importance (Δ neg-log-loss):")
    for row in importances:
        print(f"    {row['feature']:<14} {row['importance']:+.5f}")

    # Persist artifact (gitignored) + metadata.
    out = Path(getattr(args, "out", None) or _DEFAULT_OUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": gbm, "calibrator": iso, "features": FEATURES,
         "categorical_features": CATEGORICAL_FEATURES},
        out,
    )
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_seasons": train_seasons,
        "test_season": test_season,
        "features": FEATURES,
        "metrics": metrics,
        "permutation_importance": importances,
    }
    meta_path = out.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"[train-xhr] wrote {out} and {meta_path}")
