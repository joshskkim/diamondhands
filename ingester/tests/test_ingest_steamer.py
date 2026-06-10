"""Unit tests for the Steamer-CSV parsing helpers (no DB)."""
from __future__ import annotations

import unittest

from ingester.commands.ingest_steamer import _find_col, _norm_name, _to_rate


class TestSteamerHelpers(unittest.TestCase):
    def test_to_rate_handles_fraction_and_percent(self):
        self.assertAlmostEqual(_to_rate(0.225), 0.225)
        self.assertAlmostEqual(_to_rate("22.5%"), 0.225)
        self.assertAlmostEqual(_to_rate("22.5"), 0.225)   # bare percent number
        self.assertAlmostEqual(_to_rate(" 18 %"), 0.18)
        self.assertIsNone(_to_rate(None))
        self.assertIsNone(_to_rate(""))

    def test_find_col_is_case_insensitive(self):
        cols = {c.lower(): c for c in ["Name", "wOBA", "PA", "MLBAMID"]}
        self.assertEqual(_find_col(cols, "woba"), "wOBA")
        self.assertEqual(_find_col(cols, "mlbamid", "mlbam"), "MLBAMID")
        self.assertEqual(_find_col(cols, "playername", "name"), "Name")
        self.assertIsNone(_find_col(cols, "iso"))

    def test_norm_name_strips_accents_and_punctuation(self):
        self.assertEqual(_norm_name("José Ramírez"), "jose ramirez")
        self.assertEqual(_norm_name("Kyle Schwarber"), "kyle schwarber")
        self.assertEqual(_norm_name("J.D. Martinez"), "jd martinez")


if __name__ == "__main__":
    unittest.main()
