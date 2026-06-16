"""Refinement levers (Milestone 3): small, signed adjustments to the match-winner
probability, each gated by a beta that is 0 until proven on the backtest.

All features are signed so a positive value favors player_a, and are applied in
logit space so the adjustment is symmetric and bounded:

    p' = sigmoid( logit(p) + court_beta*court + fatigue_beta*fatigue + lefty_beta*lefty )

Feature functions are pure; FatigueTracker maintains point-in-time recent load as
the backtest replays matches chronologically.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import date, timedelta

from ingester.tennis.constants import (
    FATIGUE_GAMES_SCALE,
    FATIGUE_WINDOW_DAYS,
)


def _logit(p: float) -> float:
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


# ── Feature functions (signed; positive favors player_a) ─────────────────────

def court_speed_feature(spw_a: float | None, spw_b: float | None,
                        court_speed_z: float | None) -> float:
    """On a fast court (court_speed_z > 0) the better server gains."""
    if spw_a is None or spw_b is None or court_speed_z is None:
        return 0.0
    return court_speed_z * (spw_a - spw_b)


def fatigue_feature(load_a: float, load_b: float) -> float:
    """More recent load on a player hurts them; scaled to ~unit range."""
    return (load_b - load_a) / FATIGUE_GAMES_SCALE


def lefty_feature(hand_a: str | None, hand_b: str | None) -> float:
    """Lefty edge: +1 when a is a lefty vs a right-handed b, −1 for the reverse."""
    a = 1.0 if hand_a == "L" else 0.0
    b = 1.0 if hand_b == "L" else 0.0
    return a - b


AGE_PEAK = 24.5  # peak performance age (research ~24–25)


def _age_curve(age: float) -> float:
    """Concave aging curve, 0 at peak, falling away (scale absorbed by the beta)."""
    return -(((age - AGE_PEAK) / 10.0) ** 2)


def age_feature(age_a: float | None, age_b: float | None) -> float:
    """Favors the player nearer peak age."""
    if age_a is None or age_b is None:
        return 0.0
    return _age_curve(age_a) - _age_curve(age_b)


def backhand_feature(bh_a: int | None, bh_b: int | None) -> float:
    """One-handers (backhand==1) are slightly disadvantaged: +1 when b is the
    one-hander (favoring two-hander a), −1 for the reverse."""
    if bh_a is None or bh_b is None:
        return 0.0
    return (1.0 if bh_b == 1 else 0.0) - (1.0 if bh_a == 1 else 0.0)


def apply_levers(
    p: float,
    *,
    court_feat: float = 0.0,
    fatigue_feat: float = 0.0,
    lefty_feat: float = 0.0,
    age_feat: float = 0.0,
    backhand_feat: float = 0.0,
    court_beta: float = 0.0,
    fatigue_beta: float = 0.0,
    lefty_beta: float = 0.0,
    age_beta: float = 0.0,
    backhand_beta: float = 0.0,
) -> float:
    """Adjust a win probability by the active levers (logit space)."""
    z = (_logit(p)
         + court_beta * court_feat
         + fatigue_beta * fatigue_feat
         + lefty_beta * lefty_feat
         + age_beta * age_feat
         + backhand_beta * backhand_feat)
    return _sigmoid(z)


# ── Point-in-time fatigue ────────────────────────────────────────────────────

class FatigueTracker:
    """Per-player recent-games load. Feed matches in chronological order; query
    load BEFORE adding the current match so it counts only prior play (same-day
    earlier rounds included, since match dates are tournament-start dates)."""

    def __init__(self, window_days: int = FATIGUE_WINDOW_DAYS) -> None:
        self.window = timedelta(days=window_days)
        self._hist: dict[str, deque[tuple[date, int]]] = defaultdict(deque)

    def load(self, player: str, as_of: date) -> float:
        dq = self._hist.get(player)
        if not dq:
            return 0.0
        cutoff = as_of - self.window
        return float(sum(g for (d, g) in dq if cutoff <= d <= as_of))

    def add(self, player: str, match_date: date, games: int) -> None:
        dq = self._hist[player]
        dq.append((match_date, games))
        # Bound memory: drop entries well outside any future window.
        horizon = match_date - self.window
        while dq and dq[0][0] < horizon:
            dq.popleft()
