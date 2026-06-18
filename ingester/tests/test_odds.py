"""Tests for odds math + provider parsing (pure, no DB required)."""
from __future__ import annotations

import math

from ingester import odds_api
from ingester.commands.odds import _norm_name


class TestOddsMath:
    def test_american_to_decimal_underdog(self):
        assert odds_api.american_to_decimal(100) == 2.0
        assert math.isclose(odds_api.american_to_decimal(150), 2.5)

    def test_american_to_decimal_favorite(self):
        assert math.isclose(odds_api.american_to_decimal(-200), 1.5)
        assert math.isclose(odds_api.american_to_decimal(-110), 1.0 + 100 / 110)

    def test_implied_prob(self):
        assert math.isclose(odds_api.implied_prob(100), 0.5)
        assert math.isclose(odds_api.implied_prob(-200), 200 / 300)
        assert math.isclose(odds_api.implied_prob(200), 100 / 300)


class TestNameNorm:
    def test_strips_accents_and_punct(self):
        assert _norm_name("Yoán Moncada") == "yoan moncada"
        assert _norm_name("Walbert Ureña") == "walbert urena"
        assert _norm_name("Ronald Acuña Jr.") == "ronald acuna jr"
        assert _norm_name("  Mike   Trout ") == "mike trout"


class TestParseGameMarkets:
    def _event(self):
        return {
            "home_team": "Los Angeles Angels",
            "away_team": "Colorado Rockies",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "last_update": "t",
                    "markets": [
                        {"key": "h2h", "outcomes": [
                            {"name": "Los Angeles Angels", "price": -118},
                            {"name": "Colorado Rockies", "price": 100},
                        ]},
                        {"key": "spreads", "outcomes": [
                            {"name": "Los Angeles Angels", "price": 150, "point": -1.5},
                            {"name": "Colorado Rockies", "price": -175, "point": 1.5},
                        ]},
                        {"key": "totals", "outcomes": [
                            {"name": "Over", "price": -110, "point": 8.5},
                            {"name": "Under", "price": -110, "point": 8.5},
                        ]},
                    ],
                }
            ],
        }

    def test_normalizes_sides_and_lines(self):
        rows = odds_api.parse_game_markets(self._event())
        by = {(r["market"], r["side"]): r for r in rows}
        assert by[("moneyline", "home")]["line"] is None
        assert by[("run_line", "home")]["line"] == -1.5
        assert by[("run_line", "away")]["line"] == 1.5
        assert by[("total", "over")]["line"] == 8.5
        assert len(rows) == 6

    def test_parses_first_five_and_first_inning_markets(self):
        event = {
            "home_team": "New York Yankees",
            "away_team": "Boston Red Sox",
            "bookmakers": [{"key": "draftkings", "last_update": "t", "markets": [
                {"key": "totals_1st_5_innings", "outcomes": [
                    {"name": "Over", "price": -110, "point": 4.5},
                    {"name": "Under", "price": -110, "point": 4.5},
                ]},
                {"key": "h2h_1st_5_innings", "outcomes": [
                    {"name": "New York Yankees", "price": -130},
                    {"name": "Boston Red Sox", "price": 110},
                ]},
                {"key": "spreads_1st_5_innings", "outcomes": [
                    {"name": "New York Yankees", "price": 120, "point": -0.5},
                    {"name": "Boston Red Sox", "price": -140, "point": 0.5},
                ]},
                {"key": "totals_1st_1_innings", "outcomes": [
                    {"name": "Over", "price": 120, "point": 0.5},
                    {"name": "Under", "price": -150, "point": 0.5},
                ]},
            ]}],
        }
        by = {(r["market"], r["side"]): r for r in odds_api.parse_game_markets(event)}
        assert by[("total_f5", "over")]["line"] == 4.5
        assert by[("moneyline_f5", "home")]["line"] is None
        assert by[("moneyline_f5", "away")]["price_american"] == 110
        assert by[("run_line_f5", "home")]["line"] == -0.5
        assert by[("total_f1", "over")]["line"] == 0.5  # YRFI market


class TestParsePropMarkets:
    def test_player_and_side(self):
        event = {
            "bookmakers": [
                {"key": "fanduel", "last_update": "t", "markets": [
                    {"key": "batter_home_runs", "outcomes": [
                        {"name": "Over", "description": "Mike Trout", "price": 340, "point": 0.5},
                        {"name": "Under", "description": "Mike Trout", "price": -440, "point": 0.5},
                    ]},
                    {"key": "unsupported_market", "outcomes": [
                        {"name": "Over", "description": "Mike Trout", "price": 100, "point": 0.5},
                    ]},
                ]}
            ]
        }
        rows = odds_api.parse_prop_markets(event)
        assert len(rows) == 2  # unsupported market dropped
        assert {r["side"] for r in rows} == {"over", "under"}
        assert all(r["market"] == "hr" for r in rows)
        assert all(r["player_name"] == "Mike Trout" for r in rows)


class TestGamesNeedingOdds:
    """The odds-pull gate is expressed in SQL (lineup-lock); we assert it parameterizes the
    --force flag and threads the date through, exercising it against a fake connection that
    captures the query + bound params (the lock predicate itself is verified end-to-end)."""

    class _FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class _FakeConn:
        def __init__(self, rows):
            self.rows = rows
            self.calls = []

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return TestGamesNeedingOdds._FakeCursor(self.rows)

    def test_returns_game_ids_and_passes_force_false(self):
        from datetime import date
        from ingester.commands.odds import _games_needing_odds

        conn = self._FakeConn([(1,), (2,)])
        out = _games_needing_odds(conn, date(2026, 6, 18))

        assert out == {1, 2}
        sql, params = conn.calls[0]
        assert params == (date(2026, 6, 18), False)  # force defaults False
        assert "odds_pulled_at IS NULL" in sql
        assert "home_lineup_confirmed_at IS NULL" in sql
        assert "away_lineup_confirmed_at IS NULL" in sql
        assert "start_time_utc > NOW()" in sql

    def test_force_flag_is_bound(self):
        from datetime import date
        from ingester.commands.odds import _games_needing_odds

        conn = self._FakeConn([])
        _games_needing_odds(conn, date(2026, 6, 18), force=True)

        _, params = conn.calls[0]
        assert params == (date(2026, 6, 18), True)
