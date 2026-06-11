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
import copy
import time
from datetime import timedelta

from ingester.db import eastern_today
from ingester.commands.accuracy import cmd_compute_accuracy
from ingester.commands.backfill_stats import cmd_backfill_stats
from ingester.commands.daily_slate import cmd_daily_slate
from ingester.commands.picks import cmd_record_picks, cmd_score_picks
from ingester.commands.refresh_weather import cmd_refresh_weather
from ingester.commands.refresh_umpires import cmd_refresh_umpires
from ingester.commands.refresh_skills import cmd_refresh_skills
from ingester.commands.refresh_bullpen import cmd_refresh_bullpen
from ingester.commands.lineups import cmd_refresh_lineups
from ingester.commands.odds import cmd_refresh_odds
from ingester.commands.scores import cmd_backfill_scores
from ingester.projection.runner import cmd_project


def cmd_daily(args: argparse.Namespace) -> None:
    target = args.date if getattr(args, "date", None) is not None else eastern_today()

    def _close_prior_slate(_args: argparse.Namespace) -> None:
        """Close the books on the PRIOR slate (its actuals exist by now):
        ingest final scores + player stats, grade the recorded picks, and write
        the daily_accuracy snapshot. Substeps are individually guarded so one
        flaky source doesn't lose the rest; props that still lack player stats
        stay pending and are retried on the next nightly run.

        This ordering matters: project preserves prior-slate projections
        (_clear_slate_projections deletes only the target date), so the rows
        compute-accuracy joins against are still there."""
        prior = copy.copy(_args)
        prior.date = target - timedelta(days=1)
        prior.start = prior.date
        prior.end = prior.date
        prior.season = prior.date.year
        for name, fn in (
            ("backfill-scores", cmd_backfill_scores),
            ("backfill-stats", cmd_backfill_stats),
            ("score-picks", cmd_score_picks),
            ("compute-accuracy", cmd_compute_accuracy),
        ):
            try:
                fn(prior)
            except Exception as exc:  # noqa: BLE001
                print(f"[daily]   ⚠ close-prior-slate/{name} failed: {exc} — continuing")

    # Build the ordered step list. --quick is the afternoon re-projection loop
    # (lineups trickle in, project clears+recomputes the slate); --skip-skills
    # drops the slow ~1.5 min skills recompute when it isn't needed yet.
    # Each step is (name, fn, fatal). Only the core path (get the slate, project it) is
    # fatal; enhancement steps (weather, umpires, bullpen, odds, accuracy) warn and continue
    # so one flaky external API can't block the day's projections.
    if getattr(args, "quick", False):
        steps = [
            ("refresh-lineups", cmd_refresh_lineups, False),
            ("project", cmd_project, True),
            ("refresh-odds", cmd_refresh_odds, False),
            ("record-picks", cmd_record_picks, False),
        ]
    else:
        steps = [
            ("daily-slate", cmd_daily_slate, True),
            ("refresh-weather", cmd_refresh_weather, False),
            ("refresh-umpires", cmd_refresh_umpires, False),
            ("refresh-skills", cmd_refresh_skills, False),
            ("refresh-bullpen", cmd_refresh_bullpen, False),
            ("refresh-lineups", cmd_refresh_lineups, False),
            ("project", cmd_project, True),
            ("refresh-odds", cmd_refresh_odds, False),
            ("record-picks", cmd_record_picks, False),
            ("close prior slate (scores+stats+picks+accuracy)", _close_prior_slate, False),
        ]
        if getattr(args, "skip_skills", False):
            # Both skills and bullpen do the slow Statcast-cache re-aggregation.
            steps = [s for s in steps if s[0] not in ("refresh-skills", "refresh-bullpen")]

    names = " -> ".join(name for name, _, _ in steps)
    print(f"[daily] {target}: {names}\n")

    overall_start = time.monotonic()
    warnings: list[str] = []
    for i, (name, fn, fatal) in enumerate(steps, 1):
        print(f"[daily] ({i}/{len(steps)}) {name} …")
        step_start = time.monotonic()
        try:
            fn(args)
        except Exception as exc:  # noqa: BLE001
            if fatal:
                print(f"\n[daily] FAILED at step {i}/{len(steps)} ({name}): {exc}")
                raise
            print(f"[daily] ⚠ {name} failed (non-fatal): {exc} — continuing\n")
            warnings.append(name)
            continue
        print(f"[daily] ✓ {name} ({time.monotonic() - step_start:.1f}s)\n")

    elapsed = time.monotonic() - overall_start
    if warnings:
        print(f"[daily] done with {len(warnings)} warning(s) [{', '.join(warnings)}] "
              f"— {len(steps)} steps in {elapsed:.1f}s")
    else:
        print(f"[daily] done — {len(steps)} steps in {elapsed:.1f}s")
