"""Tests for lineup-aware PA weighting (v2.0 Sprint 1).

Covers the PA_BY_ORDER mapping and _resolve_lineup's confirmed-vs-predicted branching.
_resolve_lineup is exercised with a fake connection so no database is required: the
confirmed branch reads canned game_lineups rows; the predicted fallback resolves empty
when the fake returns no recent-usage history.
"""
from __future__ import annotations

from datetime import date

import pytest

from ingester.projection import runner
from ingester.projection.constants import EXPECTED_PA_PER_STARTER, PA_BY_ORDER


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Routes _resolve_lineup's game_lineups read to canned rows; any other query
    (the predicted-lineup fallback's recent-usage / roster reads) returns nothing,
    so the fallback resolves to an empty predicted lineup."""

    def __init__(self, lineup_rows):
        self._lineup_rows = lineup_rows

    def execute(self, sql, params=None):
        if "gl.batting_order" in sql and "recent_games" not in sql:
            return _FakeResult(self._lineup_rows)
        return _FakeResult([])


_AS_OF = date(2025, 4, 15)


# ---------------------------------------------------------------------------
# PA_BY_ORDER mapping
# ---------------------------------------------------------------------------

class TestPaByOrder:
    def test_covers_all_nine_slots(self):
        assert sorted(PA_BY_ORDER.keys()) == list(range(1, 10))

    def test_exact_values(self):
        assert PA_BY_ORDER == {
            1: 4.62, 2: 4.51, 3: 4.40, 4: 4.30, 5: 4.20,
            6: 4.10, 7: 4.00, 8: 3.90, 9: 3.80,
        }

    def test_monotonic_decreasing(self):
        values = [PA_BY_ORDER[i] for i in range(1, 10)]
        assert all(earlier > later for earlier, later in zip(values, values[1:]))

    def test_leadoff_gets_most_nine_hole_least(self):
        assert PA_BY_ORDER[1] == max(PA_BY_ORDER.values())
        assert PA_BY_ORDER[9] == min(PA_BY_ORDER.values())

    def test_fallback_constant(self):
        # Projected lineups use the flat per-starter PA, which sits mid-order.
        assert EXPECTED_PA_PER_STARTER == 4.0


# ---------------------------------------------------------------------------
# _resolve_lineup
# ---------------------------------------------------------------------------

class TestResolveLineup:
    def test_confirmed_lineup_uses_pa_by_order(self, monkeypatch):
        # Guard: the confirmed branch must NOT consult the L30 proxy.
        monkeypatch.setattr(
            runner, "_likely_hitters",
            lambda *a, **k: pytest.fail("_likely_hitters called for a confirmed lineup"),
        )
        # rows: (batting_order, player_id, bats)
        rows = [(order, 1000 + order, "R") for order in range(1, 10)]
        conn = _FakeConn(rows)

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=True, as_of=_AS_OF
        )

        assert len(hitters) == 9
        assert all(h.lineup_confirmed for h in hitters)
        assert [h.lineup_position for h in hitters] == list(range(1, 10))
        assert [h.expected_pa for h in hitters] == [PA_BY_ORDER[i] for i in range(1, 10)]
        # Leadoff hitter: highest PA, player_id 1001.
        assert hitters[0].player_id == 1001
        assert hitters[0].expected_pa == 4.62
        assert hitters[-1].expected_pa == 3.80

    def test_no_lineup_returns_empty(self):
        # No confirmed slots → no projection for this side (we don't guess the lineup).
        conn = _FakeConn([])

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=False, as_of=_AS_OF
        )

        assert hitters == []

    def test_partial_lineup_falls_back_to_predicted(self):
        # Fewer than nine posted slots is not a confirmation → the predicted-lineup
        # fallback runs; with no recent-usage history it resolves to [] (skip the side).
        conn = _FakeConn([(order, 1000 + order, "R") for order in range(1, 6)])  # 5 slots

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=True, as_of=_AS_OF
        )

        assert hitters == []
