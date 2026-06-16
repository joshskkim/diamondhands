"""tennis-backtest: walk-forward evaluation of the tennis model.

Replays every match in causal order through a fresh EloEngine. For each match in
the evaluation window (and where both players have enough prior history) it records
a prediction BEFORE applying the result, so there is no look-ahead. Reports Brier,
log-loss, accuracy and a calibration table for the match-winner, plus total-games
MAE, comparing:

  * ranking   — rank_b / (rank_a + rank_b)         (parameter-free reference)
  * elo       — bare overall Elo                    (no surface, no serve/return)
  * blend     — surface-blended Elo                 (the model)
  * levers    — blend + refinement levers           (only with --levers)

Exit gate: `blend` beats `elo`/`ranking`; a lever ships only if `levers` beats
`blend`. `--tune-levers` grid-searches each beta for the Brier-minimizing value.
"""
from __future__ import annotations

import argparse
import math
import re
from datetime import date

from ingester.db import eastern_today, get_connection
from ingester.tennis.adjustments import (
    FatigueTracker,
    apply_levers,
    court_speed_feature,
    fatigue_feature,
    lefty_feature,
)
from ingester.tennis.calibration import TennisCalibrator
from ingester.tennis.constants import (
    TENNIS_COURT_SPEED_BETA,
    TENNIS_FATIGUE_BETA,
    TENNIS_LEFTY_BETA,
)
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
        self.bins = [[0.0, 0.0, 0] for _ in range(10)]

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


def _load_feature_lookups(conn) -> tuple[dict, dict, dict]:
    """Static per-venue / per-player lever inputs (stable traits, leak-safe)."""
    court_z = {tid: float(z) for tid, z in conn.execute(
        "SELECT id, court_speed_index FROM tennis_tournaments WHERE court_speed_index IS NOT NULL"
    ).fetchall()}
    player_spw = {pid: float(spw) for pid, spw in conn.execute(
        "SELECT player_id, avg((COALESCE(first_won,0)+COALESCE(second_won,0))::numeric"
        " / NULLIF(serve_points,0)) FROM tennis_player_match_stats WHERE serve_points > 0"
        " GROUP BY player_id"
    ).fetchall() if spw is not None}
    player_hand = {pid: hand for pid, hand in conn.execute(
        "SELECT id, hand FROM tennis_players"
    ).fetchall()}
    return court_z, player_spw, player_hand


