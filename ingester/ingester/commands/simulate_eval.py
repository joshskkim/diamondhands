"""simulate-eval: backtest the lineup Monte-Carlo run simulator vs actual final scores.

For each game in the range with a confirmed lineup and a real score, build each batter's
point-in-time features, predict the per-PA outcome distribution (saved per-PA model),
simulate the game, and compare the predicted total runs to the actual total — against the
naive baseline (always predict the league mean). The first honest read on the run/total
projection, now that actual scores are backfilled (V12).
"""
from __future__ import annotations

import argparse
from bisect import bisect_right

import numpy as np
import pandas as pd

from ingester.db import get_connection
from ingester.ml.features import build_feature_row
from ingester.ml.perpa import load_pa_model, predict_pa_probs
from ingester.ml.simulate import expected_total_runs, split_to_7
from ingester.ml.train import resolve_models_dir
from ingester.projection.park_adj import ParkFactors
from ingester.projection.runner import _effective_bat_side  # noqa: F401 (kept for parity)

_GAMES_SQL = """
    SELECT g.id, g.game_date, g.home_score, g.away_score,
           gl.is_home, gl.batting_order, gl.player_id, COALESCE(p.bats,'R') AS bats,
           CASE WHEN gl.is_home THEN g.away_probable_pitcher_id
                ELSE g.home_probable_pitcher_id END AS opp_pid,
           COALESCE(s.park_factor_hits,1.0), COALESCE(s.park_factor_hr_lhb,1.0),
           COALESCE(s.park_factor_hr_rhb,1.0)
    FROM games g
    JOIN game_lineups gl ON gl.game_id = g.id
    JOIN players p ON p.id = gl.player_id
    LEFT JOIN stadiums s ON s.id = g.stadium_id
    WHERE g.game_date BETWEEN %s AND %s AND g.home_score IS NOT NULL
    ORDER BY g.id, gl.is_home, gl.batting_order
"""


def cmd_simulate_eval(args: argparse.Namespace) -> None:
    models_dir = resolve_models_dir(getattr(args, "models_dir", None))
    booster = load_pa_model(models_dir)
    if booster is None:
        raise SystemExit(f"[simulate-eval] no {models_dir.name}/pa.json — run train-pa --save first")

    conn = get_connection()
    throws = {int(r[0]): (r[1] or "R") for r in conn.execute("SELECT id, throws FROM players").fetchall()}
    snap_dates = [r[0] for r in conn.execute(
        "SELECT DISTINCT as_of_date FROM batter_skill_snapshots ORDER BY as_of_date").fetchall()]

    def as_of_for(game_date):
        i = bisect_right(snap_dates, game_date)
        return snap_dates[i - 1] if i else game_date

    rows = conn.execute(_GAMES_SQL, (args.start, args.end)).fetchall()

    # group rows by game id
    games: dict[int, list] = {}
    for r in rows:
        games.setdefault(int(r[0]), []).append(r)

    preds, actuals = [], []
    skipped = 0
    items = list(games.items())
    if args.limit:
        items = items[: args.limit]

    for gi, (game_id, grp) in enumerate(items, 1):
        if len(grp) != 18 or any(r[8] is None for r in grp):
            skipped += 1
            continue
        game_date = grp[0][1]
        actual = int(grp[0][2]) + int(grp[0][3])
        as_of = as_of_for(game_date)
        season = game_date.year
        feats, ok = [], True
        for r in grp:
            (_, _, _, _, is_home, order, pid, bats, opp_pid, pf_h, pf_l, pf_r) = r
            f = build_feature_row(
                conn, batter_id=int(pid), bats=str(bats),
                opposing_pitcher_id=int(opp_pid), pitcher_throws=throws.get(int(opp_pid), "R"),
                lineup_position=int(order), is_home=bool(is_home),
                park=ParkFactors(float(pf_h), float(pf_l), float(pf_r)),
                as_of_date=as_of, season=season,
            )
            if f is None:
                ok = False
                break
            feats.append((bool(is_home), f))
        if not ok:
            skipped += 1
            continue
        df = pd.DataFrame([f for _, f in feats])
        probs7 = split_to_7(predict_pa_probs(booster, df))
        home7 = np.array([probs7[i] for i, (h, _) in enumerate(feats) if h])
        away7 = np.array([probs7[i] for i, (h, _) in enumerate(feats) if not h])
        preds.append(expected_total_runs(home7, away7, n_sims=args.sims, seed=game_id))
        actuals.append(actual)
        if gi % 100 == 0:
            print(f"  …{gi}/{len(items)} games simulated")

    conn.close()
    if not preds:
        raise SystemExit("[simulate-eval] no eligible games")
    preds = np.array(preds)
    actuals = np.array(actuals)
    league_mean = actuals.mean()
    sim_mae = np.abs(preds - actuals).mean()
    naive_mae = np.abs(league_mean - actuals).mean()
    # Calibrated: rescale predictions to the actual mean (removes the base-running scale
    # bias) so we test discrimination, not absolute calibration.
    scaled = preds * (league_mean / preds.mean())
    scaled_mae = np.abs(scaled - actuals).mean()
    corr = float(np.corrcoef(preds, actuals)[0, 1])

    sep = "=" * 60
    print(sep)
    print(f"SIMULATE-EVAL — total runs, {len(preds)} games ({args.start} → {args.end})")
    print(f"  simulator run-MAE:   {sim_mae:.3f}   (avg pred {preds.mean():.2f})")
    print(f"  calibrated run-MAE:  {scaled_mae:.3f}   (rescaled to mean {league_mean:.2f})")
    print(f"  naive-mean run-MAE:  {naive_mae:.3f}")
    print(f"  corr(pred, actual):  {corr:+.3f}")
    print(f"  VERDICT: calibrated sim beats naive by {naive_mae - scaled_mae:+.3f}")
    print(sep)
