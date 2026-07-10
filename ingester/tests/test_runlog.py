"""Run-log deltas and its never-break-the-pipeline contract.

The row counts in pipeline_run_steps are differences of two pg_stat_user_tables reads, so
the arithmetic (clamping, unseen tables) is where the bugs live. The other half of these
tests pins the contract that matters operationally: instrumentation failures must degrade
to "no log" rather than take the daily pipeline down with them.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import date
from unittest import mock

from ingester import runlog
from ingester.runlog import RunLog, _diff


class _FakeConn:
    """Routes on SQL substrings; records every write it's handed."""

    def __init__(self, snapshots: list[list[tuple]] | None = None) -> None:
        self.snapshots = snapshots or []
        self.writes: list[tuple[str, tuple]] = []
        self.closed = False
        self.autocommit = False

    def execute(self, sql: str, params: tuple = ()):  # noqa: ANN201
        if "pg_stat_user_tables" in sql:
            return mock.Mock(fetchall=lambda: self.snapshots.pop(0))
        if "INSERT INTO pipeline_runs" in sql:
            self.writes.append((sql, params))
            return mock.Mock(fetchone=lambda: (7,))
        if "pipeline_run_steps" in sql or "UPDATE pipeline_runs" in sql:
            self.writes.append((sql, params))
        return mock.Mock()

    def close(self) -> None:
        self.closed = True


def _begin(conn: _FakeConn) -> RunLog | None:
    with mock.patch.dict(os.environ, {"DIAMOND_RUNLOG_ENABLED": "1"}), \
         mock.patch.object(runlog, "get_connection", return_value=conn):
        return RunLog.begin("full", date(2026, 7, 9))


def _step_rows(conn: _FakeConn) -> list[tuple]:
    return [p for sql, p in conn.writes if "pipeline_run_steps" in sql]


class TestDiff(unittest.TestCase):
    def test_counts_writes_per_table(self):
        before = {"model_picks": (100, 5, 50)}
        after = {"model_picks": (912, 5, 912)}
        ins, upd, dele, tables = _diff(before, after)
        self.assertEqual((ins, upd, dele), (812, 0, 862))
        self.assertEqual(tables, {"model_picks": {"ins": 812, "upd": 0, "del": 862}})

    def test_untouched_tables_are_dropped(self):
        ins, upd, dele, tables = _diff({"games": (10, 0, 0)}, {"games": (10, 0, 0)})
        self.assertEqual((ins, upd, dele), (0, 0, 0))
        self.assertEqual(tables, {}, "a table nobody wrote to must not bloat tables_json")

    def test_stat_reset_mid_step_clamps_to_zero(self):
        # pg_stat_reset() between snapshots runs the counters backwards.
        ins, upd, dele, tables = _diff({"games": (100, 20, 50)}, {"games": (0, 0, 0)})
        self.assertEqual((ins, upd, dele), (0, 0, 0))
        self.assertEqual(tables, {})

    def test_table_unseen_in_before_counts_from_zero(self):
        ins, _, _, tables = _diff({}, {"batter_xhr": (40, 0, 0)})
        self.assertEqual(ins, 40)
        self.assertEqual(tables["batter_xhr"]["ins"], 40)

    def test_failed_snapshot_yields_no_volume(self):
        self.assertEqual(_diff(None, {"games": (1, 0, 0)}), (0, 0, 0, {}))


class TestRunLog(unittest.TestCase):
    def test_records_step_and_accumulates_run_totals(self):
        conn = _FakeConn()
        log = _begin(conn)
        log.record_step(1, "project", "ok", 4200,
                        {"model_picks": (100, 0, 0)}, {"model_picks": (912, 0, 0)})
        log.record_step(2, "refresh-odds", "warn", 900,
                        {"odds": (0, 0, 0)}, {"odds": (0, 30, 0)})
        log.finish("warn", 2, 1, 5100)

        (idx, name, status, ms, ins, upd, dele, tables) = _step_rows(conn)[0][1:]
        self.assertEqual((idx, name, status, ms), (1, "project", "ok", 4200))
        self.assertEqual((ins, upd, dele), (812, 0, 0))
        self.assertEqual(json.loads(tables), {"model_picks": {"ins": 812, "upd": 0, "del": 0}})

        update = next(p for sql, p in conn.writes if "UPDATE pipeline_runs" in sql)
        status, step_count, warning_count, ins, upd, dele, ms, run_id = update
        self.assertEqual((status, step_count, warning_count), ("warn", 2, 1))
        self.assertEqual((ins, upd, dele), (812, 30, 0), "run totals sum the step deltas")
        self.assertEqual((ms, run_id), (5100, 7))
        self.assertTrue(conn.closed, "finish must not leak the connection")

    def test_step_with_no_writes_stores_null_tables_json(self):
        conn = _FakeConn()
        log = _begin(conn)
        log.record_step(1, "daily briefing (Discord)", "ok", 120, {"games": (5, 0, 0)}, {"games": (5, 0, 0)})
        self.assertIsNone(_step_rows(conn)[0][-1])

    def test_kill_switch_touches_no_database(self):
        conn = _FakeConn()
        with mock.patch.dict(os.environ, {"DIAMOND_RUNLOG_ENABLED": "0"}), \
             mock.patch.object(runlog, "get_connection", return_value=conn) as get_conn:
            self.assertIsNone(RunLog.begin("full", date(2026, 7, 9)))
        get_conn.assert_not_called()
        self.assertEqual(conn.writes, [])

    def test_unreachable_database_disables_log_without_raising(self):
        # The contract cmd_daily relies on: a broken run-log never fails the pipeline.
        with mock.patch.dict(os.environ, {"DIAMOND_RUNLOG_ENABLED": "1"}), \
             mock.patch.object(runlog, "get_connection", side_effect=RuntimeError("DATABASE_URL not set in .env")):
            self.assertIsNone(RunLog.begin("full", date(2026, 7, 9)))

    def test_step_write_failure_is_swallowed(self):
        conn = _FakeConn()
        log = _begin(conn)
        with mock.patch.object(conn, "execute", side_effect=RuntimeError("connection lost")):
            log.record_step(1, "project", "ok", 10, {}, {})  # must not raise


if __name__ == "__main__":
    unittest.main()
