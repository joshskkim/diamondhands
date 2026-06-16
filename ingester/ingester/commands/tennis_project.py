"""tennis-project: write tennis_match_projections for a slate of matches using the
current ratings snapshot (surface-blended Elo -> win prob -> serve model -> totals).

In Milestone 1 there is no live slate yet, so this projects the matches on a given
date (default: the latest match date in the DB) as a demonstration / smoke of the
end-to-end model path."""
from __future__ import annotations

import argparse
import json

from ingester.db import get_connection
from ingester.tennis.constants import ELO_SURFACE_WEIGHT, MODEL_VERSION, SURFACES
from ingester.tennis.calibration import TennisCalibrator
from ingester.tennis.games_calibration import GamesCalibrator
from ingester.tennis.elo import pred_prob
from ingester.tennis.match_model import project_from_winprob


def _load_snapshot(conn) -> dict:
    """Latest rating snapshot as {(player_id, surface): elo}."""
    as_of = conn.execute("SELECT max(as_of_date) FROM tennis_player_ratings").fetchone()[0]
    if as_of is None:
        return {}
    rows = conn.execute(
        "SELECT player_id, surface, elo FROM tennis_player_ratings "
        "WHERE as_of_date = %s AND elo IS NOT NULL",
        (as_of,),
    ).fetchall()
    return {(pid, surface): float(elo) for pid, surface, elo in rows}


def _blended_elo(snap: dict, pid: str, surface: str | None) -> float | None:
    overall = snap.get((pid, "all"))
    if overall is None:
        return None
    if surface in SURFACES and (surface_elo := snap.get((pid, surface))) is not None:
        return ELO_SURFACE_WEIGHT * surface_elo + (1.0 - ELO_SURFACE_WEIGHT) * overall
    return overall


def cmd_tennis_project(args: argparse.Namespace) -> None:
    conn = get_connection()
    try:
        snap = _load_snapshot(conn)
        if not snap:
            print("[tennis-project] no ratings snapshot — run tennis-refresh-ratings first")
            return

        if getattr(args, "scheduled", False):
            label = "scheduled"
            matches = conn.execute(
                "SELECT id, surface, best_of, player_a_id, player_b_id "
                "FROM tennis_matches WHERE status = 'scheduled' ORDER BY start_time_utc NULLS LAST, id"
            ).fetchall()
        else:
            target = args.date
            if target is None:
                target = conn.execute("SELECT max(match_date) FROM tennis_matches").fetchone()[0]
            label = str(target)
            matches = conn.execute(
                "SELECT id, surface, best_of, player_a_id, player_b_id "
                "FROM tennis_matches WHERE match_date = %s ORDER BY id",
                (target,),
            ).fetchall()

        # Calibration is opt-in: the blended Elo is already well-calibrated, so the
        # isotonic map was flat out-of-sample (kept for if calibration ever drifts).
        calibrator = TennisCalibrator.load() if getattr(args, "calibrate", False) else None
        # Games calibration is ON by default: the closed-form sim over-counts games
        # ~+2, so this de-biases the displayed expected total games (validated OOS).
        games_cal = GamesCalibrator.load()

        rows = []
        skipped = 0
        for mid, surface, best_of, a_id, b_id in matches:
            elo_a = _blended_elo(snap, a_id, surface)
            elo_b = _blended_elo(snap, b_id, surface)
            if elo_a is None or elo_b is None:
                skipped += 1
                continue
            win_a = pred_prob(elo_a, elo_b)
            if calibrator is not None:
                win_a = calibrator.apply(win_a)
            proj = project_from_winprob(win_a, best_of or 3, surface)
            if games_cal is not None:
                proj["exp_total_games"] = games_cal.mean(proj["exp_total_games"])
            reasoning = {
                "surface": surface, "elo_a": round(elo_a, 1), "elo_b": round(elo_b, 1),
                "blend_weight": ELO_SURFACE_WEIGHT,
            }
            rows.append((
                mid, a_id, b_id, round(proj["p_win_a"], 4),
                round(proj["p_serve_a"], 4), round(proj["p_serve_b"], 4),
                round(proj["exp_total_games"], 2), round(proj["prob_straight_sets"], 4),
                json.dumps(reasoning), MODEL_VERSION,
            ))

        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO tennis_match_projections
                     (match_id, player_a_id, player_b_id, p_win_a, p_serve_a, p_serve_b,
                      exp_total_games, prob_straight_sets, reasoning, model_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (match_id) DO UPDATE SET
                     p_win_a = EXCLUDED.p_win_a, p_serve_a = EXCLUDED.p_serve_a,
                     p_serve_b = EXCLUDED.p_serve_b, exp_total_games = EXCLUDED.exp_total_games,
                     prob_straight_sets = EXCLUDED.prob_straight_sets,
                     reasoning = EXCLUDED.reasoning, model_version = EXCLUDED.model_version,
                     projected_at = NOW()""",
                rows,
            )
        conn.commit()
        print(f"[tennis-project] {label}: projected {len(rows)} matches "
              f"({skipped} skipped for missing ratings) [{MODEL_VERSION}]")
    finally:
        conn.close()
