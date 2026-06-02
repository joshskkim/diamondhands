"""build_feature_row must be point-in-time (as-of bound) and contain only features."""
from __future__ import annotations

from datetime import date

from ingester.ml.features import FEATURE_COLUMNS, build_feature_row, effective_bat_side
from ingester.projection.park_adj import ParkFactors

AS_OF = date(2025, 6, 1)
PARK = ParkFactors(park_factor_hits=1.02, park_factor_hr_lhb=1.10, park_factor_hr_rhb=0.95)

# _read_batter_snapshot SELECT order.
_BATTER_ROW = (0.360, 0.345, 0.220, 0.230, 0.180, 0.170, 120,  # xwoba..pa_l30
               0.350, 0.085, 0.300, 0.090, 0.420, 480)          # woba..plate_appearances
# _read_pitcher_snapshot SELECT order.
_PITCHER_ROW = (0.310, 0.305, 0.240, 0.075, 0.032, 0.205, 350)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Routes by table; records (sql, params) so tests can assert the as-of bound."""

    def __init__(self, batter_row, pitcher_row):
        self._batter = [batter_row] if batter_row else []
        self._pitcher = [pitcher_row] if pitcher_row else []
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM batter_skill_snapshots" in sql:
            return _Result(self._batter)
        if "FROM pitcher_skill_snapshots" in sql:
            return _Result(self._pitcher)
        # pitcher_arsenal (matchup) → empty → matchup falls back to overall blend
        return _Result([])


def _build(conn, **over):
    kw = dict(
        batter_id=1, bats="L", opposing_pitcher_id=2, pitcher_throws="R",
        lineup_position=3, is_home=True, park=PARK, as_of_date=AS_OF, season=2025,
    )
    kw.update(over)
    return build_feature_row(conn, **kw)


def test_returns_none_without_batter_snapshot():
    assert _build(_FakeConn(None, _PITCHER_ROW)) is None


def test_row_has_exactly_the_feature_columns_and_no_labels():
    row = _build(_FakeConn(_BATTER_ROW, _PITCHER_ROW))
    assert set(row.keys()) == set(FEATURE_COLUMNS)
    for leak in ("h1", "h2", "hr", "k", "hits", "total_bases", "game_date"):
        assert leak not in row


def test_features_read_with_as_of_upper_bound():
    conn = _FakeConn(_BATTER_ROW, _PITCHER_ROW)
    _build(conn)
    for sql, params in conn.calls:
        if "FROM batter_skill_snapshots" in sql or "FROM pitcher_skill_snapshots" in sql:
            assert "as_of_date <= %s" in sql           # never reads after the game date
            assert AS_OF in params                      # bound is the game's as-of date


def test_context_encoding():
    row = _build(_FakeConn(_BATTER_ROW, _PITCHER_ROW))  # LHB vs RHP, slot 3, home
    assert row["is_home"] == 1
    assert row["platoon_same"] == 0          # L vs R = opposite hands (platoon advantage)
    assert row["expected_pa"] == 4.40        # PA_BY_ORDER[3]
    assert row["park_hr"] == 1.10            # LHB → hr_lhb factor
    assert row["b_xwoba"] == 0.360 and row["p_xwoba_against"] == 0.305


def test_missing_pitcher_snapshot_yields_none_features():
    row = _build(_FakeConn(_BATTER_ROW, None))
    assert row is not None and row["p_xwoba_against"] is None  # NaN downstream


def test_effective_bat_side_switch():
    assert effective_bat_side("S", "R") == "L"
    assert effective_bat_side("S", "L") == "R"
    assert effective_bat_side("L", "R") == "L"
