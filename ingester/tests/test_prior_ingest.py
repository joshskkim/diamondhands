"""Unit tests for ingest_prior_frame (fake conn) and the blend-weight fit."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from ingester.commands.ingest_steamer import ingest_prior_frame
from ingester.commands.tune_prior_blend import _fit_metric


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeCursor:
    def __init__(self, sink):
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, row):
        self._sink.append(row)


class _FakeConn:
    """Mimics the psycopg surface ingest_prior_frame touches: two SELECTs + cursor."""

    def __init__(self, players):  # players: list[(id, full_name)]
        self._players = players
        self.upserted: list[dict] = []

    def execute(self, sql, *args):
        if "full_name" in sql:
            return _FakeResult([(pid, name) for pid, name in self._players])
        return _FakeResult([(pid,) for pid, _ in self._players])

    def cursor(self):
        return _FakeCursor(self.upserted)


class TestIngestPriorFrame(unittest.TestCase):
    PLAYERS = [(592450, "Aaron Judge"), (605141, "Mookie Betts")]

    def test_matches_xmlbamid_and_maps_columns(self):
        df = pd.DataFrame([
            {"PlayerName": "A. Judge", "xMLBAMID": 592450,
             "wOBA": 0.41, "ISO": 0.30, "K%": 0.25, "PA": 633},
        ])
        conn = _FakeConn(self.PLAYERS)
        written, unmatched = ingest_prior_frame(conn, df, 2026, "steamer")
        self.assertEqual((written, unmatched), (1, 0))
        row = conn.upserted[0]
        self.assertEqual(row["player_id"], 592450)
        self.assertEqual(row["method"], "steamer")
        self.assertAlmostEqual(row["proj_xwoba"], 0.41)
        self.assertAlmostEqual(row["proj_iso"], 0.30)
        self.assertAlmostEqual(row["proj_k_rate"], 0.25)

    def test_name_match_and_iso_from_slg_minus_avg(self):
        df = pd.DataFrame([
            {"Name": "Mookie Betts", "wOBA": 0.36, "SLG": 0.500, "AVG": 0.290,
             "K%": 0.15, "PA": 600},
        ])
        conn = _FakeConn(self.PLAYERS)
        written, unmatched = ingest_prior_frame(conn, df, 2026, "atc")
        self.assertEqual((written, unmatched), (1, 0))
        self.assertAlmostEqual(conn.upserted[0]["proj_iso"], 0.210)

    def test_unmatched_player_is_skipped(self):
        df = pd.DataFrame([
            {"Name": "Nobody Here", "wOBA": 0.30, "ISO": 0.10, "K%": 0.30, "PA": 400},
        ])
        conn = _FakeConn(self.PLAYERS)
        written, unmatched = ingest_prior_frame(conn, df, 2026, "rzips")
        self.assertEqual((written, unmatched), (0, 1))


class TestFitMetric(unittest.TestCase):
    def test_recovers_convex_weights_and_constraints(self):
        rng = np.random.default_rng(0)
        A = rng.uniform(0.1, 0.4, size=(400, 3))
        true_w = np.array([0.2, 0.5, 0.3])
        b = A @ true_w  # exact convex combination, no noise
        w = _fit_metric(A, b)
        self.assertTrue(np.all(w >= -1e-9))
        self.assertAlmostEqual(float(w.sum()), 1.0, places=5)
        np.testing.assert_allclose(w, true_w, atol=1e-3)


if __name__ == "__main__":
    unittest.main()
