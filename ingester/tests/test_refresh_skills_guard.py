"""Tests for the barrel-coverage guard in refresh-skills (pure, no DB)."""
from __future__ import annotations

from ingester.commands.refresh_skills import barrel_coverage_warning


class TestBarrelCoverageWarning:
    def test_warns_when_all_batters_missing_barrel(self):
        msg = barrel_coverage_warning(2026, n_batters=515, n_with_barrel=0)
        assert msg is not None
        assert "no prior-season (2025) barrel" in msg
        assert "refresh-batted-ball --season 2025" in msg  # actionable fix
        assert "515" in msg

    def test_silent_when_barrel_present(self):
        # Any coverage at all → no warning (partial coverage is expected/normal).
        assert barrel_coverage_warning(2026, n_batters=515, n_with_barrel=395) is None
        assert barrel_coverage_warning(2026, n_batters=515, n_with_barrel=1) is None

    def test_silent_when_no_batters(self):
        # Nothing to project → not a barrel problem, stay quiet.
        assert barrel_coverage_warning(2026, n_batters=0, n_with_barrel=0) is None

    def test_message_uses_prior_season(self):
        # Guard reports season-1 (the season whose batted-ball feeds barrel).
        msg = barrel_coverage_warning(2025, n_batters=10, n_with_barrel=0)
        assert "2024" in msg and "refresh-batted-ball --season 2024" in msg
