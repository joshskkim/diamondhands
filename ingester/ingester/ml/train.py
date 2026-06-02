"""train-xgb: time-series-CV-tuned XGBoost per market, reporting Brier vs the mechanistic
baseline and (with --save) persisting final models to ingester/models/ for inference.

Reports honest out-of-fold Brier (each val row scored by a model trained only on earlier
folds). With --save it then fits a final model on the whole season and writes
models/<target>.json + models/feature_spec.json for ml.infer.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import optuna
import pandas as pd
import xgboost as xgb

from ingester.commands.backtest import baseline_brier, brier_score, calibration_buckets
from ingester.ml.dataset import MODELS_DIR
from ingester.ml.features import FEATURE_COLUMNS
from ingester.ml.cv import walk_forward_folds

# Mechanistic full-season Brier per market (backtest run #20/#22, v2.0.0) — reference bar.
# NOTE: full-season population, not the OOF folds; the same-rows naive baseline printed
# alongside is the cleaner apples-to-apples comparison.
_MECHANISTIC_BRIER = {"h1": 0.2351, "h2": 0.1734, "hr": 0.1047, "k": 0.2293}
_BINARY_TARGETS = list(_MECHANISTIC_BRIER)
_BASE = {"objective": "binary:logistic", "eval_metric": "logloss", "tree_method": "hist", "seed": 42}


def resolve_models_dir(name: str | None):
    """Resolve an optional --models-dir to a Path under ingester/ (default the production
    MODELS_DIR). A relative name lands beside MODELS_DIR (e.g. 'models_eval')."""
    from pathlib import Path
    if not name:
        return MODELS_DIR
    p = Path(name)
    return p if p.is_absolute() else (MODELS_DIR.parent / name)


def _load(seasons: list[int]) -> pd.DataFrame:
    frames = []
    for s in seasons:
        path = MODELS_DIR / f"training_{s}.parquet"
        if not path.exists():
            raise SystemExit(f"[train-xgb] missing {path} — run build-training-data --season {s} first")
        frames.append(pd.read_parquet(path))
    return pd.concat(frames, ignore_index=True).sort_values("game_date").reset_index(drop=True)


def _fit(params, X_tr, y_tr, X_val, y_val):
    dtrain = xgb.DMatrix(X_tr, label=y_tr)
    dval = xgb.DMatrix(X_val, label=y_val)
    return xgb.train(params, dtrain, num_boost_round=2000, evals=[(dval, "val")],
                     early_stopping_rounds=50, verbose_eval=False)


def _run_one(df: pd.DataFrame, target: str, trials: int, n_folds: int, save: bool, models_dir=None) -> None:
    models_dir = models_dir or MODELS_DIR
    X = df[list(FEATURE_COLUMNS)].astype("float64")
    y = df[target].astype(int)
    folds = walk_forward_folds(df["game_date"], n_folds=n_folds)
    if not folds:
        raise SystemExit("[train-xgb] no usable CV folds")
    print(f"[train-xgb] target={target} rows={len(df)} base_rate={y.mean():.4f} folds={len(folds)}")

    def objective(trial: optuna.Trial) -> float:
        params = {
            **_BASE,
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "eta": trial.suggest_float("eta", 0.01, 0.3, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 30),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
        }
        briers = [
            brier_score(_fit(params, X.iloc[tr], y.iloc[tr], X.iloc[val], y.iloc[val])
                        .predict(xgb.DMatrix(X.iloc[val])).tolist(), y.iloc[val].tolist())
            for tr, val in folds
        ]
        return float(np.mean(briers))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective, n_trials=trials, show_progress_bar=False)
    best = {**_BASE, **study.best_params}

    # Out-of-fold predictions + the per-fold best_iteration (for the final fit's rounds).
    oof_pred: list[float] = []
    oof_actual: list[int] = []
    best_iters: list[int] = []
    for tr, val in folds:
        bst = _fit(best, X.iloc[tr], y.iloc[tr], X.iloc[val], y.iloc[val])
        oof_pred += bst.predict(xgb.DMatrix(X.iloc[val]), iteration_range=(0, bst.best_iteration + 1)).tolist()
        oof_actual += y.iloc[val].tolist()
        best_iters.append(bst.best_iteration + 1)

    xgb_brier = brier_score(oof_pred, oof_actual)
    naive = baseline_brier(oof_actual)
    mech = _MECHANISTIC_BRIER[target]
    sep = "=" * 56
    print(sep)
    print(f"GATE — target={target}")
    print(f"  out-of-fold rows:     {len(oof_actual):>7,}")
    print(f"  XGBoost CV Brier:     {xgb_brier:.4f}")
    print(f"  naive baseline Brier: {naive:.4f}  (same rows)")
    print(f"  mechanistic baseline: {mech:.4f}  (full-season, diff. population)")
    print(f"  VERDICT: vs naive {naive - xgb_brier:+.4f}; vs mechanistic {mech - xgb_brier:+.4f}")
    for b in calibration_buckets(oof_pred, oof_actual):
        diff = b["actual_rate"] - b["predicted_mean"]
        flag = "ok" if abs(diff) <= 0.02 else ("under" if diff > 0 else "over")
        print(f"    {b['lo']:.1f}-{b['hi']:.1f} n={b['n']:>6} pred={b['predicted_mean']:.3f} actual={b['actual_rate']:.3f} {flag}")
    print(sep)

    if save:
        n_rounds = int(np.median(best_iters))
        final = xgb.train(best, xgb.DMatrix(X, label=y), num_boost_round=max(n_rounds, 1))
        models_dir.mkdir(parents=True, exist_ok=True)
        gi = models_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n!.gitignore\n")
        final.save_model(models_dir / f"{target}.json")
        (models_dir / "feature_spec.json").write_text(json.dumps({"features": list(FEATURE_COLUMNS)}, indent=2))
        print(f"  saved → {models_dir.name}/{target}.json  ({n_rounds} rounds)  + feature_spec.json")


# Regressor targets: name -> (label column, xgboost objective).
_REGRESSORS = {"exp_hits": ("hits", "count:poisson"), "exp_tb": ("total_bases", "reg:tweedie")}


def _run_regressor(df, name, trials, n_folds, save, models_dir):
    models_dir = models_dir or MODELS_DIR
    label_col, objective = _REGRESSORS[name]
    X = df[list(FEATURE_COLUMNS)].astype("float64")
    y = df[label_col].astype("float64")
    folds = walk_forward_folds(df["game_date"], n_folds=n_folds)
    base = {"objective": objective, "eval_metric": "mae", "tree_method": "hist", "seed": 42}

    def mae(pred, actual):
        return float(np.mean(np.abs(np.asarray(pred) - np.asarray(actual))))

    def fit(params, X_tr, y_tr, X_val, y_val):
        return xgb.train(params, xgb.DMatrix(X_tr, label=y_tr), num_boost_round=2000,
                         evals=[(xgb.DMatrix(X_val, label=y_val), "val")],
                         early_stopping_rounds=50, verbose_eval=False)

    def objective_fn(trial):
        params = {
            **base,
            "max_depth": trial.suggest_int("max_depth", 3, 8),
            "eta": trial.suggest_float("eta", 0.01, 0.3, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 30),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
        }
        if objective == "reg:tweedie":
            params["tweedie_variance_power"] = trial.suggest_float("tvp", 1.1, 1.9)
        maes = []
        for tr, val in folds:
            bst = fit(params, X.iloc[tr], y.iloc[tr], X.iloc[val], y.iloc[val])
            pred = bst.predict(xgb.DMatrix(X.iloc[val]), iteration_range=(0, bst.best_iteration + 1))
            maes.append(mae(pred, y.iloc[val]))
        return float(np.mean(maes))

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    study.optimize(objective_fn, n_trials=trials, show_progress_bar=False)
    best = {**base, **{k: v for k, v in study.best_params.items() if k != "tvp"}}
    if objective == "reg:tweedie":
        best["tweedie_variance_power"] = study.best_params["tvp"]

    oof_pred, oof_actual, best_iters = [], [], []
    for tr, val in folds:
        bst = fit(best, X.iloc[tr], y.iloc[tr], X.iloc[val], y.iloc[val])
        oof_pred += bst.predict(xgb.DMatrix(X.iloc[val]), iteration_range=(0, bst.best_iteration + 1)).tolist()
        oof_actual += y.iloc[val].tolist()
        best_iters.append(bst.best_iteration + 1)
    model_mae = mae(oof_pred, oof_actual)
    naive_mae = mae([np.mean(oof_actual)] * len(oof_actual), oof_actual)
    print(f"[train-xgb] regressor {name} ({label_col}, {objective}) rows={len(df)} "
          f"MAE {model_mae:.4f}  (naive-mean {naive_mae:.4f})")

    if save:
        n_rounds = int(np.median(best_iters))
        final = xgb.train(best, xgb.DMatrix(X, label=y), num_boost_round=max(n_rounds, 1))
        models_dir.mkdir(parents=True, exist_ok=True)
        gi = models_dir / ".gitignore"
        if not gi.exists():
            gi.write_text("*\n!.gitignore\n")
        final.save_model(models_dir / f"{name}.json")
        print(f"  saved → {models_dir.name}/{name}.json  ({n_rounds} rounds)")


def cmd_tune_blend(args: argparse.Namespace) -> None:
    """Grid-search the per-market blend weight w (on mechanistic) that minimizes Brier
    of w*p_mech + (1-w)*p_xgb, using two existing backtest runs over identical rows.

    Tune on a clean out-of-sample holdout (e.g. the within-2025 late tail: --mech-run 33
    --xgb-run 34); the weights are a market-level ratio that transfers across model
    generations. Writes models/blend.json.
    """
    import json
    import numpy as np
    from ingester.db import get_connection

    rows = None
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT m.p_hit_1plus, x.p_hit_1plus, m.p_hit_2plus, x.p_hit_2plus,
                   m.p_hr, x.p_hr, m.p_k_1plus, x.p_k_1plus,
                   pgs.hits, pgs.home_runs, pgs.strikeouts
            FROM backtest_projections m
            JOIN backtest_projections x
              ON x.game_id = m.game_id AND x.player_id = m.player_id AND x.backtest_run_id = %s
            JOIN player_game_stats pgs
              ON pgs.game_id = m.game_id AND pgs.player_id = m.player_id AND pgs.plate_appearances > 0
            WHERE m.backtest_run_id = %s
            """,
            (args.xgb_run, args.mech_run),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise SystemExit("[tune-blend] no overlapping rows for those runs")

    cols = {
        "h1": (0, 1, lambda r: int(r[8] >= 1)),
        "h2": (2, 3, lambda r: int(r[8] >= 2)),
        "hr": (4, 5, lambda r: int(r[9] >= 1)),
        "k":  (6, 7, lambda r: int(r[10] >= 1)),
    }
    grid = np.linspace(0.0, 1.0, 21)
    weights: dict[str, float] = {}
    print(f"[tune-blend] {len(rows)} rows  (mech run {args.mech_run}, xgb run {args.xgb_run})")
    for m, (mi, xi, label) in cols.items():
        p_mech = [float(r[mi]) for r in rows]
        p_xgb = [float(r[xi]) for r in rows]
        actual = [label(r) for r in rows]
        best_w, best_b = 1.0, 1.0
        for w in grid:
            blended = [w * pm + (1 - w) * px for pm, px in zip(p_mech, p_xgb)]
            b = brier_score(blended, actual)
            if b < best_b:
                best_b, best_w = b, float(round(w, 2))
        b_mech = brier_score(p_mech, actual)
        b_xgb = brier_score(p_xgb, actual)
        weights[m] = best_w
        print(f"  {m}: w_mech={best_w:.2f}  blended={best_b:.4f}  (mech {b_mech:.4f}, xgb {b_xgb:.4f})")

    models_dir = resolve_models_dir(getattr(args, "models_dir", None))
    models_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "blend.json").write_text(json.dumps(weights, indent=2))
    print(f"  saved → {models_dir.name}/blend.json  {weights}")


