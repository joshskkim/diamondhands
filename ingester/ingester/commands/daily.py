"""daily: run the standard daily workflow as one command (quality-of-life wrapper).

Chains the steps documented in the README's "Typical daily workflow":

    daily-slate -> refresh-weather -> refresh-skills -> refresh-lineups -> project

Each underlying command reads only the attributes it needs off the shared args
namespace (``date``, ``season``, ``model``, ``as_of``), so we forward a single
namespace to all of them. Steps run in order and the chain stops on the first
failure so a half-built slate is obvious rather than silent.
"""
from __future__ import annotations

import argparse
import time

from ingester.db import eastern_today
from ingester.commands.daily_slate import cmd_daily_slate
from ingester.commands.refresh_weather import cmd_refresh_weather
from ingester.commands.refresh_skills import cmd_refresh_skills
from ingester.commands.lineups import cmd_refresh_lineups
from ingester.commands.odds import cmd_refresh_odds
from ingester.projection.runner import cmd_project


def cmd_daily(args: argparse.Namespace) -> None:
    target = args.date if getattr(args, "date", None) is not None else eastern_today()

    # Build the ordered step list. --quick is the afternoon re-projection loop
    # (lineups trickle in, project clears+recomputes the slate); --skip-skills
    # drops the slow ~1.5 min skills recompute when it isn't needed yet.
    if getattr(args, "quick", False):
        steps = [
            ("refresh-lineups", cmd_refresh_lineups),
            ("project", cmd_project),
            ("refresh-odds", cmd_refresh_odds),
        ]
    else:
        steps = [
            ("daily-slate", cmd_daily_slate),
            ("refresh-weather", cmd_refresh_weather),
            ("refresh-skills", cmd_refresh_skills),
            ("refresh-lineups", cmd_refresh_lineups),
            ("project", cmd_project),
            ("refresh-odds", cmd_refresh_odds),
        ]
        if getattr(args, "skip_skills", False):
            steps = [s for s in steps if s[0] != "refresh-skills"]

    names = " -> ".join(name for name, _ in steps)
    print(f"[daily] {target}: {names}\n")

    overall_start = time.monotonic()
    for i, (name, fn) in enumerate(steps, 1):
        print(f"[daily] ({i}/{len(steps)}) {name} …")
        step_start = time.monotonic()
        try:
            fn(args)
        except Exception as exc:  # noqa: BLE001 — surface which step failed, then re-raise
            print(f"\n[daily] FAILED at step {i}/{len(steps)} ({name}): {exc}")
            raise
        print(f"[daily] ✓ {name} ({time.monotonic() - step_start:.1f}s)\n")

    print(f"[daily] done — {len(steps)} steps in {time.monotonic() - overall_start:.1f}s")
