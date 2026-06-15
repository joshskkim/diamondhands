"""Recency-weighted, surface-specific serve/return skills (SPW / RPW).

SPW = serve points won / serve points (the engine of the point model).
RPW = return points won / return points faced (= opponent serve points lost).

Each match is weighted by exp decay on its age (half-life SKILL_HALFLIFE_DAYS) and
the result is regressed toward the surface league mean with SKILL_PRIOR_POINTS of
prior weight, so thin samples don't produce wild rates. Computed for 'all' plus
each tracked surface, as of a reference date (so the same code serves the nightly
refresh and the walk-forward backtest).
"""
from __future__ import annotations

from datetime import date

from ingester.tennis.constants import (
    SKILL_HALFLIFE_DAYS,
    SKILL_PRIOR_POINTS,
    SURFACE_AVG_SPW,
    SURFACES,
)


def decay_weight(age_days: float, halflife: float = SKILL_HALFLIFE_DAYS) -> float:
    if age_days < 0:
        return 0.0
    return 0.5 ** (age_days / halflife)


class _Accum:
    __slots__ = ("spw_num", "spw_den", "rpw_num", "rpw_den", "n")

    def __init__(self) -> None:
        self.spw_num = self.spw_den = self.rpw_num = self.rpw_den = 0.0
        self.n = 0

    def add(self, w: float, won: int, svpt: int, opp_won: int, opp_svpt: int) -> None:
        self.spw_num += w * won
        self.spw_den += w * svpt
        self.rpw_num += w * (opp_svpt - opp_won)   # return points won = opp serve points lost
        self.rpw_den += w * opp_svpt
        self.n += 1

    def resolve(self, mean_spw: float) -> tuple[float, float, int] | None:
        if self.spw_den <= 0 or self.rpw_den <= 0:
            return None
        spw = (self.spw_num + SKILL_PRIOR_POINTS * mean_spw) / (self.spw_den + SKILL_PRIOR_POINTS)
        # Return-point prior mean is the complement of serve dominance on the surface.
        rpw = (self.rpw_num + SKILL_PRIOR_POINTS * (1.0 - mean_spw)) / (self.rpw_den + SKILL_PRIOR_POINTS)
        return (spw, rpw, self.n)


def build_skills(conn, as_of: date) -> dict[str, dict[str, tuple[float, float, int]]]:
    """Return {player_id: {surface: (spw, rpw, n)}} for 'all' + each surface, using
    only matches on/before `as_of`."""
    rows = conn.execute(
        """
        SELECT m.match_date, m.surface, s.player_id,
               (COALESCE(s.first_won,0) + COALESCE(s.second_won,0)) AS won,
               s.serve_points AS svpt,
               (COALESCE(o.first_won,0) + COALESCE(o.second_won,0)) AS opp_won,
               o.serve_points AS opp_svpt
        FROM tennis_player_match_stats s
        JOIN tennis_player_match_stats o
          ON o.match_id = s.match_id AND o.player_id <> s.player_id
        JOIN tennis_matches m ON m.id = s.match_id
        WHERE m.match_date <= %s AND s.serve_points > 0 AND o.serve_points > 0
        """,
        (as_of,),
    ).fetchall()

    # player -> surface_key -> _Accum   (surface_key in {'all','hard','clay','grass'})
    acc: dict[str, dict[str, _Accum]] = {}
    for match_date, surface, pid, won, svpt, opp_won, opp_svpt in rows:
        w = decay_weight((as_of - match_date).days)
        if w <= 0:
            continue
        keys = ["all"]
        if surface in SURFACES:
            keys.append(surface)
        bucket = acc.setdefault(pid, {})
        for key in keys:
            bucket.setdefault(key, _Accum()).add(w, won, svpt, opp_won, opp_svpt)

    out: dict[str, dict[str, tuple[float, float, int]]] = {}
    for pid, by_surface in acc.items():
        resolved: dict[str, tuple[float, float, int]] = {}
        for key, a in by_surface.items():
            mean_spw = SURFACE_AVG_SPW.get(key, SURFACE_AVG_SPW["all"])
            r = a.resolve(mean_spw)
            if r is not None:
                resolved[key] = r
        if resolved:
            out[pid] = resolved
    return out
