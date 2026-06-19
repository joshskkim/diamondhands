"""Opener / bullpen-game detection: is a listed "starter" really a starter?

MLB's probable pitcher is taken at face value by the rest of the pipeline and projected
as a full starter (60% of the lineup's PAs, 3-8 IP). But teams sometimes list a reliever
as the probable to OPEN a bullpen game — he throws 1-2 innings and is pulled. Projecting
him as a starter invents a 5-6 IP line and a phantom prop pick.

This module decides, from a pitcher's recorded-start history and season role, whether to
skip him. The hard constraint (the user's caveat): relievers DO convert to starters, so
the call is recency-weighted — recent real starts win over an ugly season-long ratio, and
a single fluke short outing never flags an established starter. Pure functions only; the
DB loads and the skip wiring live in runner.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from .constants import (
    OPENER_MAX_RECENT_IP,
    OPENER_REAL_START_OUTS,
    OPENER_RECENCY_DECAY,
    OPENER_RECENT_REAL_STARTS_OVERRIDE,
    OPENER_SEASON_IP_PER_APP_MIN,
    OPENER_STARTED_SHARE_MIN,
    OPENER_WINDOW,
)
from .workload import weighted_mean


@dataclass(frozen=True)
class SeasonRole:
    """Season-level pitcher role stats (from pitcher_season_role / MLB Stats API)."""

    games_started: int
    games_pitched: int
    innings_pitched: float
    games_finished: int = 0

    @property
    def started_share(self) -> float:
        return self.games_started / self.games_pitched if self.games_pitched else 0.0

    @property
    def ip_per_appearance(self) -> float:
        return self.innings_pitched / self.games_pitched if self.games_pitched else 0.0

    def looks_like_starter(self) -> bool:
        return (
            self.started_share >= OPENER_STARTED_SHARE_MIN
            and self.ip_per_appearance >= OPENER_SEASON_IP_PER_APP_MIN
        )


@dataclass(frozen=True)
class OpenerParams:
    """Tunable thresholds (defaults pulled from constants; tests override directly)."""

    recency_decay: float = OPENER_RECENCY_DECAY
    window: int = OPENER_WINDOW
    max_recent_ip: float = OPENER_MAX_RECENT_IP
    real_start_outs: int = OPENER_REAL_START_OUTS
    recent_real_starts_override: int = OPENER_RECENT_REAL_STARTS_OVERRIDE


DEFAULT = OpenerParams()


def is_likely_opener(
    outs_history: list[int],
    season: SeasonRole | None,
    params: OpenerParams = DEFAULT,
) -> tuple[bool, str]:
    """Decide whether a probable pitcher is a likely opener (→ skip projecting him).

    `outs_history` is recorded outs per START, MOST-RECENT-FIRST (from pitcher_starts).
    `season` is the pitcher's season role, or None when unknown (fetch failed / debut).
    Returns (flagged, reason); the reason feeds the skip log line. Fails OPEN — when in
    doubt it does NOT flag, so a legit starter is never silently dropped.
    """
    window = outs_history[: params.window]
    real_in_window = sum(1 for o in window if o >= params.real_start_outs)

    # 1. Recency veto: enough recent real starts means he's pitching as a starter now,
    #    no matter what a season-long reliever ratio says (RP→SP conversion).
    if real_in_window >= params.recent_real_starts_override:
        return False, f"{real_in_window} recent real starts -> SP"

    # 2. No recorded starts at all: lean entirely on the season role.
    if not window:
        if season is None:
            return False, "no start history, no season role -> project (fail open)"
        if season.looks_like_starter():
            return False, "no start history but season role = SP"
        return (
            True,
            f"no start history, season role = RP/opener "
            f"(GS/GP={season.started_share:.2f}, IP/app={season.ip_per_appearance:.1f})",
        )

    # 3. We have history. Recency signal = recency-weighted mean depth.
    recent_outs, _ = weighted_mean(
        [float(o) for o in window], decay=params.recency_decay, window=params.window
    )
    recent_ip = recent_outs / 3.0
    recency_opener = recent_ip < params.max_recent_ip

    if season is None:
        # Fetch failed: history-only fallback. Flag only if he's clearly short AND has
        # made no real start in the window.
        if recency_opener and real_in_window == 0:
            return True, f"no season role; recent_ip={recent_ip:.1f}, no real starts"
        return False, f"no season role; recent_ip={recent_ip:.1f}"

    # 4. Both signals available: require agreement so a single fluke can't flag an SP.
    season_opener = not season.looks_like_starter()
    if recency_opener and season_opener:
        return (
            True,
            f"opener: recent_ip={recent_ip:.1f}, GS/GP={season.started_share:.2f}, "
            f"IP/app={season.ip_per_appearance:.1f}",
        )
    return False, f"not opener: recent_ip={recent_ip:.1f}, season_SP={not season_opener}"