def cmd_tennis_backtest(args: argparse.Namespace) -> None:
    start = args.start or date(2024, 1, 1)
    end = args.end or eastern_today()
    min_matches = args.min_matches
    use_levers = args.levers or args.tune_levers

    conn = get_connection()
    try:
        matches = load_matches(conn)
        court_z, player_spw, player_hand = _load_feature_lookups(conn) if use_levers else ({}, {}, {})
    finally:
        conn.close()

    calibrator = TennisCalibrator.load() if args.calibrate else None
    engine = EloEngine()
    fatigue = FatigueTracker()
    s_rank, s_elo, s_blend = _Scorer("ranking"), _Scorer("elo"), _Scorer("blend")
    s_levers = _Scorer("levers")
    s_cal = _Scorer("calibrated")
    games_n = 0
    games_abs_err = 0.0
    tune_rows: list[tuple] = []  # (p_blend, court_feat, fatigue_feat, lefty_feat, y)

    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        n_a = engine.n_overall.get(a, 0)
        n_b = engine.n_overall.get(b, 0)
        in_window = start <= m["date"] <= end and n_a >= min_matches and n_b >= min_matches

        # Recent load BEFORE this match is added (point-in-time).
        load_a = fatigue.load(a, m["date"]) if use_levers else 0.0
        load_b = fatigue.load(b, m["date"]) if use_levers else 0.0

        if in_window:
            y = 1 if m["winner_id"] == a else 0
            p_blend = engine.win_prob(a, b, surface)
            p_elo = pred_prob(engine.overall.get(a, 1500.0), engine.overall.get(b, 1500.0))
            s_blend.add(p_blend, y)
            s_elo.add(p_elo, y)
            ra, rb = m["player_a_rank"], m["player_b_rank"]
            if ra and rb:
                s_rank.add(rb / (ra + rb), y)
            if calibrator is not None:
                s_cal.add(calibrator.apply(p_blend), y)

            if use_levers:
                cf = court_speed_feature(player_spw.get(a), player_spw.get(b), court_z.get(m["tourney_id"]))
                ff = fatigue_feature(load_a, load_b)
                lf = lefty_feature(player_hand.get(a), player_hand.get(b))
                tune_rows.append((p_blend, cf, ff, lf, y))
                p_lev = apply_levers(p_blend, court_feat=cf, fatigue_feat=ff, lefty_feat=lf,
                                     court_beta=TENNIS_COURT_SPEED_BETA,
                                     fatigue_beta=TENNIS_FATIGUE_BETA,
                                     lefty_beta=TENNIS_LEFTY_BETA)
                s_levers.add(p_lev, y)

            if m["status"] == "completed":
                actual = _total_games(m.get("score"))
                if actual is not None:
                    proj = project_from_winprob(p_blend, m["best_of"] or 3, surface)
                    games_abs_err += abs(proj["exp_total_games"] - actual)
                    games_n += 1

        engine.update(m["winner_id"], m["loser_id"], surface)
        if use_levers:
            g = _total_games(m.get("score")) or 0
            fatigue.add(a, m["date"], g)
            fatigue.add(b, m["date"], g)

    print(f"[tennis-backtest] window {start}..{end}  min_prior_matches={min_matches}\n")
    for s in (s_rank, s_elo, s_blend):
        print(s.report())
    if use_levers:
        print(s_levers.report())
    if calibrator is not None:
        print(s_cal.report())
    if games_n:
        print(f"\n  total-games MAE (blend): {games_abs_err/games_n:.2f}  (N={games_n})")

    if args.tune_levers:
        _tune(tune_rows)
    else:
        print()
        print(s_blend.calibration())


def _brier(rows, cb, fb, lb) -> float:
    bs = 0.0
    for p, cf, ff, lf, y in rows:
        pa = apply_levers(p, court_feat=cf, fatigue_feat=ff, lefty_feat=lf,
                          court_beta=cb, fatigue_beta=fb, lefty_beta=lb)
        pa = min(max(pa, 1e-6), 1 - 1e-6)
        bs += (pa - y) ** 2
    return bs / len(rows)


def _sweep(rows, label, lo, hi, step, set_beta):
    """Grid one beta (others 0); print the Brier-minimizing value vs the base."""
    base = _brier(rows, 0.0, 0.0, 0.0)
    best_b, best_brier = 0.0, base
    beta = lo
    while beta <= hi + 1e-9:
        bs = _brier(rows, *set_beta(beta))
        if bs < best_brier:
            best_b, best_brier = beta, bs
        beta += step
    # Require a non-trivial Brier improvement (>5e-4) to call a lever live — a
    # sub-0.0005 move on thousands of matches is noise (cf. the MLB dead levers).
    flag = "ship" if best_brier < base - 5e-4 and abs(best_b) > 1e-9 else "DEAD"
    print(f"  {label:<12} best_beta={best_b:+.2f}  Brier {base:.4f} -> {best_brier:.4f}  [{flag}]")
    return best_b


def _tune(rows: list[tuple]) -> None:
    if not rows:
        print("\n[tune-levers] no eval rows")
        return
    print(f"\n[tune-levers] grid search over {len(rows)} eval matches (base Brier {_brier(rows,0,0,0):.4f})")
    cb = _sweep(rows, "court_speed", -2.0, 2.0, 0.25, lambda x: (x, 0.0, 0.0))
    fb = _sweep(rows, "fatigue", -1.0, 1.0, 0.1, lambda x: (0.0, x, 0.0))
    lb = _sweep(rows, "lefty", -0.5, 0.5, 0.05, lambda x: (0.0, 0.0, x))
    joint = _brier(rows, cb, fb, lb)
    base = _brier(rows, 0, 0, 0)
    print(f"  {'joint':<12} betas=({cb:+.2f},{fb:+.2f},{lb:+.2f})  Brier {base:.4f} -> {joint:.4f}")
