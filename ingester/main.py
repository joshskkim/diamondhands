"""
Diamond MLB Projection Ingester
================================
Usage:
    uv run python main.py <subcommand> [options]

Subcommands:
    load-static      Seed teams and stadiums from /data/stadiums.json
    backfill-stats   Pull historical player_game_stats via pybaseball
    backfill-games   Populate historical games for a date range from MLB Stats API
    daily-slate      Fetch today's games + probable pitchers from MLB Stats API
    refresh-lineups  Pull today's confirmed batting orders (cron-friendly, idempotent)
    backfill-lineups Populate historical confirmed lineups for a date range (backtesting)
    refresh-weather  Attach weather snapshot to today's games
    refresh-skills   Recompute batter_skill and pitcher_skill aggregates
    project          Compute batter_projections for today's slate
    backtest         Run full backtesting suite comparing predictions to actuals
    smoke            End-to-end sanity check (read-only)
    smoke-project    Run project + verify projection row counts
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from ingester.commands.load_static import cmd_load_static
from ingester.commands.backfill_stats import cmd_backfill_stats
from ingester.commands.backfill_games import cmd_backfill_games
from ingester.commands.daily_slate import cmd_daily_slate
from ingester.commands.lineups import cmd_backfill_lineups, cmd_refresh_lineups
from ingester.commands.scores import cmd_backfill_scores
from ingester.commands.refresh_weather import cmd_refresh_weather
from ingester.commands.refresh_skills import cmd_refresh_skills
from ingester.commands.skill_snapshots import cmd_refresh_skill_snapshots
from ingester.commands.pitch_aggregations import (
    cmd_refresh_pitch_aggregations,
    cmd_refresh_pitch_snapshots,
)
from ingester.commands.backtest import cmd_backtest
from ingester.ml.dataset import cmd_build_training_data
from ingester.ml.train import cmd_train_xgb, cmd_tune_blend
from ingester.ml.perpa import cmd_train_pa
from ingester.commands.simulate_eval import cmd_simulate_eval
from ingester.commands.report import cmd_compare_runs
from ingester.commands.smoke import cmd_smoke_skills, cmd_smoke_slate
from ingester.projection.runner import cmd_project, cmd_smoke_project


def _date_arg(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date {s!r} — expected YYYY-MM-DD (e.g. 2026-04-15)"
        )


def cmd_smoke(args: argparse.Namespace) -> None:
    """End-to-end sanity check: verify DB connection, row counts, etc."""
    from dotenv import load_dotenv
    import os
    import psycopg

    load_dotenv()
    url = os.getenv("DATABASE_URL")
    if not url:
        print("[smoke] ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = [row[0] for row in cur.fetchall()]

    print(f"[smoke] Connected to DB. Tables: {tables}")
    print("[smoke] OK")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diamond-ingester",
        description="Diamond MLB Projection — data ingestion & projection CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_static = sub.add_parser("load-static", help="Seed teams + stadiums from /data/stadiums.json")
    p_static.add_argument(
        "--data-dir",
        default=str(Path(__file__).parent.parent / "data"),
        help="Directory containing stadiums.json (default: ../data)",
    )

    p_backfill = sub.add_parser("backfill-stats", help="Pull historical game logs via pybaseball")
    p_backfill.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")

    p_bf_games = sub.add_parser("backfill-games", help="Populate historical games for a date range")
    p_bf_games.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="First date in range (inclusive)",
    )
    p_bf_games.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="Last date in range (inclusive)",
    )

    p_slate   = sub.add_parser("daily-slate",     help="Fetch today's games + probable pitchers")
    p_lineups = sub.add_parser("refresh-lineups", help="Pull today's confirmed batting orders")
    p_weather = sub.add_parser("refresh-weather", help="Attach weather to today's games")

    p_bf_lineups = sub.add_parser(
        "backfill-lineups", help="Populate historical confirmed lineups for a date range"
    )
    p_bf_lineups.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="First date in range (inclusive)",
    )
    p_bf_lineups.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="Last date in range (inclusive)",
    )

    p_skills = sub.add_parser("refresh-skills", help="Recompute batter/pitcher skill aggregates")
    p_skills.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")

    p_snapshots = sub.add_parser(
        "refresh-skill-snapshots",
        help="Compute point-in-time skill snapshots for backtesting",
    )
    p_snapshots.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")
    p_snapshots.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="First date in snapshot range",
    )
    p_snapshots.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="Last date in snapshot range",
    )
    p_snapshots.add_argument(
        "--interval", choices=["weekly"], default="weekly",
        help="Snapshot frequency (default: weekly = every Monday)",
    )
    p_snapshots.add_argument(
        "--force-rebuild", action="store_true", default=False, dest="force_rebuild",
        help="Delete existing snapshots for the target dates before rebuilding "
             "(required to clear stale rows when the player population changes)",
    )

    p_pitch_agg = sub.add_parser(
        "refresh-pitch-aggregations",
        help="Aggregate pitch-level Statcast into batter pitch-type stats, arsenals, baselines",
    )
    p_pitch_agg.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")
    p_pitch_agg.add_argument(
        "--as-of", metavar="YYYY-MM-DD", type=_date_arg, default=None, dest="as_of",
        help="Aggregate season-to-date through this date (default: today in US/Eastern)",
    )

    p_pitch_snap = sub.add_parser(
        "refresh-pitch-snapshots",
        help="Backfill point-in-time pitch-mix snapshots (one per Monday) for backtesting",
    )
    p_pitch_snap.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")
    p_pitch_snap.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="First date in snapshot range",
    )
    p_pitch_snap.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="Last date in snapshot range",
    )
    p_pitch_snap.add_argument(
        "--interval", choices=["weekly"], default="weekly",
        help="Snapshot frequency (default: weekly = every Monday)",
    )

    p_build_td = sub.add_parser(
        "build-training-data",
        help="Build per-batter-game feature rows (point-in-time) into models/training_<season>.parquet",
    )
    p_build_td.add_argument(
        "--season", type=int, action="append",
        help="Season year (repeatable; default 2025)",
    )

    p_train_xgb = sub.add_parser(
        "train-xgb",
        help="Time-series-CV-tuned XGBoost for one market; reports Brier vs the mechanistic baseline",
    )
    p_train_xgb.add_argument("--target", default="hr", help="Market: h1|h2|hr|k|all (default hr)")
    p_train_xgb.add_argument("--season", type=int, action="append", help="Season(s) (default 2025)")
    p_train_xgb.add_argument("--trials", type=int, default=30, help="Optuna trials (default 30)")
    p_train_xgb.add_argument("--folds", type=int, default=4, help="Walk-forward CV folds (default 4)")
    p_train_xgb.add_argument(
        "--save", action="store_true", default=False,
        help="Fit a final model on the whole season and save to models/<target>.json",
    )
    p_train_xgb.add_argument(
        "--train-end", metavar="YYYY-MM-DD", type=_date_arg, default=None, dest="train_end",
        help="Temporal holdout: train only on games on/before this date",
    )
    p_train_xgb.add_argument(
        "--models-dir", default=None, dest="models_dir",
        help="Save models to this dir (default models/; e.g. models_eval to not clobber production)",
    )

    p_tune_blend = sub.add_parser(
        "tune-blend",
        help="Grid-search per-market blend weights from two backtest runs; writes models/blend.json",
    )
    p_tune_blend.add_argument("--mech-run", type=int, required=True, dest="mech_run",
                              help="backtest_runs.id of the mechanistic run")
    p_tune_blend.add_argument("--xgb-run", type=int, required=True, dest="xgb_run",
                              help="backtest_runs.id of the xgb run (same rows)")
    p_tune_blend.add_argument("--models-dir", default=None, dest="models_dir",
                              help="Save blend.json to this dir (default models/)")

    p_bf_scores = sub.add_parser("backfill-scores", help="Backfill actual final scores into games")
    p_bf_scores.add_argument("--start", metavar="YYYY-MM-DD", type=_date_arg, required=True)
    p_bf_scores.add_argument("--end", metavar="YYYY-MM-DD", type=_date_arg, required=True)

    p_compare = sub.add_parser("compare-runs", help="Side-by-side Brier + calibration across backtest runs")
    p_compare.add_argument("--runs", required=True, help="Comma-separated backtest_runs ids (e.g. 40,41,42)")

    p_train_pa = sub.add_parser(
        "train-pa", help="Per-PA multiclass outcome model spike; reports binary-market Brier vs XGB")
    p_train_pa.add_argument("--season", type=int, action="append", help="Season(s) (default 2023,2024,2025)")
    p_train_pa.add_argument("--folds", type=int, default=4, help="Walk-forward CV folds (default 4)")
    p_train_pa.add_argument("--rounds", type=int, default=300, help="Boosting rounds (default 300)")
    p_train_pa.add_argument("--save", action="store_true", default=False, help="Save pa.json for the simulator")
    p_train_pa.add_argument("--models-dir", default=None, dest="models_dir", help="Save/load dir (default models/)")

    p_sim = sub.add_parser("simulate-eval", help="Backtest the lineup run simulator vs actual scores")
    p_sim.add_argument("--start", metavar="YYYY-MM-DD", type=_date_arg, required=True)
    p_sim.add_argument("--end", metavar="YYYY-MM-DD", type=_date_arg, required=True)
    p_sim.add_argument("--models-dir", default=None, dest="models_dir", help="Load pa.json from (default models/)")
    p_sim.add_argument("--sims", type=int, default=400, help="Monte-Carlo sims per game (default 400)")
    p_sim.add_argument("--limit", type=int, default=None, help="Cap games (for a quick run)")

    p_project      = sub.add_parser("project",      help="Compute projections for today's slate")

    p_backtest = sub.add_parser("backtest", help="Run backtesting suite comparing predictions to actuals")
    p_backtest.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="First date in backtest range",
    )
    p_backtest.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, required=True,
        help="Last date in backtest range",
    )
    p_backtest.add_argument(
        "--csv", action="store_true", default=False,
        help="Write per-row predictions to /tmp/backtest_<run_id>.csv",
    )
    p_backtest.add_argument(
        "--model", choices=["mechanistic", "xgb", "blend"], default="mechanistic",
        help="Probability source: mechanistic (default), xgb, or blend (per-market w*mech+(1-w)*xgb)",
    )
    p_backtest.add_argument(
        "--models-dir", default=None, dest="models_dir",
        help="Load xgb/blend models from this dir (default models/)",
    )

    sub.add_parser("smoke",        help="DB connectivity sanity check")
    sub.add_parser("smoke-skills", help="Print top batters/pitchers from skill tables")
    p_smoke_slate    = sub.add_parser("smoke-slate",    help="Print today's slate with weather and probables")
    p_smoke_project  = sub.add_parser("smoke-project",  help="Run project and verify projection counts")

    # Shared --date flag for date-scoped commands.
    # Default is None; each command resolves it to eastern_today() if absent.
    for p in (p_slate, p_lineups, p_weather, p_project, p_smoke_slate, p_smoke_project):
        p.add_argument(
            "--date",
            metavar="YYYY-MM-DD",
            type=_date_arg,
            default=None,
            help="Date to process (default: today in US/Eastern)",
        )

    # Backtest flag: project --as-of uses snapshot tables and writes to backtest_projections.
    p_project.add_argument(
        "--as-of",
        metavar="YYYY-MM-DD",
        type=_date_arg,
        default=None,
        dest="as_of",
        help="Use skill snapshots as of this date (backtest mode)",
    )
    p_project.add_argument(
        "--model", choices=["mechanistic", "xgb", "blend"], default="blend",
        help="Probability source for live projections: blend (default; per-market "
             "w*mech+(1-w)*xgb, falls back to mechanistic if models missing), xgb, or mechanistic",
    )

    return parser


COMMANDS = {
    "load-static":              cmd_load_static,
    "backfill-stats":           cmd_backfill_stats,
    "backfill-games":           cmd_backfill_games,
    "daily-slate":              cmd_daily_slate,
    "refresh-lineups":          cmd_refresh_lineups,
    "backfill-lineups":         cmd_backfill_lineups,
    "backfill-scores":          cmd_backfill_scores,
    "refresh-weather":          cmd_refresh_weather,
    "refresh-skills":           cmd_refresh_skills,
    "refresh-skill-snapshots":  cmd_refresh_skill_snapshots,
    "refresh-pitch-aggregations": cmd_refresh_pitch_aggregations,
    "refresh-pitch-snapshots":  cmd_refresh_pitch_snapshots,
    "build-training-data":      cmd_build_training_data,
    "train-xgb":                cmd_train_xgb,
    "tune-blend":               cmd_tune_blend,
    "compare-runs":             cmd_compare_runs,
    "train-pa":                 cmd_train_pa,
    "simulate-eval":            cmd_simulate_eval,
    "project":                  cmd_project,
    "backtest":                 cmd_backtest,
    "smoke":                    cmd_smoke,
    "smoke-skills":             cmd_smoke_skills,
    "smoke-slate":              cmd_smoke_slate,
    "smoke-project":            cmd_smoke_project,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
