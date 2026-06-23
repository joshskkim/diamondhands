"""Sim-native correlation & same-game-parlay (SGP) pricing.

Diamond's Monte-Carlo simulator (`game_sim.py`) already draws the full joint game
state thousands of times; the projection pipeline then collapses it to *marginal*
per-leg probabilities and throws the joint away. This module reads the retained
per-sim arrays back off a `GameSim` and prices the JOINT — which is where the SGP
market's fattest margins live, because books charge a blunt correlation tax that
retail can't quantify.

A "leg" is any bet we can evaluate per simulation as a boolean. We support:
  - batter props  : (team, slot, market in {hit1plus,hit2plus,hr,k1plus}, side)
  - game totals    : (innings, line, side over/under)
  - team totals     : (team, innings, line, side over/under)
  - moneyline      : (team) — full game, extra-inning ties split out as no-win

Honest scope: the two teams are simulated with INDEPENDENT rng streams, so a HOME
player leg and an AWAY player leg are ~uncorrelated by construction. The real,
captured edge is WITHIN a team (a hitter's big day rides his team's runs) and any
leg vs the GAME TOTAL (which contains that team's runs). We expose
:func:`correlation` so callers can see — and not oversell — how much signal a pair
actually carries.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ingester.projection.game_sim import GameSim

_BATTER_MARKETS = {"hit1plus", "hit2plus", "hr", "k1plus"}


@dataclass(frozen=True)
class Leg:
    """One parlay leg, evaluable per simulation. See module docstring for kinds.

    side semantics: batter/total/team_total use 'over'/'under' (the batter markets
    are themselves thresholds, so 'over' = the threshold is met, 'under' = it isn't);
    moneyline uses the team name in `team` and ignores side.
    """
    kind: str                      # 'batter' | 'total' | 'team_total' | 'moneyline'
    side: str = "over"             # 'over' | 'under' (ignored for moneyline)
    team: str | None = None        # 'home' | 'away' (batter / team_total / moneyline)
    slot: int | None = None        # 0..8 lineup slot (batter)
    market: str | None = None      # batter market key
    innings: int = 9               # period for total / team_total (1,3,5,7,9)
    line: float | None = None      # total / team_total O/U line


def _team(sim: GameSim, team: str):
    ts = sim.home if team == "home" else sim.away if team == "away" else None
    if ts is None:
        raise ValueError(
            f"GameSim has no retained '{team}' arrays — build it via simulate_game "
            "(joint pricing needs the per-sim draws, not just the marginals)."
        )
    return ts


def leg_mask(sim: GameSim, leg: Leg) -> np.ndarray:
    """Boolean (n_sims,) array: True in each sim where the leg hits."""
    if leg.kind == "batter":
        if leg.market not in _BATTER_MARKETS or leg.slot is None or leg.team is None:
            raise ValueError("batter leg needs team, slot, and a valid market")
        ts = _team(sim, leg.team)
        if leg.market == "hit1plus":
            hit = ts.slot_hits[:, leg.slot] >= 1
        elif leg.market == "hit2plus":
            hit = ts.slot_hits[:, leg.slot] >= 2
        elif leg.market == "hr":
            hit = ts.slot_hr[:, leg.slot] >= 1
        else:  # k1plus
            hit = ts.slot_k[:, leg.slot] >= 1
        return hit if leg.side == "over" else ~hit

    if leg.kind == "total":
        if leg.line is None:
            raise ValueError("total leg needs a line")
        pm = sim.periods[leg.innings]
        total = pm.home_runs + pm.away_runs
        return total > leg.line if leg.side == "over" else total < leg.line

    if leg.kind == "team_total":
        if leg.line is None or leg.team is None:
            raise ValueError("team_total leg needs team and line")
        pm = sim.periods[leg.innings]
        runs = pm.home_runs if leg.team == "home" else pm.away_runs
        return runs > leg.line if leg.side == "over" else runs < leg.line

    if leg.kind == "moneyline":
        if leg.team is None:
            raise ValueError("moneyline leg needs a team")
        pm = sim.periods[leg.innings]
        return (pm.home_runs > pm.away_runs) if leg.team == "home" \
            else (pm.away_runs > pm.home_runs)

    raise ValueError(f"unknown leg kind: {leg.kind}")


def marginal(sim: GameSim, leg: Leg) -> float:
    """P(leg) from the sim — the same number the marginal pipeline would report."""
    return float(leg_mask(sim, leg).mean())


def joint_prob(sim: GameSim, legs: list[Leg]) -> float:
    """P(all legs hit together) from the joint draws."""
    if not legs:
        return float("nan")
    mask = np.ones(sim.n_sims, dtype=bool)
    for leg in legs:
        mask &= leg_mask(sim, leg)
    return float(mask.mean())


def independent_prob(sim: GameSim, legs: list[Leg]) -> float:
    """Product of the legs' marginals — what a naive 'legs are independent' parlay assumes."""
    p = 1.0
    for leg in legs:
        p *= marginal(sim, leg)
    return p


def correlation(sim: GameSim, a: Leg, b: Leg) -> float:
    """Phi (Pearson on the 0/1 masks) between two legs; NaN if either never varies."""
    ma = leg_mask(sim, a).astype(float)
    mb = leg_mask(sim, b).astype(float)
    sa, sb = ma.std(), mb.std()
    if sa == 0 or sb == 0:
        return float("nan")
    return float(((ma - ma.mean()) * (mb - mb.mean())).mean() / (sa * sb))


@dataclass(frozen=True)
class SgpQuote:
    """A priced same-game parlay."""
    model_joint: float        # our true joint probability from the sim
    independent_joint: float  # product of marginals (the naive-independence assumption)
    correlation_lift: float   # model_joint - independent_joint (the edge the book mis-taxes)
    book_decimal: float | None  # the book's combined SGP decimal price, if supplied
    book_implied: float | None  # 1 / book_decimal (vig-inclusive)
    ev: float | None          # model_joint * book_decimal - 1 (per $1), if priced
    fair_decimal: float       # 1 / model_joint (our fair price, no vig)


def price_sgp(sim: GameSim, legs: list[Leg], book_decimal: float | None = None) -> SgpQuote:
    """Price a same-game parlay against the sim's joint and (optionally) a book line.

    ``correlation_lift`` is the heart of it: how far the true joint sits from the
    independence assumption the parlay price is usually built on. Positive lift means
    the legs are positively correlated and a book pricing them as independent is
    *underpaying* the bettor's true probability; negative means the opposite.
    """
    if not legs:
        raise ValueError("price_sgp requires at least one leg")
    model_joint = joint_prob(sim, legs)
    indep = independent_prob(sim, legs)
    book_implied = (1.0 / book_decimal) if book_decimal else None
    ev = (model_joint * book_decimal - 1.0) if book_decimal else None
    fair_decimal = (1.0 / model_joint) if model_joint > 0 else float("inf")
    return SgpQuote(
        model_joint=model_joint,
        independent_joint=indep,
        correlation_lift=model_joint - indep,
        book_decimal=book_decimal,
        book_implied=book_implied,
        ev=ev,
        fair_decimal=fair_decimal,
    )
