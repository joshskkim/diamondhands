"""Surface-blended dynamic-K Elo for ATP players.

Pure in-memory engine (no DB) so it can be driven by the nightly refresh and
replayed walk-forward by the backtest with identical logic. Matches are fed in
chronological order; for each match the caller can read the *pre-match* blended
ratings (for prediction) and then apply the result.

Two rating tracks per player: an overall Elo and one Elo per surface
(hard/clay/grass). A surface rating is lazily seeded from the player's current
overall Elo the first time they appear on that surface (no look-ahead, since the
overall already reflects only prior matches) — this avoids cold 1500 ratings
dragging strong players down on a new surface. For rating a match on surface S we
blend: ELO_SURFACE_WEIGHT * surface_elo + (1 - w) * overall_elo.
"""
from __future__ import annotations

from ingester.tennis.constants import (
    ELO_BASE,
    ELO_K_DECAY,
    ELO_K_NUM,
    ELO_K_SHIFT,
    ELO_PRED_SCALE,
    ELO_SURFACE_WEIGHT,
    SURFACES,
)

# Round progression within a tournament (all share the tourney start date, so we
# replay early rounds first to keep updates causally ordered).
ROUND_ORDER = {
    "Q1": 0, "Q2": 0, "Q3": 0, "RR": 1, "R128": 1, "R64": 2, "R32": 3,
    "R16": 4, "QF": 5, "SF": 6, "BR": 6, "F": 7,
}


def round_rank(round_code: str | None) -> int:
    return ROUND_ORDER.get(round_code or "", 3)


def expected_score(elo_a: float, elo_b: float) -> float:
    """Logistic expected score for A vs B on the standard 400 scale (used for
    rating UPDATES)."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / 400.0))


def pred_prob(elo_a: float, elo_b: float) -> float:
    """Calibrated win probability for A vs B (wider ELO_PRED_SCALE; used for
    PREDICTION so the extremes aren't overconfident)."""
    return 1.0 / (1.0 + 10.0 ** ((elo_b - elo_a) / ELO_PRED_SCALE))


def _k(matches_played: int) -> float:
    """Glicko-flavoured dynamic K: large for newcomers, settling as games accrue."""
    return ELO_K_NUM / (matches_played + ELO_K_SHIFT) ** ELO_K_DECAY


class EloEngine:
    def __init__(self) -> None:
        self.overall: dict[str, float] = {}
        self.surface: dict[str, dict[str, float]] = {s: {} for s in SURFACES}
        self.n_overall: dict[str, int] = {}
        self.n_surface: dict[str, dict[str, int]] = {s: {} for s in SURFACES}

    def _surf_elo(self, player: str, surface: str) -> float:
        """Surface Elo, lazily seeded from the player's current overall Elo."""
        table = self.surface[surface]
        if player not in table:
            table[player] = self.overall.get(player, ELO_BASE)
        return table[player]

    def blended(self, player: str, surface: str | None) -> float:
        """Pre-match rating used for prediction: surface-blended when the surface
        is one we track, else the plain overall Elo."""
        overall = self.overall.get(player, ELO_BASE)
        if surface in self.surface:
            surf = self._surf_elo(player, surface)
            return ELO_SURFACE_WEIGHT * surf + (1.0 - ELO_SURFACE_WEIGHT) * overall
        return overall

    def win_prob(self, player_a: str, player_b: str, surface: str | None) -> float:
        """Calibrated P(A beats B) from blended ratings (read-only; no update)."""
        return pred_prob(self.blended(player_a, surface), self.blended(player_b, surface))

    def update(self, winner: str, loser: str, surface: str | None) -> None:
        """Apply a result, updating overall and (if tracked) surface ratings."""
        # Overall.
        ew = expected_score(self.overall.get(winner, ELO_BASE), self.overall.get(loser, ELO_BASE))
        kw = _k(self.n_overall.get(winner, 0))
        kl = _k(self.n_overall.get(loser, 0))
        self.overall[winner] = self.overall.get(winner, ELO_BASE) + kw * (1.0 - ew)
        self.overall[loser] = self.overall.get(loser, ELO_BASE) - kl * (1.0 - ew)
        self.n_overall[winner] = self.n_overall.get(winner, 0) + 1
        self.n_overall[loser] = self.n_overall.get(loser, 0) + 1

        # Surface (only for tracked surfaces).
        if surface in self.surface:
            sw = self._surf_elo(winner, surface)
            sl = self._surf_elo(loser, surface)
            esw = expected_score(sw, sl)
            kws = _k(self.n_surface[surface].get(winner, 0))
            kls = _k(self.n_surface[surface].get(loser, 0))
            self.surface[surface][winner] = sw + kws * (1.0 - esw)
            self.surface[surface][loser] = sl - kls * (1.0 - esw)
            self.n_surface[surface][winner] = self.n_surface[surface].get(winner, 0) + 1
            self.n_surface[surface][loser] = self.n_surface[surface].get(loser, 0) + 1

    def snapshot(self, player: str) -> dict[str, tuple[float, int]]:
        """Current (elo, matches) for a player across 'all' + each surface."""
        out = {"all": (self.overall.get(player, ELO_BASE), self.n_overall.get(player, 0))}
        for s in SURFACES:
            if player in self.surface[s]:
                out[s] = (self.surface[s][player], self.n_surface[s].get(player, 0))
        return out
