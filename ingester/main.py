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
    refresh-umpires  Capture home-plate umpire assignments + recompute tendencies
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
from ingester.commands.daily import cmd_daily
from ingester.commands.odds import cmd_refresh_odds
from ingester.commands.lineups import cmd_backfill_lineups, cmd_refresh_lineups
from ingester.commands.scores import cmd_backfill_scores
from ingester.commands.backfill_pitcher_starts import cmd_backfill_pitcher_starts
from ingester.commands.backfill_weather import cmd_backfill_weather
from ingester.commands.refresh_weather import cmd_refresh_weather
from ingester.commands.refresh_umpires import cmd_refresh_umpires
from ingester.commands.refresh_skills import cmd_refresh_skills
from ingester.commands.refresh_priors import cmd_refresh_priors
from ingester.commands.backfill_birthdates import cmd_backfill_birthdates
from ingester.commands.ingest_steamer import cmd_ingest_steamer
from ingester.commands.refresh_bullpen import cmd_refresh_bullpen
from ingester.commands.refresh_batted_ball import cmd_refresh_batted_ball
from ingester.commands.skill_snapshots import cmd_refresh_skill_snapshots
from ingester.commands.pitch_aggregations import (
    cmd_refresh_pitch_aggregations,
    cmd_refresh_pitch_snapshots,
)
from ingester.commands.backtest import cmd_backtest
from ingester.commands.accuracy import cmd_compute_accuracy
from ingester.commands.picks import cmd_record_picks, cmd_score_picks
from ingester.ml.dataset import cmd_build_training_data
from ingester.ml.train import cmd_train_xgb, cmd_tune_blend
from ingester.ml.perpa import cmd_train_pa
from ingester.commands.simulate_eval import cmd_simulate_eval
from ingester.commands.report import cmd_compare_runs
from ingester.commands.fit_calibration import cmd_fit_calibration
from ingester.commands.smoke import cmd_smoke_skills, cmd_smoke_slate
from ingester.db import eastern_today
from ingester.projection.runner import cmd_project, cmd_smoke_project


def _date_arg(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid date {s!r} — expected YYYY-MM-DD (e.g. 2026-04-15)"
        )


