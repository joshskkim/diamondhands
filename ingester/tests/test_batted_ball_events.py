"""Unit tests for the per-batted-ball xHR corpus extraction (pure, no DB)."""
from __future__ import annotations

import math

import pandas as pd

from ingester.statcast import batted_ball_events


def _row(batter, events="field_out", ev=95.0, la=25.0, hc_x=125.42, hc_y=100.0,
         bb_type="fly_ball", home_team="NYY", game_pk=1, ew=0.30, dist=350, p_throws="R"):
    return {
        "batter": batter, "events": events, "launch_speed": ev, "launch_angle": la,
        "hc_x": hc_x, "hc_y": hc_y, "bb_type": bb_type, "home_team": home_team,
        "game_pk": game_pk, "estimated_woba_using_speedangle": ew, "hit_distance_sc": dist,
        "p_throws": p_throws,
    }


def _by(rows):  # helper: index rows for assertions
    return rows


class TestBattedBallEvents:
    def test_empty(self):
        assert batted_ball_events([], 2025) == []
        assert batted_ball_events([pd.DataFrame()], 2025) == []

    def test_basic_fields_and_season(self):
        df = pd.DataFrame([_row(1, events="single", ev=88.5, la=12.0)])
        rows = batted_ball_events([df], 2025)
        assert len(rows) == 1
        r = rows[0]
        assert r["season"] == 2025
        assert r["player_id"] == 1
        assert r["launch_speed"] == 88.5
        assert r["launch_angle"] == 12.0
        assert r["park"] == "NYY"
        assert r["is_hr"] is False
        assert r["estimated_woba"] == 0.30
        assert r["hit_distance"] == 350

    def test_home_run_flagged_and_kept_without_coordinates(self):
        # HRs often have no hc_x/hc_y — they MUST still be included (positive class).
        df = pd.DataFrame([_row(7, events="home_run", ev=108.0, la=28.0,
                                hc_x=None, hc_y=None, dist=430)])
        rows = batted_ball_events([df], 2025)
        assert len(rows) == 1
        r = rows[0]
        assert r["is_hr"] is True
        assert r["spray_deg"] is None          # no coordinate → null, but row kept
        assert r["launch_speed"] == 108.0
        assert r["hit_distance"] == 430

    def test_drops_pitches_without_measured_contact(self):
        # A called strike / no-contact pitch has no launch_speed → not a batted ball.
        df = pd.DataFrame([
            _row(1, ev=90.0, la=10.0),                       # kept
            _row(1, ev=None, la=None),                       # dropped
        ])
        rows = batted_ball_events([df], 2025)
        assert len(rows) == 1

    def test_drops_fouls_but_keeps_hr_without_bb_type(self):
        # Fouls are tracked (have EV/LA) but bb_type is null and they're not in play →
        # must be excluded. A HR with null bb_type must still be kept (positive class).
        df = pd.DataFrame([
            _row(1, events="foul", ev=95.0, la=40.0, bb_type=None),        # dropped
            _row(2, events="field_out", ev=95.0, la=25.0, bb_type="fly_ball"),  # kept
            _row(3, events="home_run", ev=108.0, la=28.0, bb_type=None),   # kept
        ])
        rows = batted_ball_events([df], 2025)
        ids = sorted(r["player_id"] for r in rows)
        assert ids == [2, 3]
        assert {r["player_id"]: r["is_hr"] for r in rows}[3] is True

    def test_spray_sign_left_vs_right(self):
        # hc_x < home (125.42) → left side (negative); > → right side (positive).
        df = pd.DataFrame([
            _row(1, hc_x=70.0, hc_y=100.0),    # left
            _row(2, hc_x=180.0, hc_y=100.0),   # right
        ])
        rows = batted_ball_events([df], 2025)
        by_id = {r["player_id"]: r for r in rows}
        assert by_id[1]["spray_deg"] < 0
        assert by_id[2]["spray_deg"] > 0

    def test_null_estimated_woba_becomes_none(self):
        df = pd.DataFrame([_row(1, ew=None, dist=None)])
        r = batted_ball_events([df], 2025)[0]
        assert r["estimated_woba"] is None
        assert r["hit_distance"] is None
        # no NaN leaks into the DB-ready dict
        assert not any(isinstance(v, float) and math.isnan(v) for v in r.values())

    def test_multiple_chunks_accumulate(self):
        df1 = pd.DataFrame([_row(1), _row(2)])
        df2 = pd.DataFrame([_row(3, events="home_run")])
        rows = batted_ball_events([df1, df2], 2025)
        assert len(rows) == 3
        assert sum(1 for r in rows if r["is_hr"]) == 1

    def test_p_throws_captured_and_filtered_to_lr(self):
        # p_throws (opposing pitcher hand) feeds the hand-split xHR; only L/R kept.
        df = pd.DataFrame([
            _row(1, p_throws="L"),
            _row(2, p_throws="R"),
            _row(3, p_throws=None),   # missing hand → null, row still kept
        ])
        rows = batted_ball_events([df], 2025)
        by_id = {r["player_id"]: r for r in rows}
        assert by_id[1]["p_throws"] == "L"
        assert by_id[2]["p_throws"] == "R"
        assert by_id[3]["p_throws"] is None

    def test_p_throws_column_absent_is_null(self):
        # A chunk missing the column entirely must not crash → p_throws null.
        row = _row(1)
        del row["p_throws"]
        rows = batted_ball_events([pd.DataFrame([row])], 2025)
        assert rows[0]["p_throws"] is None
