"""train-pa: per-PA multiclass outcome model (spike for the per-PA → game architecture).

Each batter-game is expanded into weighted class rows {out, K, BB, non-HR hit, HR}
(weight = count of that outcome in the game), and a multi:softprob model learns the per-PA
outcome distribution. The four binary markets are then derived from the per-PA probabilities
via the binomial over expected PA, and scored with walk-forward OOF Brier — directly
comparable to the direct game-level XGBoost classifiers.

Hypothesis to test: does modeling at the PA level (then aggregating) beat the direct
game-level XGB? (Likely not for binary props — aggregation tends toward the binomial — but
worth knowing; the per-PA model's real value would be runs/totals, which need richer data.)
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import xgboost as xgb

from ingester.commands.backtest import baseline_brier, brier_score
from ingester.ml.cv import walk_forward_folds
from ingester.ml.dataset import MODELS_DIR
from ingester.ml.features import FEATURE_COLUMNS

# class index → outcome (order matters: must match the count columns built below)
_CLASS_ORDER = ["out", "k", "bb", "hit", "hr"]
# XGB direct-classifier OOF margins vs the naive baseline (2023-25 multiseason), for reference.
_XGB_VS_NAIVE = {"h1": 0.0155, "h2": 0.0060, "hr": 0.0023, "k": 0.0166}


def _load(seasons: list[int]) -> pd.DataFrame:
    frames = [pd.read_parquet(MODELS_DIR / f"training_{s}.parquet") for s in seasons]
    return pd.concat(frames, ignore_index=True).sort_values("game_date").reset_index(drop=True)


def _class_counts(df: pd.DataFrame) -> np.ndarray:
    """n_games x 5 array of outcome counts in column order _CLASS_ORDER (sums to PA)."""
    c_k = df["n_k"].to_numpy()
    c_bb = df["n_bb"].to_numpy()
    c_hr = df["n_hr"].to_numpy()
    c_hit = np.clip(df["n_hit"].to_numpy() - c_hr, 0, None)            # non-HR hits
    c_out = np.clip(df["pa"].to_numpy() - c_k - c_bb - c_hr - c_hit, 0, None)
    return np.column_stack([c_out, c_k, c_bb, c_hit, c_hr]).astype("float64")


def _expand(X: pd.DataFrame, counts: np.ndarray):
    """5 weighted rows per game (one per class, weight = count); drop zero-weight rows."""
    n = len(X)
    Xr = pd.concat([X] * 5, ignore_index=True)
    y = np.repeat(np.arange(5), n)
    w = counts.T.reshape(-1)  # class-major: [out(all games), k(all), ...]
    mask = w > 0
    return Xr[mask], y[mask], w[mask]


def _markets_from_pa(probs: np.ndarray, expected_pa: np.ndarray) -> dict[str, np.ndarray]:
    """Aggregate per-PA class probs (n x 5) to per-game market probabilities via binomial."""
    p_k = probs[:, 1]
    p_hr = probs[:, 4]
    p_hit = probs[:, 3] + probs[:, 4]  # any hit (non-HR + HR)
    N = np.clip(np.round(expected_pa), 1, None)
    one_minus = lambda p: np.clip(1.0 - p, 0.0, 1.0)
    p_h1 = 1.0 - one_minus(p_hit) ** N
    p_h2 = 1.0 - one_minus(p_hit) ** N - N * p_hit * one_minus(p_hit) ** (N - 1)
    return {
        "h1": p_h1,
        "h2": np.clip(p_h2, 0.0, 1.0),
        "hr": 1.0 - one_minus(p_hr) ** N,
        "k": 1.0 - one_minus(p_k) ** N,
    }


def cmd_train_pa(args: argparse.Namespace) -> None:
    seasons = args.season or [2023, 2024, 2025]
    df = _load(seasons)
    X = df[list(FEATURE_COLUMNS)].astype("float64")
    counts = _class_counts(df)
    folds = walk_forward_folds(df["game_date"], n_folds=args.folds)
    params = {"objective": "multi:softprob", "num_class": 5, "tree_method": "hist",
              "eta": 0.1, "max_depth": 6, "subsample": 0.8, "colsample_bytree": 0.8, "seed": 42}
    print(f"[train-pa] rows={len(df)} folds={len(folds)} (per-PA multiclass)")

    oof = {m: ([], []) for m in ("h1", "h2", "hr", "k")}
    for tr, val in folds:
        Xtr, ytr, wtr = _expand(X.iloc[tr], counts[tr])
        bst = xgb.train(params, xgb.DMatrix(Xtr, label=ytr, weight=wtr), num_boost_round=args.rounds)
        probs = bst.predict(xgb.DMatrix(X.iloc[val]))
        mk = _markets_from_pa(probs, df["expected_pa"].to_numpy()[val])
        for m in oof:
            oof[m][0].extend(mk[m].tolist())
            oof[m][1].extend(df[m].to_numpy()[val].tolist())

    sep = "=" * 60
    print(sep)
    print("GATE — per-PA model (binomial-aggregated) vs naive vs XGB direct")
    print(sep)
    for m in ("h1", "h2", "hr", "k"):
        pred, actual = oof[m]
        b = brier_score(pred, actual)
        naive = baseline_brier(actual)
        pa_margin = naive - b
        print(f"  {m}: per-PA Brier {b:.4f}  vs naive {naive:.4f}  "
              f"(per-PA beats naive {pa_margin:+.4f}; XGB direct beat naive +{_XGB_VS_NAIVE[m]:.4f})")
    print(sep)
    print("Verdict: per-PA wins a market only where its margin exceeds XGB's.")
    print(sep)

    if getattr(args, "save", False):
        from ingester.ml.train import resolve_models_dir
        import json
        models_dir = resolve_models_dir(getattr(args, "models_dir", None))
        Xa, ya, wa = _expand(X, counts)
        final = xgb.train(params, xgb.DMatrix(Xa, label=ya, weight=wa), num_boost_round=args.rounds)
        models_dir.mkdir(parents=True, exist_ok=True)
        gi = models_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n!.gitignore\n")
        final.save_model(models_dir / "pa.json")
        (models_dir / "feature_spec.json").write_text(json.dumps({"features": list(FEATURE_COLUMNS)}, indent=2))
        print(f"  saved → {models_dir.name}/pa.json (per-PA 5-class) + feature_spec.json")


def load_pa_model(models_dir):
    """Load the per-PA multiclass booster (or None)."""
    p = models_dir / "pa.json"
    if not p.exists():
        return None
    b = xgb.Booster()
    b.load_model(str(p))
    return b


def predict_pa_probs(booster, feature_rows: pd.DataFrame) -> np.ndarray:
    """Per-PA class probabilities (n x 5) in _CLASS_ORDER for the given feature rows."""
    X = feature_rows[list(FEATURE_COLUMNS)].astype("float64")
    return booster.predict(xgb.DMatrix(X))