# Default --season for refresh/backfill commands: the season in progress (Eastern
# clock, so a late-night Pacific run doesn't roll to the wrong year). A hardcoded
# year here once went stale at the season turnover and silently kept the nightly
# pipeline aggregating the PRIOR season's skills all spring.
CURRENT_SEASON = eastern_today().year


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
    p_backfill.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")

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

    p_umpires = sub.add_parser(
        "refresh-umpires",
        help="Capture home-plate umpire assignments + recompute umpire tendencies",
    )
    p_umpires.add_argument(
        "--start", metavar="YYYY-MM-DD", type=_date_arg, default=None,
        help="Backfill range start (use with --end; default is single --date)",
    )
    p_umpires.add_argument(
        "--end", metavar="YYYY-MM-DD", type=_date_arg, default=None,
        help="Backfill range end (use with --start)",
    )

    p_odds = sub.add_parser("refresh-odds", help="Pull sportsbook odds (game markets + player props)")
    p_odds.add_argument(
        "--sample", action="store_true", default=False,
        help="Use bundled fixtures instead of the API (no key / no credit spend)",
    )
    p_odds.add_argument(
        "--force", action="store_true", default=False,
        help="Bypass the input-hash cache gate and re-pull every slate game",
    )

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
    p_skills.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")

    p_priors = sub.add_parser(
        "refresh-priors",
        help="Compute Marcel-style multi-year true-talent priors into batter_projection_prior",
    )
    p_priors.add_argument("--season", type=int, default=2026, help="Target season year (default: 2026)")

    p_birth = sub.add_parser(
        "backfill-birthdates", help="Populate players.birth_date from the MLB Stats API (aging curve)"
    )
    p_birth.add_argument("--all", action="store_true", default=False, help="Refresh every player, not just NULLs")

    p_steamer = sub.add_parser(
        "ingest-steamer",
        help="Load a FanGraphs Steamer projection CSV into batter_projection_prior (true-talent prior)",
    )
    p_steamer.add_argument("--csv", required=True, metavar="PATH", help="Steamer batter projections CSV export")
    p_steamer.add_argument("--season", type=int, default=2026, help="Target season year (default: 2026)")
    p_steamer.add_argument("--method", default="steamer", help="Tag stored in batter_projection_prior.method")

    p_bullpen = sub.add_parser(
        "refresh-bullpen", help="Aggregate per-team relief-pitching skill into bullpen_skill"
    )
    p_bullpen.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")

    p_batted = sub.add_parser(
        "refresh-batted-ball",
        help="Aggregate per-batter spray / batted-ball profiles from Statcast into batter_batted_ball",
    )
    p_batted.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")

    p_snapshots = sub.add_parser(
        "refresh-skill-snapshots",
        help="Compute point-in-time skill snapshots for backtesting",
    )
    p_snapshots.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")
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
    p_pitch_agg.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")
    p_pitch_agg.add_argument(
        "--as-of", metavar="YYYY-MM-DD", type=_date_arg, default=None, dest="as_of",
        help="Aggregate season-to-date through this date (default: today in US/Eastern)",
    )

    p_pitch_snap = sub.add_parser(
        "refresh-pitch-snapshots",
        help="Backfill point-in-time pitch-mix snapshots (one per Monday) for backtesting",
    )
    p_pitch_snap.add_argument("--season", type=int, default=CURRENT_SEASON, help="Season year (default: current season)")
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

    p_bf_starts = sub.add_parser(
        "backfill-pitcher-starts",
        help="Backfill per-start pitcher workload lines (outs/BF/K/ER/pitches) from boxscores",
    )
    p_bf_starts.add_argument("--start", metavar="YYYY-MM-DD", type=_date_arg, default=None)
    p_bf_starts.add_argument("--end", metavar="YYYY-MM-DD", type=_date_arg, default=None)

    p_bf_weather = sub.add_parser(
        "backfill-weather",
        help="Backfill actual historical weather (Open-Meteo archive) so backtests can use it",
    )
    p_bf_weather.add_argument("--start", metavar="YYYY-MM-DD", type=_date_arg, required=True)
    p_bf_weather.add_argument("--end", metavar="YYYY-MM-DD", type=_date_arg, required=True)

    p_compare = sub.add_parser("compare-runs", help="Side-by-side Brier + calibration across backtest runs")
    p_compare.add_argument("--runs", required=True, help="Comma-separated backtest_runs ids (e.g. 40,41,42)")

    p_fit_cal = sub.add_parser(
        "fit-calibration",
        help="Fit per-market probability calibration (isotonic) from a backtest run → models/calibration.json",
    )
    p_fit_cal.add_argument("--run", type=int, required=True, help="backtest_runs.id to fit from")
    p_fit_cal.add_argument("--models-dir", default=None, dest="models_dir",
                           help="Write calibration.json to this dir (default models/)")

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

    p_daily = sub.add_parser(
        "daily",
        help="Run the full daily workflow in sequence: "
             "slate -> weather -> skills -> lineups -> project",
    )
    p_daily.add_argument(
        "--season", type=int, default=None,
        help="Season year for skills (default: the slate date's year)",
    )
    p_daily.add_argument(
        "--model", choices=["mechanistic", "xgb", "blend"], default="mechanistic",
        help="Probability source for project (default: mechanistic — the backtest-validated path)",
    )
    p_daily.add_argument(
        "--skip-skills", action="store_true", default=False, dest="skip_skills",
        help="Skip the ~1.5 min refresh-skills step (run it separately when needed)",
    )
    p_daily.add_argument(
        "--quick", action="store_true", default=False,
        help="Afternoon loop: only refresh-lineups then project",
    )

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
    p_backtest.add_argument(
        "--calibrate", action="store_true", default=False,
        help="Apply models/calibration.json per-market probability calibration (S3)",
    )
    p_backtest.add_argument(
        "--park-personalized", action="store_true", default=False, dest="park_personalized",
        help="Personalize park HR factor from each hitter's prior-season batted-ball profile (leak-free A/B)",
    )
    p_backtest.add_argument(
        "--weather-carry", action="store_true", default=False, dest="weather_carry",
        help="HR weather via the trajectory carry model with spray-weighted wind, prior-season profiles (leak-free A/B)",
    )

    p_accuracy = sub.add_parser(
        "compute-accuracy",
        help="Score one slate's projections vs actuals into daily_accuracy (per-market snapshot)",
    )
    p_accuracy.add_argument(
        "--date", metavar="YYYY-MM-DD", type=_date_arg, default=None,
        help="Slate date to score (default: yesterday in US/Eastern — actuals exist by then)",
    )

    p_rec_picks = sub.add_parser(
        "record-picks",
        help="Persist today's Model's Picks server-side (same bar as the home board)",
    )
    p_rec_picks.add_argument(
        "--date", metavar="YYYY-MM-DD", type=_date_arg, default=None,
        help="Slate date (default: today in US/Eastern)",
    )
    p_rec_picks.add_argument(
        "--api", default=None,
        help="API base URL serving /api/odds/best (default: http://localhost:8080)",
    )

    p_score_picks = sub.add_parser(
        "score-picks",
        help="Grade a prior slate's recorded Model's Picks against actual results",
    )
    p_score_picks.add_argument(
        "--date", metavar="YYYY-MM-DD", type=_date_arg, default=None,
        help="Slate date to score (default: yesterday in US/Eastern)",
    )

    sub.add_parser("smoke",        help="DB connectivity sanity check")
    sub.add_parser("smoke-skills", help="Print top batters/pitchers from skill tables")
    p_smoke_slate    = sub.add_parser("smoke-slate",    help="Print today's slate with weather and probables")
    p_smoke_project  = sub.add_parser("smoke-project",  help="Run project and verify projection counts")

    # Shared --date flag for date-scoped commands.
    # Default is None; each command resolves it to eastern_today() if absent.
    for p in (p_slate, p_lineups, p_weather, p_umpires, p_odds, p_project, p_daily, p_smoke_slate, p_smoke_project):
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
        "--model", choices=["mechanistic", "xgb", "blend"], default="mechanistic",
        # Default flipped blend -> mechanistic (Jun 2026): the blend's weights were tuned
        # on the pre-v2.4 model and hand batter props ~100% to a stale XGB whose live
        # output degenerated (quantized probs ~15pts under market -> phantom edges; the
        # 0/3 Model's Picks day). Backtests validate the MECHANISTIC path; serve that.
        # Re-enable blend only after retraining + re-tuning + live validation.
        help="Probability source for live projections: mechanistic (default; the "
             "backtest-validated path), xgb, or blend (per-market w*mech+(1-w)*xgb)",
    )
    p_project.add_argument(
        "--no-calibrate", action="store_true", default=False, dest="no_calibrate",
        help="Disable the per-market probability calibration that project applies by "
             "default when models/calibration.json exists (S3 accuracy feedback loop)",
    )
    p_project.add_argument(
        "--models-dir", default=None, dest="models_dir",
        help="Load calibration.json / xgb models from this dir (default models/)",
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
    "backfill-pitcher-starts":  cmd_backfill_pitcher_starts,
    "backfill-weather":         cmd_backfill_weather,
    "refresh-weather":          cmd_refresh_weather,
    "refresh-umpires":          cmd_refresh_umpires,
    "refresh-skills":           cmd_refresh_skills,
    "refresh-priors":           cmd_refresh_priors,
    "backfill-birthdates":      cmd_backfill_birthdates,
    "ingest-steamer":           cmd_ingest_steamer,
    "refresh-bullpen":          cmd_refresh_bullpen,
    "refresh-batted-ball":      cmd_refresh_batted_ball,
    "refresh-skill-snapshots":  cmd_refresh_skill_snapshots,
    "refresh-pitch-aggregations": cmd_refresh_pitch_aggregations,
    "refresh-pitch-snapshots":  cmd_refresh_pitch_snapshots,
    "build-training-data":      cmd_build_training_data,
    "train-xgb":                cmd_train_xgb,
    "tune-blend":               cmd_tune_blend,
    "compare-runs":             cmd_compare_runs,
    "fit-calibration":          cmd_fit_calibration,
    "train-pa":                 cmd_train_pa,
    "simulate-eval":            cmd_simulate_eval,
    "project":                  cmd_project,
    "daily":                    cmd_daily,
    "refresh-odds":             cmd_refresh_odds,
    "backtest":                 cmd_backtest,
    "compute-accuracy":         cmd_compute_accuracy,
    "record-picks":             cmd_record_picks,
    "score-picks":              cmd_score_picks,
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
