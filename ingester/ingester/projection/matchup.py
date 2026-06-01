"""Pitch-mix matchup scoring (v2.1 Sprint 2, Part 2).

Builds a matchup-aware xwOBA / K rate / ISO for a batter vs a specific pitcher by
weighting the batter's per-pitch-type skill (regressed toward the league baseline)
by the pitcher's usage of each pitch type. These replace the flat season blend as
the drivers of hit rate (xwOBA), K rate, and HR rate (ISO) in batter_model.

Handedness axes (the classic place this goes wrong — see test):
  * pitcher arsenal is looked up vs the BATTER's stand (how the pitcher pitches to
    that-handed hitters);
  * batter per-pitch-type stats are looked up vs the PITCHER's throws (how the
    batter hits that pitch from that-handed pitchers);
  * league baselines share the batter-stat axis (pitch type × pitcher throws).

The pure functions (empirical_bayes_regress, combine_component) carry the math and
are unit-tested without a DB; compute_matchup wires them to the snapshot tables.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import psycopg

from ingester.projection.constants import (
    MATCHUP_MIN_ARSENAL_PITCHES,
    MATCHUP_MIN_COVERED_USAGE,
    REGRESSION_K_PITCHES_BATTER,
)

QUALITY_MATCHUP = "matchup"
QUALITY_FALLBACK = "fallback_overall"


@dataclass(frozen=True)
class ArsenalEntry:
    pitch_type: str
    usage_rate: float
    pitches_thrown: int


@dataclass(frozen=True)
class BatterPitchStat:
    xwoba: float | None
    k_rate: float | None
    iso: float | None
    pitches_seen: int


@dataclass(frozen=True)
class PitchBaseline:
    xwoba: float | None
    k_rate: float | None
    iso: float | None


@dataclass(frozen=True)
class MatchupResult:
    xwoba: float
    k_rate: float
    iso: float
    quality: str
    covered_usage: float  # share of the pitcher's mix the batter had data for (xwOBA)


# ---------------------------------------------------------------------------
# Pure math
# ---------------------------------------------------------------------------

def empirical_bayes_regress(raw: float | None, n: int, league: float, k: int) -> float:
    """Blend a raw per-pitch-type rate toward its league mean by sample size.

    weight = n / (n + k); a None raw rate collapses to the league mean.
    """
    if raw is None:
        return league
    w = n / (n + k)
    return w * raw + (1.0 - w) * league


def combine_component(
    arsenal: list[ArsenalEntry],
    batter_stat_for: dict[str, BatterPitchStat],
    league_for: dict[str, float],
    overall: float,
    *,
    metric: str,
    k_regress: int = REGRESSION_K_PITCHES_BATTER,
) -> tuple[float, float]:
    """
    Usage-weighted, regressed matchup value for one metric ('xwoba'|'k_rate'|'iso').

    Returns (value, covered_usage). For pitch types the batter has data for, use the
    regressed per-type rate; weight by the pitcher's usage of that type. If the
    covered usage is at least MATCHUP_MIN_COVERED_USAGE, normalize over the covered
    share (a clean weighted average); otherwise backfill the uncovered share with
    the batter's overall blend so a thin-coverage matchup can't swing wildly.
    """
    acc = 0.0
    covered = 0.0
    for entry in arsenal:
        stat = batter_stat_for.get(entry.pitch_type)
        if stat is None:
            continue
        raw = getattr(stat, metric)
        league = league_for.get(entry.pitch_type, overall)
        regressed = empirical_bayes_regress(raw, stat.pitches_seen, league, k_regress)
        acc += entry.usage_rate * regressed
        covered += entry.usage_rate

    if covered <= 0.0:
        return overall, 0.0
    if covered >= MATCHUP_MIN_COVERED_USAGE:
        return acc / covered, covered
    # Partial coverage: fill the uncovered share of the mix with the overall blend.
    return acc + (1.0 - covered) * overall, covered


# ---------------------------------------------------------------------------
# DB fetchers (most-recent snapshot with as_of_date <= reference date)
# ---------------------------------------------------------------------------

def fetch_pitcher_arsenal(
    conn: psycopg.Connection, pitcher_id: int, as_of_date: date, batter_hand: str
) -> list[ArsenalEntry]:
    rows = conn.execute(
        """
        SELECT pitch_type, usage_rate, pitches_thrown
        FROM pitcher_arsenal
        WHERE player_id = %s AND vs_handedness = %s
          AND as_of_date = (
              SELECT MAX(as_of_date) FROM pitcher_arsenal
              WHERE player_id = %s AND vs_handedness = %s AND as_of_date <= %s
          )
        """,
        (pitcher_id, batter_hand, pitcher_id, batter_hand, as_of_date),
    ).fetchall()
    return [
        ArsenalEntry(
            pitch_type=str(r[0]),
            usage_rate=float(r[1]) if r[1] is not None else 0.0,
            pitches_thrown=int(r[2]),
        )
        for r in rows
    ]


def fetch_batter_pitch_stats(
    conn: psycopg.Connection, batter_id: int, pitcher_hand: str, as_of_date: date
) -> dict[str, BatterPitchStat]:
    rows = conn.execute(
        """
        SELECT pitch_type, xwoba, k_rate, iso, pitches_seen
        FROM batter_pitch_type_stats
        WHERE player_id = %s AND vs_handedness = %s
          AND as_of_date = (
              SELECT MAX(as_of_date) FROM batter_pitch_type_stats
              WHERE player_id = %s AND vs_handedness = %s AND as_of_date <= %s
          )
        """,
        (batter_id, pitcher_hand, batter_id, pitcher_hand, as_of_date),
    ).fetchall()
    return {
        str(r[0]): BatterPitchStat(
            xwoba=float(r[1]) if r[1] is not None else None,
            k_rate=float(r[2]) if r[2] is not None else None,
            iso=float(r[3]) if r[3] is not None else None,
            pitches_seen=int(r[4]),
        )
        for r in rows
    }


def fetch_league_baselines(
    conn: psycopg.Connection, season: int, pitcher_hand: str
) -> dict[str, PitchBaseline]:
    """League baseline per pitch type vs the given pitcher hand, with 'A' fill-in."""
    rows = conn.execute(
        """
        SELECT pitch_type, vs_handedness, league_xwoba, league_k_rate, league_iso
        FROM pitch_type_league_baselines
        WHERE season = %s AND vs_handedness IN (%s, 'A')
        """,
        (season, pitcher_hand),
    ).fetchall()
    specific: dict[str, PitchBaseline] = {}
    any_hand: dict[str, PitchBaseline] = {}
    for pt, hand, xw, kr, iso in rows:
        target = specific if hand == pitcher_hand else any_hand
        target[str(pt)] = PitchBaseline(
            xwoba=float(xw) if xw is not None else None,
            k_rate=float(kr) if kr is not None else None,
            iso=float(iso) if iso is not None else None,
        )
    # Prefer the hand-specific baseline; fall back to 'A' where it's missing.
    return {**any_hand, **specific}


# ---------------------------------------------------------------------------
# Top-level matchup
# ---------------------------------------------------------------------------

def compute_matchup(
    conn: psycopg.Connection,
    *,
    batter_id: int,
    pitcher_id: int,
    batter_hand: str,
    pitcher_hand: str,
    as_of_date: date,
    season: int,
    overall_xwoba: float,
    overall_k_rate: float,
    overall_iso: float,
) -> MatchupResult:
    """
    Resolve the matchup-aware (xwoba, k_rate, iso) for one batter vs one pitcher.

    Falls back to the v2.0.0 overall blend (quality='fallback_overall') when the
    pitcher has too little arsenal data or the batter has no per-pitch-type data
    for any pitch the pitcher throws.
    """
    arsenal = fetch_pitcher_arsenal(conn, pitcher_id, as_of_date, batter_hand)
    if not arsenal or sum(a.pitches_thrown for a in arsenal) < MATCHUP_MIN_ARSENAL_PITCHES:
        return MatchupResult(overall_xwoba, overall_k_rate, overall_iso, QUALITY_FALLBACK, 0.0)

    batter_stats = fetch_batter_pitch_stats(conn, batter_id, pitcher_hand, as_of_date)
    baselines = fetch_league_baselines(conn, season, pitcher_hand)
    league_xwoba = {pt: b.xwoba for pt, b in baselines.items() if b.xwoba is not None}
    league_k = {pt: b.k_rate for pt, b in baselines.items() if b.k_rate is not None}
    league_iso = {pt: b.iso for pt, b in baselines.items() if b.iso is not None}

    xwoba, covered = combine_component(
        arsenal, batter_stats, league_xwoba, overall_xwoba, metric="xwoba"
    )
    k_rate, _ = combine_component(
        arsenal, batter_stats, league_k, overall_k_rate, metric="k_rate"
    )
    iso, _ = combine_component(
        arsenal, batter_stats, league_iso, overall_iso, metric="iso"
    )

    quality = QUALITY_MATCHUP if covered > 0.0 else QUALITY_FALLBACK
    return MatchupResult(round(xwoba, 4), round(k_rate, 4), round(iso, 4), quality, covered)
