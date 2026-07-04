"""backtest: Run a full backtesting suite comparing predictions to actuals.

Usage:
    uv run python main.py backtest --start 2025-04-01 --end 2025-09-30
    uv run python main.py backtest --start 2025-04-01 --end 2025-04-30 --csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from dataclasses import dataclass

import psycopg

from ingester.db import get_connection
from ingester.metrics import (
    average_precision,
    baseline_brier,
    brier_score,
    calibration_buckets,
    log_loss,
    mae,
    mae_per_game,
    pearson,
    roc_auc,
    top_k_lift,
)
from ingester.projection.constants import LEAGUE_RUNS_PER_GAME_BASE, MODEL_VERSION
from ingester.projection.runner import run_backtest_projections


# ---------------------------------------------------------------------------
# Constants snapshot
# ---------------------------------------------------------------------------

def collect_model_constants() -> dict:
    """Serialize all LEAGUE_* and adjustment constants for audit."""
    import ingester.projection.constants as C
    result: dict = {}
    for k, v in vars(C).items():
        if k.startswith("_") or k == "MODEL_VERSION":
            continue
        if isinstance(v, tuple):
            result[k] = list(v)
        elif isinstance(v, (int, float, str, bool)):
            result[k] = v
    # Backtest neutralizes weather (historical games lack a live weather snapshot),
    # so tag the run to keep future runs comparable apples-to-apples.
    result["WEATHER_SKIPPED"] = True
    return result


# ---------------------------------------------------------------------------
# Metric functions live in ingester.metrics (shared with compute-accuracy):
# brier_score, baseline_brier, calibration_buckets, mae_per_game.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _insert_backtest_run(
    conn: psycopg.Connection,
    start: date,
    end: date,
    model_version: str = MODEL_VERSION,
) -> int:
    """Create a new backtest_runs row in 'running' state; returns its id."""
    row = conn.execute(
        """
        INSERT INTO backtest_runs (
            range_start, range_end, model_version, model_constants
        )
        VALUES (%s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (start, end, model_version, json.dumps(collect_model_constants())),
    ).fetchone()
    conn.commit()
    return int(row[0])


def _update_backtest_run(
    conn: psycopg.Connection,
    run_id: int,
    n_games: int,
    n_batter_projections: int,
    brier_h1: float,
    brier_h2: float,
    brier_hr: float,
    brier_k: float,
    mae: float,
    cal_json: str,
    run_corr: float = float("nan"),
    run_mae_baseline: float = float("nan"),
    ll_h1: float = float("nan"),
    ll_h2: float = float("nan"),
    ll_hr: float = float("nan"),
    ll_k: float = float("nan"),
) -> None:
    def _ll(v: float) -> float | None:
        return None if v != v else round(v, 5)  # NaN -> NULL

    conn.execute(
        """
        UPDATE backtest_runs SET
            completed_at         = NOW(),
            n_games              = %s,
            n_batter_projections = %s,
            brier_hit1plus       = %s,
            brier_hit2plus       = %s,
            brier_hr             = %s,
            brier_k1plus         = %s,
            mae_total_runs       = %s,
            run_corr             = %s,
            run_mae_baseline     = %s,
            log_loss_hit1plus    = %s,
            log_loss_hit2plus    = %s,
            log_loss_hr          = %s,
            log_loss_k1plus      = %s,
            calibration_buckets  = %s::jsonb
        WHERE id = %s
        """,
        (
            n_games, n_batter_projections,
            None if brier_h1 != brier_h1 else round(brier_h1, 5),  # NaN check
            None if brier_h2 != brier_h2 else round(brier_h2, 5),
            None if brier_hr != brier_hr else round(brier_hr, 5),
            None if brier_k != brier_k  else round(brier_k,  5),
            None if mae != mae           else round(mae, 2),
            None if run_corr != run_corr else round(run_corr, 3),
            None if run_mae_baseline != run_mae_baseline else round(run_mae_baseline, 2),
            _ll(ll_h1), _ll(ll_h2), _ll(ll_hr), _ll(ll_k),
            cal_json,
            run_id,
        ),
    )
    conn.commit()


