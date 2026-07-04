"""Unit tests for the Lever 5 hits-allowed de-luck toward xBA."""
from __future__ import annotations

import unittest
from unittest import mock

import pandas as pd

from ingester.commands import refresh_skills as RS
from ingester.commands.refresh_skills import _deluck_hits
from ingester.statcast import agg_pitcher_vs_handedness


class TestDeluckHits(unittest.TestCase):
    def test_off_when_weight_zero(self) -> None:
        # Weight 0 → raw hits unchanged even with xBA present. (Default is now 0.5 ON.)
        with mock.patch.object(RS, "PITCHER_HIT_DELUCK_W", 0.0):
            self.assertEqual(_deluck_hits(0.230, 0.200), 0.230)

    def test_default_is_on(self) -> None:
        # Lever 5 ships ON (0.5): raw hits blend halfway toward xBA.
        self.assertAlmostEqual(_deluck_hits(0.240, 0.200), 0.220, places=6)

    def test_blends_toward_xba_when_on(self) -> None:
        with mock.patch.object(RS, "PITCHER_HIT_DELUCK_W", 0.5):
            self.assertAlmostEqual(_deluck_hits(0.240, 0.200), 0.220, places=6)
        with mock.patch.object(RS, "PITCHER_HIT_DELUCK_W", 1.0):
            self.assertAlmostEqual(_deluck_hits(0.240, 0.200), 0.200, places=6)

    def test_noop_without_xba_or_raw(self) -> None:
        with mock.patch.object(RS, "PITCHER_HIT_DELUCK_W", 0.5):
            self.assertEqual(_deluck_hits(0.240, None), 0.240)  # no xBA
            self.assertIsNone(_deluck_hits(None, 0.200))        # no raw


class TestXbaAgainstAggregation(unittest.TestCase):
    def test_xba_against_summed_per_pa(self) -> None:
        # 3 PAs vs RHB: a single (xBA .9), a strikeout (no xBA), a flyout (xBA .1).
        df = pd.DataFrame([
            {"pitcher": 10, "stand": "R", "events": "single",
             "estimated_woba_using_speedangle": 0.9, "estimated_ba_using_speedangle": 0.9,
             "woba_value": 0.9, "woba_denom": 1},
            {"pitcher": 10, "stand": "R", "events": "strikeout",
             "estimated_woba_using_speedangle": None, "estimated_ba_using_speedangle": None,
             "woba_value": 0.0, "woba_denom": 1},
            {"pitcher": 10, "stand": "R", "events": "field_out",
             "estimated_woba_using_speedangle": 0.10, "estimated_ba_using_speedangle": 0.10,
             "woba_value": 0.0, "woba_denom": 1},
        ])
        rows = agg_pitcher_vs_handedness([df])
        r = next(x for x in rows if x["player_id"] == 10 and x["vs_handedness"] == "R")
        # expected hits = .9 + 0 + .1 = 1.0 over 3 PA → xBA-against = 0.3333
        self.assertAlmostEqual(r["xba_against"], round(1.0 / 3, 4), places=4)
        self.assertAlmostEqual(r["hits_per_pa"], round(1.0 / 3, 4), places=4)  # 1 actual hit


if __name__ == "__main__":
    unittest.main()
