"""tennis-daily: run the tennis daily workflow as one command (mirrors `daily`).

Full run:   refresh-ratings -> slate -> project(scheduled) -> odds -> score
Quick (--quick): slate -> project(scheduled) -> odds   (intraday refresh)

A single args namespace is forwarded to every step (they read only what they need).
The slate + projection are fatal (no slate = no board); enhancement steps (ratings,
odds, accuracy) warn and continue so one flaky external API can't block the day's
projections. `--sample` flows to slate/odds for a no-key dry run.
"""
from __future__ import annotations

import argparse
import copy
import time

from ingester.commands.tennis_ratings import cmd_tennis_refresh_ratings
from ingester.commands.tennis_slate import cmd_tennis_slate
from ingester.commands.tennis_project import cmd_tennis_project
from ingester.commands.tennis_odds import cmd_tennis_odds
from ingester.commands.tennis_score import cmd_tennis_score


def cmd_tennis_daily(args: argparse.Namespace) -> None:
    # Shared namespace: every step reads only the attrs it needs.
    a = copy.copy(args)
    a.scheduled = True        # tennis-project projects the live slate
    a.date = None
    a.calibrate = False
    a.as_of = None
    a.start = None
    a.end = None

    if getattr(args, "quick", False):
        steps = [
            ("tennis-slate", cmd_tennis_slate, True),
            ("tennis-project (scheduled)", cmd_tennis_project, True),
            ("tennis-odds", cmd_tennis_odds, False),
        ]
    else:
        steps = [
            ("tennis-refresh-ratings", cmd_tennis_refresh_ratings, False),
            ("tennis-slate", cmd_tennis_slate, True),
            ("tennis-project (scheduled)", cmd_tennis_project, True),
            ("tennis-odds", cmd_tennis_odds, False),
            ("tennis-score", cmd_tennis_score, False),
        ]
        if getattr(args, "skip_ratings", False):
            steps = [s for s in steps if s[0] != "tennis-refresh-ratings"]

    print(f"[tennis-daily] {' -> '.join(name for name, _, _ in steps)}\n")
    overall_start = time.monotonic()
    warnings: list[str] = []
    for i, (name, fn, fatal) in enumerate(steps, 1):
        print(f"[tennis-daily] ({i}/{len(steps)}) {name} …")
        step_start = time.monotonic()
        try:
            fn(a)
        except Exception as exc:  # noqa: BLE001
            if fatal:
                print(f"\n[tennis-daily] FAILED at step {i}/{len(steps)} ({name}): {exc}")
                raise
            print(f"[tennis-daily] ⚠ {name} failed (non-fatal): {exc} — continuing\n")
            warnings.append(name)
            continue
        print(f"[tennis-daily] ✓ {name} ({time.monotonic() - step_start:.1f}s)\n")

    elapsed = time.monotonic() - overall_start
    tail = f" with {len(warnings)} warning(s) [{', '.join(warnings)}]" if warnings else ""
    print(f"[tennis-daily] done{tail} — {len(steps)} steps in {elapsed:.1f}s")
