"""tennis-fit-games-calibration: learn the affine total-games correction (actual ≈
a + b*predicted) from walk-forward predictions and save it. Fits on an EARLIER
window (default 2018–2023) so the recent window it's applied to is out-of-sample."""
from __future__ import annotations

import argparse
import re
from datetime import date

from ingester.db import get_connection
from ingester.tennis.elo import EloEngine
from ingester.tennis.games_calibration import fit_linear, save
from ingester.tennis.match_model import project_from_winprob
from ingester.tennis.match_sim import games_stats
from ingester.tennis.ratings import ELO_STATUSES, load_matches

_SET_RE = re.compile(r"(\d+)-(\d+)")


def _total_games(score: str | None) -> int | None:
    if not score:
        return None
    total, found = 0, False
    for chunk in score.split():
        m = _SET_RE.match(chunk)
        if m:
            total += int(m.group(1)) + int(m.group(2))
            found = True
    return total if found else None


def cmd_tennis_fit_games_calibration(args: argparse.Namespace) -> None:
    start = args.start or date(2018, 1, 1)
    end = args.end or date(2023, 12, 31)

    conn = get_connection()
    try:
        matches = load_matches(conn)
    finally:
        conn.close()

    engine = EloEngine()
    preds: list[float] = []
    actuals: list[int] = []
    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        n_a = engine.n_overall.get(a, 0)
        n_b = engine.n_overall.get(b, 0)
        if (start <= m["date"] <= end and n_a >= 10 and n_b >= 10
                and m["status"] == "completed"):
            actual = _total_games(m.get("score"))
            if actual is not None:
                best_of = m["best_of"] or 3
                proj = project_from_winprob(engine.win_prob(a, b, surface), best_of, surface)
                preds.append(games_stats(proj["p_serve_a"], proj["p_serve_b"], best_of)["mean"])
                actuals.append(actual)
        engine.update(m["winner_id"], m["loser_id"], surface)

    if len(preds) < 500:
        print(f"[tennis-fit-games-calibration] only {len(preds)} matches — too few")
        return

    a, b = fit_linear(preds, actuals)
    path = save(a, b)
    bias_before = sum(p - y for p, y in zip(preds, actuals)) / len(preds)
    bias_after = sum((a + b * p) - y for p, y in zip(preds, actuals)) / len(preds)
    print(f"[tennis-fit-games-calibration] fit on {start}..{end} (N={len(preds)}); "
          f"a={a:.3f} b={b:.3f}; bias {bias_before:+.2f} -> {bias_after:+.2f}; saved {path}")