def cmd_train_xgb(args: argparse.Namespace) -> None:
    seasons: list[int] = args.season or [2025]
    if args.target == "all":
        targets = list(_BINARY_TARGETS)
    elif args.target == "regressors":
        targets = list(_REGRESSORS)
    else:
        targets = [args.target]
    valid = set(_BINARY_TARGETS) | set(_REGRESSORS)
    for t in targets:
        if t not in valid:
            raise SystemExit(f"[train-xgb] unknown target {t!r}; choose from {sorted(valid)}, 'all', 'regressors'")
    df = _load(seasons)
    train_end = getattr(args, "train_end", None)
    if train_end is not None:
        # Temporal holdout: train only on games on/before train_end so a later range
        # can be backtested as a genuine out-of-sample tail.
        df = df[df["game_date"] <= pd.Timestamp(train_end)].reset_index(drop=True)
        print(f"[train-xgb] restricted to game_date <= {train_end}: {len(df)} rows")
    models_dir = resolve_models_dir(getattr(args, "models_dir", None))
    for t in targets:
        if t in _REGRESSORS:
            _run_regressor(df, t, trials=args.trials, n_folds=args.folds, save=args.save, models_dir=models_dir)
        else:
            _run_one(df, t, trials=args.trials, n_folds=args.folds, save=args.save, models_dir=models_dir)
