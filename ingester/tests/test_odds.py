"""Tests for odds math + provider parsing (pure, no DB required)."""
from __future__ import annotations

import math

from ingester import odds_api
from ingester.commands.odds import _game_roster, _norm_name, odds_input_hash


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Minimal psycopg-like stand-in: records execute() calls, returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list[tuple] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return _FakeCursor(self._rows)


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


class TestGameRoster:
    """The prop name→id map now resolves off the two teams' rosters (one game-keyed
    query), so props store before a game is projected — see _game_roster."""

    def test_builds_normalized_name_map(self):
        conn = _FakeConn([(660271, "Mike Trout"), (605483, "Ronald Acuña Jr.")])
        roster = _game_roster(conn, 12345)
        assert roster == {"mike trout": 660271, "ronald acuna jr": 605483}

    def test_single_query_keyed_only_by_game_id(self):
        # The behavioral change: one parameter (game_id), not the old projection-dependent
        # three-game_id UNION — team rosters + probables are resolved in SQL.
        conn = _FakeConn([(1, "A B")])
        _game_roster(conn, 999)
        assert len(conn.calls) == 1
        assert conn.calls[0][1] == (999,)


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

    def test_line_based_batter_and_pitcher_markets(self):
        # The TB / H+R+RBI and pitcher hits/ER markets carry real (non-0.5) lines.
        event = {
            "bookmakers": [
                {"key": "draftkings", "last_update": "t", "markets": [
                    {"key": "batter_total_bases", "outcomes": [
                        {"name": "Over", "description": "Mike Trout", "price": -115, "point": 1.5},
                        {"name": "Under", "description": "Mike Trout", "price": -105, "point": 1.5},
                    ]},
                    {"key": "batter_hits_runs_rbis", "outcomes": [
                        {"name": "Over", "description": "Mike Trout", "price": 105, "point": 2.5},
                    ]},
                    {"key": "pitcher_hits_allowed", "outcomes": [
                        {"name": "Over", "description": "Walbert Urena", "price": -120, "point": 4.5},
                    ]},
                    {"key": "pitcher_earned_runs", "outcomes": [
                        {"name": "Under", "description": "Walbert Urena", "price": -140, "point": 1.5},
                    ]},
                ]}
            ]
        }
        rows = odds_api.parse_prop_markets(event)
        by_market = {r["market"]: r for r in rows}
        assert set(by_market) == {"tb", "hrr", "pitcher_hits_allowed", "pitcher_earned_runs"}
        assert by_market["tb"]["line"] == 1.5
        assert by_market["hrr"]["line"] == 2.5
        assert by_market["pitcher_hits_allowed"]["side"] == "over"
        assert by_market["pitcher_earned_runs"]["side"] == "under"


class TestOddsInputHash:
    """The cache-gate hash is a pure function over a game's odds-relevant inputs."""

    def _inputs(self):
        # (home_lineup_at, away_lineup_at, temp, wind_spd, wind_dir, weather_at, home_pp, away_pp)
        return ("2026-06-03T17:00:00+00:00", "2026-06-03T17:05:00+00:00",
                72, 8, 180, "2026-06-03T16:30:00+00:00", 660271, 605483)

    def test_deterministic(self):
        assert odds_input_hash(self._inputs()) == odds_input_hash(self._inputs())

    def test_is_64_hex_chars(self):
        h = odds_input_hash(self._inputs())
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_weather_change_flips_hash(self):
        base = self._inputs()
        mutated = (base[0], base[1], base[2] + 5, *base[3:])  # temperature_f changed
        assert odds_input_hash(base) != odds_input_hash(mutated)

    def test_lineup_timestamp_change_flips_hash(self):
        base = self._inputs()
        mutated = ("2026-06-03T18:00:00+00:00", *base[1:])  # home lineup confirmed later
        assert odds_input_hash(base) != odds_input_hash(mutated)

    def test_probable_pitcher_change_flips_hash(self):
        base = self._inputs()
        mutated = (*base[:6], 999999, base[7])  # home probable pitcher swapped
        assert odds_input_hash(base) != odds_input_hash(mutated)

    def test_none_values_are_stable_and_distinct_from_empty(self):
        all_none = (None,) * 8
        # All-None hashes deterministically and does not collide with a populated game.
        assert odds_input_hash(all_none) == odds_input_hash((None,) * 8)
        assert odds_input_hash(all_none) != odds_input_hash(self._inputs())

    def test_field_order_matters(self):
        # Same multiset of values in a different position must not collide.
        a = (None, None, 1, 2, None, None, None, None)
        b = (None, None, 2, 1, None, None, None, None)
        assert odds_input_hash(a) != odds_input_hash(b)
