"""Closed-form hierarchical match simulator (Newton & Keller / O'Malley family).

Under the standard i.i.d.-on-serve assumption, a match's outcome distribution is
fully determined by each player's per-point serve-win probability. We compute, in
closed form, the probability of holding a game, winning a tiebreak, winning a set
(with expected games), and winning the match (Bo3 or Bo5) with expected total
games and the probability of a straight-sets result.

All functions take pa, pb = the two players' serve-point-win probabilities for
THIS matchup (A serving / B serving). They are exact and fast (memoised DP), so
the backtest can call them per match.
"""
from __future__ import annotations

from functools import lru_cache


def game_win_prob(p: float) -> float:
    """Probability the server wins a game, server wins each point w.p. p
    (to 4 points, win by 2, with deuce)."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    q = 1.0 - p
    deuce = (p * p) / (p * p + q * q)            # P(win | at deuce)
    # win to love / 15 / 30, plus reach deuce (3-3) then win it
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


def tiebreak_win_prob(pa: float, pb: float) -> float:
    """P(A wins a 7-point tiebreak), A serving the first point. Serve alternates
    in the 1-2-2-... pattern; win by 2."""
    @lru_cache(maxsize=None)
    def f(a: int, b: int) -> float:
        if a >= 6 and b >= 6:
            if a == b:                            # 6-6, 7-7, ...: win-by-2 from level
                # next pair is one A-serve then one B-serve point
                wa = pa * (1.0 - pb)              # A wins both
                wb = (1.0 - pa) * pb              # B wins both
                return wa / (wa + wb)
        if a >= 7 and a - b >= 2:
            return 1.0
        if b >= 7 and b - a >= 2:
            return 0.0
        n = a + b
        server_a = (((n + 1) // 2) % 2 == 0)      # A serves point 0, then BB AA BB ...
        pw = pa if server_a else (1.0 - pb)       # P(A wins this point)
        return pw * f(a + 1, b) + (1.0 - pw) * f(a, b + 1)

    return f(0, 0)


def _set_solve(pa: float, pb: float) -> tuple[float, float]:
    """(P(A wins the set), E[games in the set]). A serves the first game."""
    hold_a = game_win_prob(pa)                    # A serving holds
    win_on_b_serve = 1.0 - game_win_prob(pb)      # A breaks B
    tb = tiebreak_win_prob(pa, pb)

    @lru_cache(maxsize=None)
    def f(ga: int, gb: int) -> tuple[float, float]:
        if ga >= 6 and ga - gb >= 2:
            return (1.0, 0.0)
        if gb >= 6 and gb - ga >= 2:
            return (0.0, 0.0)
        if ga == 6 and gb == 6:
            return (tb, 1.0)                       # the tiebreak counts as one game
        n = ga + gb
        a_serving = (n % 2 == 0)                   # A serves games 0,2,4,...
        pw = hold_a if a_serving else win_on_b_serve
        wa1, eg1 = f(ga + 1, gb)
        wa2, eg2 = f(ga, gb + 1)
        return (pw * wa1 + (1.0 - pw) * wa2, 1.0 + pw * eg1 + (1.0 - pw) * eg2)

    return f(0, 0)


def set_win_prob(pa: float, pb: float) -> float:
    return _set_solve(pa, pb)[0]


def match_outcome(pa: float, pb: float, best_of: int = 3) -> dict:
    """Match-level summary from per-point serve probs.

    Returns p_win_a, exp_total_games, prob_straight_sets. Sets are treated as
    independent draws with the same per-set win prob / expected games (a standard
    simplification; serve order across sets is approximated as A-first each set)."""
    p_set_a, e_games_set = _set_solve(pa, pb)
    need = best_of // 2 + 1

    @lru_cache(maxsize=None)
    def m(sa: int, sb: int) -> tuple[float, float]:
        if sa == need:
            return (1.0, 0.0)
        if sb == need:
            return (0.0, 0.0)
        wa1, es1 = m(sa + 1, sb)
        wa2, es2 = m(sa, sb + 1)
        pw = p_set_a * wa1 + (1.0 - p_set_a) * wa2
        es = 1.0 + p_set_a * es1 + (1.0 - p_set_a) * es2
        return (pw, es)

    p_win_a, e_sets = m(0, 0)
    return {
        "p_win_a": p_win_a,
        "exp_total_games": e_sets * e_games_set,
        "prob_straight_sets": p_set_a ** need + (1.0 - p_set_a) ** need,
        "p_set_a": p_set_a,
    }
