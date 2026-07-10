"""daily workflow step ordering.

The afternoon quick loop (--quick) must re-run daily-slate: it's the only command that
persists games.{home,away}_probable_pitcher_id, and late games' probables aren't known
at the 9am full run. Without it those games stay "missing probable pitcher" and the
projector skips them all day (late/West-Coast games never got projected).
"""
from __future__ import annotations

import argparse
import os
import unittest
from datetime import date
from unittest import mock

from ingester.commands import daily


# Every (name, module-attr) the daily workflow may invoke, including the ones the
# _grade_today / _close_prior_slate helpers call. Patching them all lets us run cmd_daily
# end to end and just record the order in which steps fire.
_STEP_ATTRS = [
    "cmd_daily_slate",
    "cmd_refresh_weather",
    "cmd_refresh_umpires",
    "cmd_refresh_skills",
    "cmd_refresh_bullpen",
    "cmd_refresh_team_defense",
    "cmd_refresh_lineups",
    "cmd_project",
    "cmd_refresh_odds",
    "cmd_record_picks",
    "cmd_backfill_scores",
    "cmd_backfill_stats",
    "cmd_backfill_pitcher_starts",
    "cmd_backfill_batter_lines",
    "cmd_score_picks",
    "cmd_compute_accuracy",
]


def _run_daily(quick: bool) -> list[str]:
    """Run cmd_daily with all step fns stubbed; return the order they were called."""
    calls: list[str] = []
    args = argparse.Namespace(date=date(2026, 6, 21), season=None, quick=quick)

    patchers = {
        attr: mock.patch.object(
            daily, attr, side_effect=lambda _a, _n=attr: calls.append(_n)
        )
        for attr in _STEP_ATTRS
    }
    for p in patchers.values():
        p.start()
    try:
        # The run-log is on by default and get_connection() reads .env, so without this the
        # test would write real pipeline_runs rows into whatever dev DB is configured.
        with mock.patch.dict(os.environ, {"DIAMOND_RUNLOG_ENABLED": "0"}):
            daily.cmd_daily(args)
    finally:
        for p in patchers.values():
            p.stop()
    return calls


class TestDailyQuickWorkflow(unittest.TestCase):
    def test_quick_loop_runs_daily_slate_before_project(self):
        calls = _run_daily(quick=True)
        self.assertIn(
            "cmd_daily_slate",
            calls,
            "quick loop must re-fetch the slate so late probables get persisted",
        )
        self.assertLess(
            calls.index("cmd_daily_slate"),
            calls.index("cmd_project"),
            "daily-slate must run before project so refreshed probables are used",
        )

    def test_full_run_still_includes_daily_slate(self):
        calls = _run_daily(quick=False)
        self.assertIn("cmd_daily_slate", calls)
        self.assertLess(
            calls.index("cmd_daily_slate"), calls.index("cmd_project")
        )


if __name__ == "__main__":
    unittest.main()