def _latest_snapshot_before(conn: psycopg.Connection, game_date: date) -> date | None:
    """Return the most recent as_of_date <= game_date in batter_skill_snapshots, or None."""
    row = conn.execute(
        "SELECT MAX(as_of_date) FROM batter_skill_snapshots WHERE as_of_date <= %s",
        (game_date,),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


@dataclass
class _Outcomes:
    p_hit1: list[float]
    p_hit2: list[float]
    p_hr:   list[float]
    p_k:    list[float]
    a_hit1: list[int]
    a_hit2: list[int]
    a_hr:   list[int]
    a_k:    list[int]
    game_hits: dict[int, tuple[float, float]]  # game_id → (exp, actual)
    n_projections: int
    n_games: int
    csv_rows: list[tuple]  # populated only when want_csv=True
    # Sim-blend weight fitting (--sim-props): the simulator's per-batter estimate aligned
    # 1:1 to p_hit1/p_hr/p_k above. None entries = no sim prob for that row.
    sim_hit1: list[float | None]
    sim_hr:   list[float | None]
    sim_k:    list[float | None]
    # Prior-season HR-ranker features (leak-free), each None when the hitter has no
    # prior-season batted-ball profile. Aligned 1:1 to p_hr/a_hr. Keyed by feature
    # name: barrel, pulled_air, sweet_spot, p90_ev. The baselines the model must beat.
    hr_rankers: dict[str, list[float | None]]


def _load_outcomes(
    conn: psycopg.Connection,
    run_id: int,
    want_csv: bool = False,
) -> _Outcomes:
    """
    Join backtest_projections to player_game_stats for the given run.
    Only rows with non-NULL predictions AND matching player_game_stats are included.
    """
    rows = conn.execute(
        """
        SELECT
            bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus,
            bp.expected_hits,
            bp.game_id,
            bp.player_id,
            g.game_date,
            pgs.hits,
            CASE WHEN pgs.hits      >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.hits      >= 2 THEN 1 ELSE 0 END,
            CASE WHEN pgs.home_runs >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.strikeouts>= 1 THEN 1 ELSE 0 END,
            bp.sim_p_hit_1plus, bp.sim_p_hr, bp.sim_p_k_1plus,
            bbb.barrel_pct, bbb.pulled_air_pct, bbb.sweet_spot_pct, bbb.p90_ev_fbld
        FROM backtest_projections bp
        JOIN games g ON g.id = bp.game_id
        JOIN player_game_stats pgs
            ON pgs.player_id = bp.player_id
            AND pgs.game_id  = bp.game_id
            AND pgs.plate_appearances > 0
            AND pgs.plate_appearances IS NOT NULL
        -- Naive-barrel-rank baseline: each hitter's PRIOR-season barrel rate (leak-free,
        -- known before the game). The yardstick the model's HR ranking must beat.
        LEFT JOIN batter_batted_ball bbb
            ON bbb.player_id = bp.player_id
            AND bbb.season = EXTRACT(YEAR FROM g.game_date)::int - 1
        WHERE bp.backtest_run_id = %s
          AND pgs.game_id IS NOT NULL
          AND bp.p_hit_1plus IS NOT NULL
        ORDER BY g.game_date, bp.game_id, bp.player_id
        """,
        (run_id,),
    ).fetchall()

    n_total = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT game_id) FROM backtest_projections WHERE backtest_run_id = %s",
        (run_id,),
    ).fetchone()

    out = _Outcomes(
        p_hit1=[], p_hit2=[], p_hr=[], p_k=[],
        a_hit1=[], a_hit2=[], a_hr=[], a_k=[],
        game_hits={},
        n_projections=int(n_total[0]),
        n_games=int(n_total[1]),
        csv_rows=[],
        sim_hit1=[], sim_hr=[], sim_k=[],
        hr_rankers={"barrel": [], "pulled_air": [], "sweet_spot": [], "p90_ev": []},
    )

    for row in rows:
        (pred_h1, pred_h2, pred_hr, pred_k,
         exp_hits, game_id, player_id, game_date,
         actual_hits, act_h1, act_h2, act_hr, act_k,
         sim_h1, sim_hr, sim_k,
         f_barrel, f_pull_air, f_sweet, f_p90) = row

        out.p_hit1.append(float(pred_h1))
        out.p_hit2.append(float(pred_h2) if pred_h2 is not None else float(pred_h1))
        out.p_hr.append(float(pred_hr) if pred_hr is not None else 0.0)
        out.p_k.append(float(pred_k)  if pred_k  is not None else 0.0)
        out.a_hit1.append(int(act_h1)); out.a_hit2.append(int(act_h2))
        out.a_hr.append(int(act_hr));   out.a_k.append(int(act_k))
        out.sim_hit1.append(float(sim_h1) if sim_h1 is not None else None)
        out.sim_hr.append(float(sim_hr) if sim_hr is not None else None)
        out.sim_k.append(float(sim_k) if sim_k is not None else None)
        out.hr_rankers["barrel"].append(float(f_barrel) if f_barrel is not None else None)
        out.hr_rankers["pulled_air"].append(float(f_pull_air) if f_pull_air is not None else None)
        out.hr_rankers["sweet_spot"].append(float(f_sweet) if f_sweet is not None else None)
        out.hr_rankers["p90_ev"].append(float(f_p90) if f_p90 is not None else None)

        gid = int(game_id)
        eh = float(exp_hits) if exp_hits is not None else 0.0
        ah = int(actual_hits) if actual_hits is not None else 0
        prev = out.game_hits.get(gid, (0.0, 0))
        out.game_hits[gid] = (prev[0] + eh, prev[1] + ah)

        if want_csv:
            d = str(game_date)[:10]
            pid = int(player_id)
            gid_csv = int(game_id)
            out.csv_rows.extend([
                (d, pid, gid_csv, "hit1plus", float(pred_h1), int(act_h1)),
                (d, pid, gid_csv, "hit2plus", float(pred_h2) if pred_h2 else float(pred_h1), int(act_h2)),
                (d, pid, gid_csv, "hr",       float(pred_hr) if pred_hr else 0.0, int(act_hr)),
                (d, pid, gid_csv, "k1plus",   float(pred_k)  if pred_k  else 0.0, int(act_k)),
            ])

    return out


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------

