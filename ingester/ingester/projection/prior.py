"""Marcel-style multi-year true-talent prior (v2.4.0).

A batter's in-season rates are a noisy estimate of their true talent — on any
given day in May/June a regular has ~250 PA and a part-timer ~30. The model's
existing empirical-Bayes step (refresh-skills) corrects this by regressing toward
a baseline; until now that baseline was the flat *league* mean, which is blind to
the player's established skill and multi-year form.

This module computes the better baseline: a Marcel-style projection from the
player's prior three seasons — recency-weighted (5/4/3), PA-weighted, and itself
regressed toward the league mean so a thin track record reverts to league. No
aging curve in v1 (we don't store birthdates); that's the polish, not the bulk
of the value, and the ``ProjectionPrior`` interface leaves room to swap in a
licensed projection set (Steamer/ZiPS/THE BAT) without touching the model.

The pure functions here carry the math and are unit-tested without a DB;
``ingester.commands.refresh_priors`` wires them to ``player_game_stats``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection.constants import (
    MARCEL_REGRESSION_PA,
    MARCEL_SEASON_WEIGHTS,
)


@dataclass(frozen=True)
class SeasonLine:
    """One prior season's counting totals for a player (raw, un-regressed)."""

    pa: int
    ab: int
    hits: int
    hr: int
    tb: int
    k: int
    xwoba: float | None  # PA-weighted season xwOBA (None if unavailable)


@dataclass(frozen=True)
class ProjectionPrior:
    """A player's projected true-talent baseline for one target season.

    The stable seam the rest of the model regresses toward. ``proj_pa`` is the
    recency-weighted PA behind the estimate (reliability), not a PA forecast.
    """

    xwoba: float
    k_rate: float
    iso: float
    proj_pa: int


def _season_iso(line: SeasonLine) -> float | None:
    return (line.tb - line.hits) / line.ab if line.ab > 0 else None


def _season_k_rate(line: SeasonLine) -> float | None:
    return line.k / line.pa if line.pa > 0 else None


def _weighted_regress(
    pairs: list[tuple[float, float]],  # (weighted_pa, rate) per season
    league: float,
    regression_pa: float,
) -> float:
    """PA-weighted mean of per-season rates, regressed toward league.

    proj = (Σ wpa·rate + regression_pa·league) / (Σ wpa + regression_pa).
    Seasons with a missing rate are simply absent from ``pairs``.
    """
    num = regression_pa * league
    den = regression_pa
    for wpa, rate in pairs:
        num += wpa * rate
        den += wpa
    return num / den


def compute_marcel_prior(
    seasons_by_year: dict[int, SeasonLine],
    target_season: int,
    *,
    league_xwoba: float,
    league_k_rate: float,
    league_iso: float,
    weights: tuple[int, int, int] = MARCEL_SEASON_WEIGHTS,
    regression_pa: float = MARCEL_REGRESSION_PA,
) -> ProjectionPrior | None:
    """Project ``target_season`` from the prior three seasons.

    ``weights`` apply to (target-1, target-2, target-3). Returns None when the
    player has no usable prior-season data at all (a true debutant — the caller
    should fall back to the league mean for them).
    """
    # Collect (recency_weight, SeasonLine) for the seasons we actually have.
    present: list[tuple[int, SeasonLine]] = []
    for offset, weight in enumerate(weights, start=1):
        line = seasons_by_year.get(target_season - offset)
        if line is not None and line.pa > 0:
            present.append((weight, line))
    if not present:
        return None

    xwoba_pairs: list[tuple[float, float]] = []
    k_pairs: list[tuple[float, float]] = []
    iso_pairs: list[tuple[float, float]] = []
    weighted_pa = 0
    for weight, line in present:
        wpa = weight * line.pa
        weighted_pa += wpa
        if line.xwoba is not None:
            xwoba_pairs.append((wpa, line.xwoba))
        k_rate = _season_k_rate(line)
        if k_rate is not None:
            k_pairs.append((wpa, k_rate))
        iso = _season_iso(line)
        if iso is not None:
            iso_pairs.append((wpa, iso))

    return ProjectionPrior(
        xwoba=round(_weighted_regress(xwoba_pairs, league_xwoba, regression_pa), 4),
        k_rate=round(_weighted_regress(k_pairs, league_k_rate, regression_pa), 4),
        iso=round(_weighted_regress(iso_pairs, league_iso, regression_pa), 4),
        proj_pa=int(weighted_pa),
    )
