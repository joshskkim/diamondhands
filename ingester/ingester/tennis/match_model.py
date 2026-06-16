"""Bridge from the match-winner prior (surface-blended Elo) to a consistent
per-point serve model, so the headline win prob and the derivative markets
(total games, straight sets) come from one coherent object.

Approach: take the Elo blended win probability as authoritative, then solve for a
symmetric serve-advantage `d` such that the closed-form simulator reproduces that
win prob — pa = base + d (A's serve), pb = base - d (B's serve), where `base` is
the surface's league-average serve-points-won. This keeps the simulator's total-
games / straight-sets outputs consistent with the win prob without needing point-
in-time serve skills (which Elo already encodes the net effect of).

A separate Barnett–Clarke path (serve_probs_from_skills) is provided for the live
projection, where surface-specific SPW/RPW from the ratings snapshot are known.
"""
from __future__ import annotations

from ingester.tennis.constants import SURFACE_AVG_SPW
from ingester.tennis.match_sim import match_outcome

_SPW_MIN, _SPW_MAX = 0.40, 0.88


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def base_spw(surface: str | None) -> float:
    return SURFACE_AVG_SPW.get(surface or "all", SURFACE_AVG_SPW["all"])


def invert_serve_advantage(target_win_a: float, best_of: int, surface: str | None) -> tuple[float, float]:
    """Find (pa, pb) reproducing `target_win_a` under a symmetric serve advantage."""
    base = base_spw(surface)
    lo, hi = 0.0, min(base - _SPW_MIN, _SPW_MAX - base)  # max symmetric delta
    target = _clamp(target_win_a, 1e-4, 1 - 1e-4)

    def win_at(d: float) -> float:
        return match_outcome(base + d, base - d, best_of)["p_win_a"]

    # win_at is monotincreasing in d on [0, hi]; target<0.5 mirrors via sign.
    sign = 1.0 if target >= 0.5 else -1.0
    t = target if target >= 0.5 else 1.0 - target
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if win_at(mid) < t:
            lo = mid
        else:
            hi = mid
    d = sign * (lo + hi) / 2.0
    return (base + d, base - d)


def project_from_winprob(win_a: float, best_of: int, surface: str | None) -> dict:
    """Full per-match projection from an (already surface-blended) Elo win prob."""
    pa, pb = invert_serve_advantage(win_a, best_of, surface)
    out = match_outcome(pa, pb, best_of)
    return {
        "p_win_a": win_a,                      # authoritative (Elo); simulator is calibrated to it
        "p_serve_a": pa,
        "p_serve_b": pb,
        "exp_total_games": out["exp_total_games"],
        "prob_straight_sets": out["prob_straight_sets"],
    }


def serve_probs_from_skills(
    spw_a: float, rpw_a: float, spw_b: float, rpw_b: float, surface: str | None
) -> tuple[float, float]:
    """Barnett–Clarke combination: a player's serve level adjusted for how good the
    opponent is at returning relative to the surface average. (For the live model
    once point-in-time skills are available.)"""
    base = base_spw(surface)
    avg_rpw = 1.0 - base
    pa = spw_a - (rpw_b - avg_rpw)
    pb = spw_b - (rpw_a - avg_rpw)
    return (_clamp(pa, _SPW_MIN, _SPW_MAX), _clamp(pb, _SPW_MIN, _SPW_MAX))
