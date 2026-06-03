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
