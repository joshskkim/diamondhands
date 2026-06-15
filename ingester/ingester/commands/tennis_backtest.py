"""tennis-backtest: walk-forward evaluation of the tennis model.

Replays every match in causal order through a fresh EloEngine. For each match in
the evaluation window (and where both players have enough prior history) it records
a prediction BEFORE applying the result, so there is no look-ahead. Reports Brier,
log-loss, accuracy and a calibration table for the match-winner, plus total-games
MAE, comparing three models:

  * ranking   — rank_b / (rank_a + rank_b)         (parameter-free reference)
  * elo       — bare overall Elo                    (no surface, no serve/return)
  * blend     — surface-blended Elo                 (the model)

Exit gate: `blend` should beat `elo` and `ranking` on Brier / log-loss.
"""
from __future__ import annotations

import argparse
import math
import re
from datetime import date

from ingester.db import eastern_today, get_connection
from ingester.tennis.elo import EloEngine, pred_prob
from ingester.tennis.match_model import project_from_winprob
from ingester.tennis.ratings import ELO_STATUSES, load_matches

_SET_RE = re.compile(r"(\d+)-(\d+)")


def _total_games(score: str | None) -> int | None:
    """Sum games across sets from a score like '6-4 7-6(3)'. None if unparseable."""
    if not score:
        return None
    total = 0
    found = False
    for chunk in score.split():
        m = _SET_RE.match(chunk)
        if m:
            total += int(m.group(1)) + int(m.group(2))
            found = True
    return total if found else None


class _Scorer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.n = 0
        self.brier = 0.0
        self.logloss = 0.0
        self.correct = 0
        self.bins = [[0.0, 0.0, 0] for _ in range(10)]  # sum_pred, sum_actual, count

    def add(self, p: float, y: int) -> None:
        p = min(max(p, 1e-6), 1 - 1e-6)
        self.n += 1
        self.brier += (p - y) ** 2
        self.logloss += -(y * math.log(p) + (1 - y) * math.log(1 - p))
        self.correct += int((p >= 0.5) == bool(y))
        b = self.bins[min(int(p * 10), 9)]
        b[0] += p
        b[1] += y
        b[2] += 1

    def report(self) -> str:
        if self.n == 0:
            return f"  {self.name:<10} (no samples)"
        return (f"  {self.name:<10} N={self.n:<6} Brier={self.brier/self.n:.4f} "
                f"logloss={self.logloss/self.n:.4f} acc={self.correct/self.n:.3f}")

    def calibration(self) -> str:
        lines = [f"  calibration — {self.name}", "    pred   actual    n"]
        for b in self.bins:
            if b[2]:
                lines.append(f"    {b[0]/b[2]:.3f}  {b[1]/b[2]:.3f}  {b[2]:>5}")
        return "\n".join(lines)


def cmd_tennis_backtest(args: argparse.Namespace) -> None:
    start = args.start or date(2024, 1, 1)
    end = args.end or eastern_today()
    min_matches = args.min_matches

    conn = get_connection()
    try:
        matches = load_matches(conn)
    finally:
        conn.close()

    engine = EloEngine()
    s_rank, s_elo, s_blend = _Scorer("ranking"), _Scorer("elo"), _Scorer("blend")
    games_n = 0
    games_abs_err = 0.0

    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        n_a = engine.n_overall.get(a, 0)
        n_b = engine.n_overall.get(b, 0)
        in_window = start <= m["date"] <= end and n_a >= min_matches and n_b >= min_matches

        if in_window:
            y = 1 if m["winner_id"] == a else 0
            p_blend = engine.win_prob(a, b, surface)
            p_elo = pred_prob(engine.overall.get(a, 1500.0), engine.overall.get(b, 1500.0))
            s_blend.add(p_blend, y)
            s_elo.add(p_elo, y)
            ra, rb = m["player_a_rank"], m["player_b_rank"]
            if ra and rb:
                s_rank.add(rb / (ra + rb), y)
            # total games (completed matches only — retirements are partial)
            if m["status"] == "completed":
                actual = _total_games(m.get("score"))
                if actual is not None:
                    proj = project_from_winprob(p_blend, m["best_of"] or 3, surface)
                    games_abs_err += abs(proj["exp_total_games"] - actual)
                    games_n += 1

        engine.update(m["winner_id"], m["loser_id"], surface)

    print(f"[tennis-backtest] window {start}..{end}  min_prior_matches={min_matches}\n")
    for s in (s_rank, s_elo, s_blend):
        print(s.report())
    if games_n:
        print(f"\n  total-games MAE (blend): {games_abs_err/games_n:.2f}  (N={games_n})")
    print()
    print(s_blend.calibration())
