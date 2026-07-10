"""Run-log for the `daily` command: per-run and per-step wall time + rows written.

Rows written are pg_stat_user_tables (n_tup_ins/upd/del) deltas snapshotted around each
step, so none of the pipeline commands had to change to report a count. See
db/migrations/V75__pipeline_runs.sql for what a "row" means here and why runs record
their mode.

Every database call in this module is best-effort: the run-log is instrumentation and
must never be able to break the pipeline it measures. A failure prints the same
"⚠ … — continuing" line the daily loop uses and the run proceeds unlogged.
"""
from __future__ import annotations

import json
import os
from datetime import date

import psycopg

from ingester.db import get_connection

# relname -> (n_tup_ins, n_tup_upd, n_tup_del)
Snapshot = dict[str, tuple[int, int, int]]


def _open() -> psycopg.Connection:
    """A connection dedicated to reading stats and writing the log.

    autocommit is required, not stylistic: since PG15 stats_fetch_consistency defaults to
    'cache', which caches pg_stat_* on first access *for the life of the transaction*. In a
    single transaction every snapshot would return identical values and every delta would be
    zero. autocommit puts each snapshot in its own transaction; setting the GUC to 'none'
    forces a re-fetch on every access as well, so no pg_stat_clear_snapshot() call is needed.

    Keeping this off the step functions' own connections means we never disturb their
    transactions.
    """
    conn = get_connection()
    conn.autocommit = True
    conn.execute("SET stats_fetch_consistency = 'none'")
    return conn


class RunLog:
    """Handle for one cmd_daily invocation. Build it with begin(); None means "don't log"."""

    def __init__(self, conn: psycopg.Connection, run_id: int) -> None:
        self._conn = conn
        self._run_id = run_id
        self._ins = 0
        self._upd = 0
        self._del = 0

    @classmethod
    def begin(cls, mode: str, slate_date: date) -> RunLog | None:
        """Open the log and insert the run header. Returns None if disabled or unreachable.

        The kill switch is read here rather than at import so tests can patch it — and they
        must: get_connection() calls load_dotenv(), so a default-on flag captured at import
        would make a local `pytest` run connect to the dev database and write real rows.
        """
        if os.environ.get("DIAMOND_RUNLOG_ENABLED", "1") == "0":
            return None
        try:
            conn = _open()
            row = conn.execute(
                "INSERT INTO pipeline_runs (mode, slate_date) VALUES (%s, %s) RETURNING id",
                (mode, slate_date),
            ).fetchone()
            return cls(conn, int(row[0]))
        except Exception as exc:  # noqa: BLE001
            print(f"[daily]   ⚠ run-log unavailable: {exc} — continuing unlogged")
            return None

    def snapshot(self) -> Snapshot | None:
        """Cumulative write counters for every public table, or None if the read failed."""
        try:
            rows = self._conn.execute(
                """
                SELECT relname, n_tup_ins, n_tup_upd, n_tup_del
                FROM pg_stat_user_tables
                WHERE schemaname = 'public'
                """
            ).fetchall()
            return {relname: (ins, upd, dele) for relname, ins, upd, dele in rows}
        except Exception as exc:  # noqa: BLE001
            print(f"[daily]   ⚠ run-log snapshot failed: {exc} — continuing")
            return None

    def record_step(
        self,
        index: int,
        name: str,
        status: str,
        duration_ms: int,
        before: Snapshot | None,
        after: Snapshot | None,
    ) -> None:
        ins, upd, dele, tables = _diff(before, after)
        self._ins += ins
        self._upd += upd
        self._del += dele
        try:
            self._conn.execute(
                """
                INSERT INTO pipeline_run_steps (
                    run_id, step_index, name, status, duration_ms,
                    rows_inserted, rows_updated, rows_deleted, tables_json, finished_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, now())
                """,
                (
                    self._run_id, index, name, status, duration_ms,
                    ins, upd, dele, json.dumps(tables) if tables else None,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[daily]   ⚠ run-log step '{name}' failed to write: {exc} — continuing")

    def finish(self, status: str, step_count: int, warning_count: int, duration_ms: int) -> None:
        try:
            self._conn.execute(
                """
                UPDATE pipeline_runs
                   SET status = %s, step_count = %s, warning_count = %s,
                       rows_inserted = %s, rows_updated = %s, rows_deleted = %s,
                       duration_ms = %s, finished_at = now()
                 WHERE id = %s
                """,
                (
                    status, step_count, warning_count,
                    self._ins, self._upd, self._del, duration_ms, self._run_id,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[daily]   ⚠ run-log finish failed: {exc} — continuing")
        finally:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass


def _diff(
    before: Snapshot | None, after: Snapshot | None
) -> tuple[int, int, int, dict[str, dict[str, int]]]:
    """Per-table write deltas, plus their totals. Tables with no writes are dropped.

    Deltas are clamped at zero: a pg_stat_reset() between the two snapshots would otherwise
    make the counters run backwards and report a negative volume. A table absent from
    `before` (created or first written during the step) counts from zero.
    """
    if before is None or after is None:
        return 0, 0, 0, {}
    total_ins = total_upd = total_del = 0
    tables: dict[str, dict[str, int]] = {}
    for relname, (a_ins, a_upd, a_del) in after.items():
        b_ins, b_upd, b_del = before.get(relname, (0, 0, 0))
        d_ins = max(0, a_ins - b_ins)
        d_upd = max(0, a_upd - b_upd)
        d_del = max(0, a_del - b_del)
        if d_ins or d_upd or d_del:
            tables[relname] = {"ins": d_ins, "upd": d_upd, "del": d_del}
            total_ins += d_ins
            total_upd += d_upd
            total_del += d_del
    return total_ins, total_upd, total_del, tables
