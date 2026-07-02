"""Marcel-style multi-year true-talent prior (v2.4.0).

A batter's in-season rates are a noisy estimate of their true talent — on any
given day in May/June a regular has ~250 PA and a part-timer ~30. The model's
existing empirical-Bayes step (refresh-skills) corrects this by regressing toward
a baseline; until now that baseline was the flat *league* mean, which is blind to
the player's established skill and multi-year form.

This module computes the better baseline: a Marcel-style projection from the
player's prior three seasons — recency-weighted (5/4/3), PA-weighted, and itself
regressed toward the league mean so a thin track record reverts to league. An
optional component-specific aging curve (Phase 3a, env-gated ``DIAMOND_AGING_ENABLED``,
OFF by default) ages the regressed xwOBA/ISO forward to the target season; the
``ProjectionPrior`` interface also leaves room to swap in a licensed projection set
(Steamer/ZiPS/THE BAT) without touching the model.

The pure functions here carry the math and are unit-tested without a DB;
``ingester.commands.refresh_priors`` wires them to ``player_game_stats``.
"""
from __future__ import annotations

from dataclasses import dataclass

from ingester.projection import constants as C
from ingester.projection.constants import (
    BAT_SPEED_ISO_PER_Z,
    BAT_SPEED_MEAN,
    BAT_SPEED_SD,
    FAST_SWING_ISO_PER_Z,
    FAST_SWING_MEAN,
    FAST_SWING_SD,
    MARCEL_REGRESSION_PA_ISO,
    MARCEL_REGRESSION_PA_K,
    MARCEL_REGRESSION_PA_XWOBA,
    MARCEL_SEASON_WEIGHTS,
    WHIFF_K_PER_Z,
    WHIFF_MEAN,
    WHIFF_SD,
)


def aging_factor(
    age: float, peak: float, up_per_year: float, down_per_year: float,
    clamp: tuple[float, float],
) -> float:
    """Multiplicative age adjustment for a 'higher-is-better' rate, ages forward to target.

    A player below ``peak`` is still improving, so the projection from his (younger) track
    record is nudged up; above peak it's nudged down (decline is usually steeper). 1.0 at
    the peak. Bounded by ``clamp`` so the tails stay sane.
    """
    if age <= peak:
        factor = 1.0 + up_per_year * (peak - age)
    else:
        factor = 1.0 - down_per_year * (age - peak)
    lo, hi = clamp
    return min(max(factor, lo), hi)


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
    regression_pa_xwoba: float = MARCEL_REGRESSION_PA_XWOBA,
    regression_pa_k: float = MARCEL_REGRESSION_PA_K,
    regression_pa_iso: float = MARCEL_REGRESSION_PA_ISO,
    iso_anchor: float | None = None,
    k_rate_anchor: float | None = None,
    age: float | None = None,
) -> ProjectionPrior | None:
    """Project ``target_season`` from the prior three seasons.

    ``weights`` apply to (target-1, target-2, target-3). Each metric reverts to its
    league mean by its own regression constant (K% light, ISO heavy — see constants).
    ``iso_anchor`` (v2.7): when the caller can supply a bat-speed-implied ISO (see
    bat_speed_iso_anchor), the ISO component regresses toward THAT instead of the
    flat league mean. Evidence-rich histories barely feel it (their own weighted PA
    dominate the phantom 1800); thin histories lean on it hard — which is exactly
    where the out-of-sample gate showed bat tracking helps (thin-half ISO MAE −4%)
    and where it showed redundancy for established hitters.
    ``k_rate_anchor`` (v2.8): same architecture for K — a whiff-implied K rate (see
    whiff_k_anchor). Out-of-sample this helped across the board, not just thin
    histories (deep 300+ PA K-rate MAE −17.5%), because league-shrinking a
    high-whiff hitter's K over-corrects where whiff is most informative.
    Returns None when the player has no usable prior-season data at all (a true
    debutant — the caller should fall back to the league mean for them).
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

    iso_target = iso_anchor if iso_anchor is not None else league_iso
    k_target = k_rate_anchor if k_rate_anchor is not None else league_k_rate
    xwoba = _weighted_regress(xwoba_pairs, league_xwoba, regression_pa_xwoba)
    k_rate = _weighted_regress(k_pairs, k_target, regression_pa_k)
    iso = _weighted_regress(iso_pairs, iso_target, regression_pa_iso)

    # Age the regressed projection forward to the target season (Phase 3a, gated OFF).
    # K-rate is intentionally left unaged. No age (debut / missing birth_date) → no change.
    if C.AGING_ENABLED and age is not None:
        xwoba *= aging_factor(
            age, C.AGING_PEAK_AGE_XWOBA,
            C.AGING_XWOBA_UP_PER_YEAR, C.AGING_XWOBA_DOWN_PER_YEAR, C.AGING_XWOBA_CLAMP)
        iso *= aging_factor(
            age, C.AGING_PEAK_AGE_ISO,
            C.AGING_ISO_UP_PER_YEAR, C.AGING_ISO_DOWN_PER_YEAR, C.AGING_ISO_CLAMP)

    return ProjectionPrior(
        xwoba=round(xwoba, 4),
        k_rate=round(k_rate, 4),
        iso=round(iso, 4),
        proj_pa=int(weighted_pa),
    )


def bat_speed_iso_anchor(
    avg_bat_speed: float | None,
    fast_swing_rate: float | None,
    league_iso: float,
) -> float | None:
    """Bat-speed-implied ISO: the regression target for thin ISO histories.

    Fit out-of-sample (2024 tracking → 2025 ISO, n=324): standalone corr .496 —
    nearly as predictive as a full 3-year Marcel (.617) from one season of swing
    physics. Centered on the league ISO (not the fitted intercept, which carries
    ≥200-PA survivor bias). Returns None without tracking data → caller falls back
    to the plain league anchor.
    """
    if avg_bat_speed is None or fast_swing_rate is None:
        return None
    bs_z = (avg_bat_speed - BAT_SPEED_MEAN) / BAT_SPEED_SD
    fast_z = (fast_swing_rate - FAST_SWING_MEAN) / FAST_SWING_SD
    return league_iso + BAT_SPEED_ISO_PER_Z * bs_z + FAST_SWING_ISO_PER_Z * fast_z


def whiff_k_anchor(whiff_rate: float | None, league_k_rate: float) -> float | None:
    """Whiff-implied K rate: the regression target for the K prior (v2.8).

    A batter's overall swinging-strike rate is a more granular contact-skill signal
    than PA-level K rate. Fit out-of-sample (2024 whiff -> 2025 K, n=322): standalone
    K ≈ league_k + .0401·whiff_z. Centered on the league K rate (not the fitted
    intercept, which carries ≥200-PA survivor bias), same as bat_speed_iso_anchor.
    Returns None without whiff data → caller falls back to the flat league anchor.

    (Lever 3 chase was moved OUT of this prior anchor and onto the matchup K driver —
    see matchup.batter_chase_k_delta — because the prior's K is bypassed by the matchup
    for ~88% of projections, so a prior-side chase term never reached them.)
    """
    if whiff_rate is None:
        return None
    whiff_z = (whiff_rate - WHIFF_MEAN) / WHIFF_SD
    return league_k_rate + WHIFF_K_PER_Z * whiff_z
