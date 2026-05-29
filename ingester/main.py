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
"""

import argparse
import sys
from pathlib import Path

from ingester.commands.load_static import cmd_load_static


# ---------------------------------------------------------------------------
# Subcommand stubs
# ---------------------------------------------------------------------------

def cmd_backfill_stats(args: argparse.Namespace) -> None:
    """Pull historical game-level stats via pybaseball and upsert player_game_stats."""
    print("[backfill-stats] stub — not yet implemented")


def cmd_daily_slate(args: argparse.Namespace) -> None:
    """Fetch today's scheduled games + probable pitchers from the MLB Stats API."""
    print("[daily-slate] stub — not yet implemented")


def cmd_refresh_weather(args: argparse.Namespace) -> None:
    """Fetch weather for each stadium hosting a game today and store on games row."""
    print("[refresh-weather] stub — not yet implemented")


def cmd_refresh_skills(args: argparse.Namespace) -> None:
    """Recompute batter_skill and pitcher_skill from player_game_stats."""
    print("[refresh-skills] stub — not yet implemented")


def cmd_project(args: argparse.Namespace) -> None:
    """Generate batter_projections and game_projections for today's slate."""
    print("[project] stub — not yet implemented")


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
    sub.add_parser("backfill-stats",  help="Pull historical game logs via pybaseball")
    sub.add_parser("daily-slate",     help="Fetch today's games + probable pitchers")
    sub.add_parser("refresh-weather", help="Attach weather to today's games")
    sub.add_parser("refresh-skills",  help="Recompute batter/pitcher skill aggregates")
    sub.add_parser("project",         help="Compute projections for today's slate")
    sub.add_parser("smoke",           help="End-to-end sanity check")

    return parser


COMMANDS = {
    "load-static":     cmd_load_static,
    "backfill-stats":  cmd_backfill_stats,
    "daily-slate":     cmd_daily_slate,
    "refresh-weather": cmd_refresh_weather,
    "refresh-skills":  cmd_refresh_skills,
    "project":         cmd_project,
    "smoke":           cmd_smoke,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
