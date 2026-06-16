"""tennis-games-eval: validation gate for the total-games (over/under) market.

Walk-forward, leak-free: for each completed match build the point-in-time win prob,
its closed-form expected games, then evaluate the calibrated games model (de-biased
mean + empirical residual distribution). Reports mean-games MAE/bias and — the
betting question — whether the predictive distribution is calibrated (PIT
uniformity), so we only wire odds/EV if P(over line) is trustworthy.

With --raw, evaluates the uncorrected closed-form mean (no model) for comparison."""
from __future__ import annotations

import argparse
import re
from datetime import date

from ingester.db import eastern_today, get_connection
from ingester.tennis.elo import EloEngine
from ingester.tennis.games_calibration import GamesCalibrator
from ingester.tennis.match_model import project_from_winprob
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


def cmd_tennis_games_eval(args: argparse.Namespace) -> None:
    start = args.start or date(2024, 1, 1)
    end = args.end or eastern_today()
    min_matches = args.min_matches
    model = None if args.raw else GamesCalibrator.load()
    if model is None and not args.raw:
        print("[tennis-games-eval] no model — run tennis-fit-games-calibration first (or use --raw)")
        return

    conn = get_connection()
    try:
        matches = load_matches(conn)
    finally:
        conn.close()

    engine = EloEngine()
    n = 0
    abs_err = bias = 0.0
    pit_bins = [0] * 10
    cover50 = cover80 = 0

    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        n_a = engine.n_overall.get(a, 0)
        n_b = engine.n_overall.get(b, 0)
        in_window = start <= m["date"] <= end and n_a >= min_matches and n_b >= min_matches

        if in_window and m["status"] == "completed":
            actual = _total_games(m.get("score"))
            if actual is not None:
                best_of = m["best_of"] or 3
                exp = project_from_winprob(engine.win_prob(a, b, surface), best_of, surface)["exp_total_games"]
                mean_pred = model.mean(exp) if model else exp
                pit = model.pit(exp, best_of, actual) if model else None

                n += 1
                abs_err += abs(mean_pred - actual)
                bias += mean_pred - actual
                if pit is not None:
                    pit_bins[min(int(pit * 10), 9)] += 1
                    if 0.25 <= pit < 0.75:
                        cover50 += 1
                    if 0.10 <= pit < 0.90:
                        cover80 += 1

        engine.update(m["winner_id"], m["loser_id"], surface)

    if n == 0:
        print("[tennis-games-eval] no matches in window")
        return

    print(f"[tennis-games-eval] {start}..{end}  N={n}")
    print(f"  mean-games MAE  {abs_err/n:.2f}   bias {bias/n:+.2f} (pred − actual)")
    if not args.raw:
        print(f"  PIT coverage    central50={cover50/n:.3f} (ideal .500)  "
              f"central80={cover80/n:.3f} (ideal .800)")
        print("  PIT histogram (ideal flat ~0.10 each):")
        print("   " + " ".join(f"{c/n:.3f}" for c in pit_bins))
