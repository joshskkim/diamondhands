"""Tests for lineup-aware PA weighting (v2.0 Sprint 1).

Covers the PA_BY_ORDER mapping and _resolve_lineup's confirmed-vs-projected branching.
_resolve_lineup is exercised with a fake connection so no database is required: the
confirmed branch reads canned game_lineups rows; the projected fallback branch reads a
prior game's confirmed lineup (a separate query, distinguished by the fake on SQL text).
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
    """Returns the same canned rows for the single game_lineups query in _resolve_lineup."""

    def __init__(self, lineup_rows):
        self._lineup_rows = lineup_rows

    def execute(self, sql, params=None):
        return _FakeResult(self._lineup_rows)


class _FakeConnWithPrior:
    """Distinguishes the current-game query from the prior-lineup fallback by SQL text.

    The fallback query (_resolve_projected_lineup) is the one with the ``last_game`` CTE;
    everything else is treated as the current game's game_lineups read.
    """

    def __init__(self, current_rows, prior_rows):
        self._current_rows = current_rows
        self._prior_rows = prior_rows

    def execute(self, sql, params=None):
        if "last_game" in sql:
            return _FakeResult(self._prior_rows)
        return _FakeResult(self._current_rows)


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
        # Guard: the confirmed branch must NOT consult the projected fallback.
        monkeypatch.setattr(
            runner, "_resolve_projected_lineup",
            lambda *a, **k: pytest.fail("projected fallback used for a confirmed lineup"),
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

    def test_projected_fallback_uses_prior_lineup(self):
        # No confirmed lineup for this game, but the team has a prior confirmed nine →
        # project it, flagged lineup_confirmed=False, keeping PA_BY_ORDER weighting.
        prior = [(order, 2000 + order, "L") for order in range(1, 10)]
        conn = _FakeConnWithPrior(current_rows=[], prior_rows=prior)

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=True, as_of=_AS_OF
        )

        assert len(hitters) == 9
        assert all(not h.lineup_confirmed for h in hitters)
        assert [h.lineup_position for h in hitters] == list(range(1, 10))
        assert [h.expected_pa for h in hitters] == [PA_BY_ORDER[i] for i in range(1, 10)]
        assert hitters[0].player_id == 2001

    def test_no_lineup_and_no_prior_returns_empty(self):
        # No confirmed slots and no prior lineup → no projection for this side.
        conn = _FakeConnWithPrior(current_rows=[], prior_rows=[])

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=False, as_of=_AS_OF
        )

        assert hitters == []

    def test_partial_current_falls_back_to_prior(self):
        # Fewer than nine current slots is not a confirmation → fall back to the prior nine.
        conn = _FakeConnWithPrior(
            current_rows=[(order, 1000 + order, "R") for order in range(1, 6)],  # 5 slots
            prior_rows=[(order, 2000 + order, "R") for order in range(1, 10)],
        )

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=True, as_of=_AS_OF
        )

        assert len(hitters) == 9
        assert all(not h.lineup_confirmed for h in hitters)
        assert hitters[0].player_id == 2001

    def test_partial_current_and_partial_prior_returns_empty(self):
        # Neither a full current nor a full prior nine → no projection (no half-guess).
        conn = _FakeConnWithPrior(
            current_rows=[(order, 1000 + order, "R") for order in range(1, 6)],
            prior_rows=[(order, 2000 + order, "R") for order in range(1, 4)],
        )

        hitters = runner._resolve_lineup(
            conn, game_id=1, team_id=2, is_home=True, as_of=_AS_OF
        )

        assert hitters == []