_SEP = "═" * 50


def _cal_flag(bucket: dict) -> str:
    diff = bucket["actual_rate"] - bucket["predicted_mean"]
    if abs(diff) <= 0.02:
        return "✓"
    return "⚠ underconfident" if diff > 0 else "⚠ overconfident"


def _load_run_totals(
    conn: psycopg.Connection, run_id: int
) -> tuple[list[float], list[float]]:
    """(predicted, actual) game-total runs for games in this run that have a final score."""
    rows = conn.execute(
        """
        SELECT bgr.expected_total_runs, (g.home_score + g.away_score)
        FROM backtest_game_runs bgr
        JOIN games g ON g.id = bgr.game_id
        WHERE bgr.backtest_run_id = %s
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    preds = [float(r[0]) for r in rows]
    actuals = [float(r[1]) for r in rows]
    return preds, actuals


def _print_results(
    run_id: int,
    start: date,
    end: date,
    out: _Outcomes,
    b_h1: float,
    b_h2: float,
    b_hr: float,
    b_k:  float,
    base_h1: float,
    base_h2: float,
    base_hr: float,
    base_k:  float,
    mae: float,
    cal: dict[str, list[dict]],
) -> None:
    def _f(v: float, places: int = 4) -> str:
        return f"{v:.{places}f}" if v == v else "N/A"

    print(_SEP)
    print(f"Backtest Run #{run_id}  |  {MODEL_VERSION}  |  {start} → {end}")
    print(_SEP)
    print(f"Games:               {out.n_games:>6,}")
    print(f"Batter projections: {out.n_projections:>6,}")
    print(f"Matched to actuals: {len(out.p_hit1):>6,}")
    print()
    print("Brier scores:")
    print(f"  P(H≥1):    {_f(b_h1)}    (baseline {_f(base_h1)})")
    print(f"  P(H≥2):    {_f(b_h2)}    (baseline {_f(base_h2)})")
    print(f"  P(HR):     {_f(b_hr)}    (baseline {_f(base_hr)})")
    print(f"  P(K≥1):    {_f(b_k)}    (baseline {_f(base_k)})")
    print()
    print(f"MAE expected vs actual hits/game:  {_f(mae, 2)}  (proxy for runs MAE)")
    print()
    print("Calibration P(HR):")
    for bucket in cal.get("hr", []):
        flag = _cal_flag(bucket)
        lo_pct = f"{bucket['lo']*100:.0f}%"
        hi_pct = f"{bucket['hi']*100:.0f}%"
        print(
            f"  {lo_pct:>4}-{hi_pct:<4}  n={bucket['n']:>5}  "
            f"pred={bucket['predicted_mean']:.3f}  actual={bucket['actual_rate']:.3f}  {flag}"
        )
    print(_SEP)


# ---------------------------------------------------------------------------
# Sim-blend weight sweep (--sim-props)
# ---------------------------------------------------------------------------

# Blend weights to try: 0% .. 100% sim in 5-pt steps. w=0 is the current closed-form
# board, so it's always in the grid and the sweep can never look worse than baseline.
_SWEEP_GRID = [i / 100 for i in range(0, 101, 5)]


def _sweep_sim_weights(out: _Outcomes) -> None:
    """Per market, sweep the sim-blend weight w over w*sim + (1-w)*closed_form and report
    the Brier-minimizing w vs the w=0 baseline. Scored on the rows that actually have a
    sim prob, so the baseline is recomputed on that same subset (not the global Brier)."""
    markets = [
        ("hit1plus", out.p_hit1, out.sim_hit1, out.a_hit1),
        ("hr",       out.p_hr,   out.sim_hr,   out.a_hr),
        ("k1plus",   out.p_k,    out.sim_k,    out.a_k),
    ]
    n_with_sim = sum(1 for s in out.sim_hit1 if s is not None)
    print(f"\nSim-blend weight sweep ({n_with_sim:,} rows with sim props):")
    if n_with_sim == 0:
        print("  (no sim props on this run — re-run with --sim-props)")
        return
    print(f"  {'market':<10}{'base(w=0)':>12}{'best w':>9}{'best Brier':>13}{'Δ Brier':>22}")
    for name, model, sim, actual in markets:
        rows = [(mp, sp, a) for mp, sp, a in zip(model, sim, actual) if sp is not None]
        if not rows:
            continue
        mp = [r[0] for r in rows]
        sp = [r[1] for r in rows]
        a = [r[2] for r in rows]
        base = brier_score(mp, a)
        best_w, best_b = 0.0, base
        for w in _SWEEP_GRID:
            blended = [w * s + (1.0 - w) * p for p, s in zip(mp, sp)]
            b = brier_score(blended, a)
            if b < best_b:
                best_b, best_w = b, w
        delta = best_b - base
        pct = (delta / base * 100.0) if base else 0.0
        print(f"  {name:<10}{base:>12.5f}{best_w:>9.2f}{best_b:>13.5f}"
              f"{delta:>+13.5f} ({pct:+.2f}%)")
    print("  NOTE: best w is IN-SAMPLE. Confirm on a held-out range before setting "
          "DIAMOND_SIM_PROP_BLEND_WEIGHT_{HIT,HR,K}.")


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def cmd_backtest(args: argparse.Namespace) -> None:
    start: date = args.start
    end: date   = args.end
    want_csv: bool = getattr(args, "csv", False)
    model: str = getattr(args, "model", "mechanistic")

    if start > end:
        print("[backtest] ERROR: --start must be <= --end", file=sys.stderr)
        sys.exit(1)

    bundle = None
    model_version = MODEL_VERSION
    if model in ("xgb", "blend"):
        from ingester.ml.infer import ModelBundle  # lazy: keeps xgboost off the default path
        from ingester.ml.train import resolve_models_dir
        bundle = ModelBundle.load(resolve_models_dir(getattr(args, "models_dir", None)), blend=(model == "blend"))
        if bundle is None:
            need = "train-xgb --target all --save" + (" then tune-blend" if model == "blend" else "")
            print(f"[backtest] ERROR: --model {model} but models/weights missing; run {need} first",
                  file=sys.stderr)
            sys.exit(1)
        model_version = f"{MODEL_VERSION}-{model}"

    if getattr(args, "calibrate", False):
        from ingester.projection.runner import set_calibrator
        from ingester.projection.calibration import Calibrator
        from ingester.ml.train import resolve_models_dir
        cal = Calibrator.load(f"{resolve_models_dir(getattr(args, 'models_dir', None))}/calibration.json")
        set_calibrator(cal)
        model_version = f"{model_version}-cal"
        print(f"[backtest] Calibration: {'ON' if cal else 'requested but calibration.json missing'}")

    if getattr(args, "park_personalized", False):
        from ingester.projection.runner import set_backtest_park_personalized
        set_backtest_park_personalized(True)
        model_version = f"{model_version}-parkgeo"
        print("[backtest] Park personalization: ON (prior-season batted-ball profile)")

    if getattr(args, "weather_carry", False):
        from ingester.projection.runner import set_backtest_weather_carry
        set_backtest_weather_carry(True)
        model_version = f"{model_version}-windspray"
        print("[backtest] Weather carry HR: ON (trajectory model, spray-weighted wind, "
              "prior-season profiles)")

    sim_props = getattr(args, "sim_props", False)
    if sim_props:
        from ingester.projection.runner import set_backtest_sim_props
        set_backtest_sim_props(True)
        print("[backtest] Sim props: ON (Monte-Carlo per-batter capture; will sweep "
              "sim-blend weight per market)")

    if getattr(args, "team_defense", False):
        from ingester.projection.runner import set_team_defense
        set_team_defense(True)
        model_version = f"{model_version}-teamdef"
        print("[backtest] Team defense: ON (leak-free xBA hit-suppression factor)")

    print(f"[backtest] Range {start} → {end}  |  Model {model_version}")

    conn = get_connection()
    try:
        # Step a: create the run row.
        run_id = _insert_backtest_run(conn, start, end, model_version)
        print(f"[backtest] Run #{run_id} created")

        # Step b: project each date in the range.
        total_days = 0
        current = start
        while current <= end:
            as_of = _latest_snapshot_before(conn, current)
            if as_of is None:
                current += timedelta(days=1)
                continue

            summary = run_backtest_projections(conn, current, as_of, run_id, bundle=bundle)
            conn.commit()

            if summary.games_projected > 0:
                total_days += 1
                print(
                    f"  {current}: {summary.games_projected} games, "
                    f"{summary.batter_rows} batter rows  (snapshot {as_of})"
                )
            current += timedelta(days=1)

        print(f"[backtest] Projections done — {total_days} game-days projected")

        # Step c+d: load outcomes and compute metrics.
        out = _load_outcomes(conn, run_id, want_csv=want_csv)
        if not out.p_hit1:
            print(
                "[backtest] WARN: No matched batter rows found. "
                "Ensure player_game_stats covers the backtest range.",
                file=sys.stderr,
            )

        b_h1 = brier_score(out.p_hit1, out.a_hit1)
        b_h2 = brier_score(out.p_hit2, out.a_hit2)
        b_hr = brier_score(out.p_hr,   out.a_hr)
        b_k  = brier_score(out.p_k,    out.a_k)

        base_h1 = baseline_brier(out.a_hit1)
        base_h2 = baseline_brier(out.a_hit2)
        base_hr = baseline_brier(out.a_hr)
        base_k  = baseline_brier(out.a_k)

        # Log-loss: strictly-proper, sharper than Brier on the rare-event markets.
        ll_h1 = log_loss(out.p_hit1, out.a_hit1)
        ll_h2 = log_loss(out.p_hit2, out.a_hit2)
        ll_hr = log_loss(out.p_hr,   out.a_hr)
        ll_k  = log_loss(out.p_k,    out.a_k)

        mae_hits = mae_per_game(out.game_hits)  # legacy hits proxy (printed for continuity)

        # Real run-total scoring: predicted game total vs actual final score, plus a
        # naive "always predict the league mean total" baseline and the correlation.
        run_pred, run_act = _load_run_totals(conn, run_id)
        run_mae = mae(run_pred, run_act)
        run_corr = pearson(run_pred, run_act)
        baseline_total = 2 * LEAGUE_RUNS_PER_GAME_BASE
        run_mae_baseline = (
            mae([baseline_total] * len(run_act), run_act) if run_act else float("nan")
        )

        cal = {
            "hit1plus": calibration_buckets(out.p_hit1, out.a_hit1),
            "hit2plus": calibration_buckets(out.p_hit2, out.a_hit2),
            "hr":       calibration_buckets(out.p_hr,   out.a_hr),
            "k1plus":   calibration_buckets(out.p_k,    out.a_k),
        }

        # Step e: persist metrics (mae_total_runs now holds the REAL run MAE).
        _update_backtest_run(
            conn, run_id,
            out.n_games, out.n_projections,
            b_h1, b_h2, b_hr, b_k, run_mae,
            json.dumps(cal),
            run_corr=run_corr,
            run_mae_baseline=run_mae_baseline,
            ll_h1=ll_h1, ll_h2=ll_h2, ll_hr=ll_hr, ll_k=ll_k,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Step f: pretty-print.
    _print_results(
        run_id, start, end, out,
        b_h1, b_h2, b_hr, b_k,
        base_h1, base_h2, base_hr, base_k,
        mae_hits, cal,
    )

    # Real run-total accuracy (V19): predicted game total vs final score.
    print(f"\nGame run totals ({len(run_pred)} scored games):")
    print(f"  run MAE:            {run_mae:.3f}")
    print(f"  league-mean MAE:    {run_mae_baseline:.3f}  (always {2 * LEAGUE_RUNS_PER_GAME_BASE:.1f})")
    print(f"  corr(pred, actual): {run_corr:+.3f}")

    # Log-loss (sharper than Brier on rare events; lower is better).
    print("\nLog-loss (proper scoring, rewards sharp+correct):")
    print(f"  hit1plus={ll_h1:.5f}  hit2plus={ll_h2:.5f}  hr={ll_hr:.5f}  k1plus={ll_k:.5f}")

    # Discrimination + lift (ranking quality Brier is blind to on the rare HR event).
    # ROC-AUC = P(rank a homer above a non-homer); PR-AUC concentrates on the top of
    # the list where our picks live; top-decile lift = realized rate of the top 10%
    # ranked vs the base rate (1.0 = no skill). These are what "getting HR right" means.
    _disc_markets = [
        ("hit1plus", out.p_hit1, out.a_hit1),
        ("hit2plus", out.p_hit2, out.a_hit2),
        ("hr",       out.p_hr,   out.a_hr),
        ("k1plus",   out.p_k,    out.a_k),
    ]
    def _n(v: float, p: int = 3) -> str:
        return f"{v:.{p}f}" if v == v else "N/A"
    print("\nDiscrimination (rank quality; AUC/PR-AUC higher=better; lift 1.0=no skill):")
    print(f"  {'market':<10}{'ROC-AUC':>9}{'PR-AUC':>9}{'base':>8}"
          f"{'top10% rate':>13}{'lift':>8}")
    for name, preds, acts in _disc_markets:
        auc = roc_auc(preds, acts)
        ap = average_precision(preds, acts)
        lift = top_k_lift(preds, acts, max(1, len(preds) // 10))
        print(f"  {name:<10}{_n(auc):>9}{_n(ap):>9}{_n(lift['base_rate']):>8}"
              f"{_n(lift['top_k_rate']):>13}{_n(lift['lift']):>8}")

    # HR gate: does the model out-rank naive prior-season batted-ball features? Scored on
    # the shared subset of rows that HAVE a prior-season profile (apples-to-apples). Each
    # raw feature is a leak-free single-number HR ranker; the model must beat all of them.
    idx = [i for i, b in enumerate(out.hr_rankers["barrel"]) if b is not None]
    print(f"\nHR gate — model vs naive prior-season feature ranks "
          f"({len(idx)}/{len(out.p_hr)} rows w/ prior profile; higher=better):")
    if idx:
        a_hr = [out.a_hr[i] for i in idx]
        k = max(1, len(idx) // 10)
        rankers = [("model", [out.p_hr[i] for i in idx])]
        rankers += [(name, [vals[i] for i in idx])
                    for name, vals in out.hr_rankers.items()]
        print(f"  {'ranker':<12}{'ROC-AUC':>9}{'PR-AUC':>9}{'top10%-lift':>13}")
        for label, scores in rankers:
            lift = top_k_lift(scores, a_hr, k)
            print(f"  {label:<12}{_n(roc_auc(scores, a_hr)):>9}"
                  f"{_n(average_precision(scores, a_hr)):>9}{_n(lift['lift']):>13}")
    else:
        print("  (no rows with a prior-season profile — load a prior season w/ refresh-batted-ball)")

    # Sim-blend weight fitting (only when --sim-props captured the simulator's estimate).
    if sim_props:
        _sweep_sim_weights(out)

    # Step g: optional CSV.
    if want_csv and out.csv_rows:
        csv_path = f"/tmp/backtest_{run_id}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["game_date", "player_id", "game_id", "market", "predicted", "actual"])
            writer.writerows(out.csv_rows)
        print(f"\n[backtest] CSV written → {csv_path}  ({len(out.csv_rows):,} rows)")
