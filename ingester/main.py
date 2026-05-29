"""
Diamond MLB Projection Ingester
================================
Usage:
    uv run python main.py <subcommand> [options]

Subcommands:
    load-static      Seed teams and stadiums from /data/stadiums.json
    backfill-stats   Pull historical player_game_stats via pybaseball
    daily-slate      Fetch today's games + probable pitchers from MLB Stats API
    refresh-weather  Attach weather snapshot to today's games
    refresh-skills   Recompute batter_skill and pitcher_skill aggregates
    project          Compute batter_projections for today's slate
    smoke            End-to-end sanity check (read-only)
    smoke-project    Run project + verify projection row counts
"""

import argparse
import sys
from datetime import date
from pathlib import Path

from ingester.commands.load_static import cmd_load_static
from ingester.commands.backfill_stats import cmd_backfill_stats
from ingester.commands.daily_slate import cmd_daily_slate
from ingester.commands.refresh_weather import cmd_refresh_weather
from ingester.commands.refresh_skills import cmd_refresh_skills
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

    p_slate   = sub.add_parser("daily-slate",     help="Fetch today's games + probable pitchers")
    p_weather = sub.add_parser("refresh-weather", help="Attach weather to today's games")

    p_skills = sub.add_parser("refresh-skills", help="Recompute batter/pitcher skill aggregates")
    p_skills.add_argument("--season", type=int, default=2025, help="Season year (default: 2025)")

    p_project      = sub.add_parser("project",      help="Compute projections for today's slate")
    sub.add_parser("smoke",        help="DB connectivity sanity check")
    sub.add_parser("smoke-skills", help="Print top batters/pitchers from skill tables")
    p_smoke_slate    = sub.add_parser("smoke-slate",    help="Print today's slate with weather and probables")
    p_smoke_project  = sub.add_parser("smoke-project",  help="Run project and verify projection counts")

    # Shared --date flag for date-scoped commands.
    # Default is None; each command resolves it to eastern_today() if absent.
    for p in (p_slate, p_weather, p_project, p_smoke_slate, p_smoke_project):
        p.add_argument(
            "--date",
            metavar="YYYY-MM-DD",
            type=_date_arg,
            default=None,
            help="Date to process (default: today in US/Eastern)",
        )

    return parser


COMMANDS = {
    "load-static":     cmd_load_static,
    "backfill-stats":  cmd_backfill_stats,
    "daily-slate":     cmd_daily_slate,
    "refresh-weather": cmd_refresh_weather,
    "refresh-skills":  cmd_refresh_skills,
    "project":         cmd_project,
    "smoke":           cmd_smoke,
    "smoke-skills":    cmd_smoke_skills,
    "smoke-slate":     cmd_smoke_slate,
    "smoke-project":   cmd_smoke_project,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
