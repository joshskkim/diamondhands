"""Unit tests for the projection engine's season clear-rate helper.

Result-shaping + the leak-free query parameters are covered here (no DB, per convention).
The SQL semantics themselves — the strict `game_date < as_of` window, `plate_appearances > 0`
— are validated end-to-end against the Java ClearRateRepository, which is the source of record.
"""
from __future__ import annotations

import unittest
from datetime import date

from ingester.projection.clear_rates import season_hit_rates


class _FakeConn:
    """Captures the executed (sql, params) and returns canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

        class _Cur:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return _Cur(self._rows)


class TestSeasonHitRates(unittest.TestCase):
    def test_shapes_rows_into_rate_and_count(self):
        conn = _FakeConn([(101, 0.62, 60), (202, 0.4, 25)])
        out = season_hit_rates(conn, [101, 202], date(2026, 7, 12))
        self.assertEqual(out, {101: (0.62, 60), 202: (0.4, 25)})

    def test_null_rate_preserved(self):
        # A grouped row could carry a NULL avg only if COUNT is 0, which GROUP BY won't emit;
        # still, guard the mapping so a NULL never crashes the blend.
        conn = _FakeConn([(303, None, 0)])
        self.assertEqual(season_hit_rates(conn, [303], date(2026, 7, 12)), {303: (None, 0)})

    def test_missing_player_absent_from_map(self):
        # Player 999 has no qualifying game → not returned → caller reads (None, 0).
        conn = _FakeConn([(101, 0.5, 10)])
        out = season_hit_rates(conn, [101, 999], date(2026, 7, 12))
        self.assertNotIn(999, out)

    def test_empty_ids_skips_query(self):
        conn = _FakeConn([(1, 1.0, 1)])
        self.assertEqual(season_hit_rates(conn, [], date(2026, 7, 12)), {})
        self.assertIsNone(conn.sql)  # never touched the DB

    def test_leak_free_params(self):
        as_of = date(2026, 7, 12)
        conn = _FakeConn([])
        season_hit_rates(conn, [101], as_of)
        ids, season_start, upper = conn.params
        self.assertEqual(ids, [101])
        self.assertEqual(season_start, date(2026, 1, 1))  # Jan 1 of the slate year
        self.assertEqual(upper, as_of)                    # strict upper bound = the slate
        self.assertIn("game_date <  %s", conn.sql)         # strictly before → no same-day leak
        self.assertIn("plate_appearances > 0", conn.sql)


if __name__ == "__main__":
    unittest.main()
