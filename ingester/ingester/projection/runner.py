"""CLI runner: project today's slate into batter_projections and game_projections."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.projection.batter_model import (
    BatterProbabilities,
    BatterProjection,
    BatterSkillInput,
    blend_batter_skills,
    expected_team_runs,
    league_average_projection,
    pitcher_line_from_lineup,
    project_batter,
    yrfi_probability,
)
from ingester.projection.game_sim import GameSim, simulate_game
from ingester.projection.constants import (
    EXPECTED_PA_PER_STARTER,
    LINEUP_SIZE_HITTERS,
    LINEUP_STARTERS,
    MIN_PLATOON_PA,
    MODEL_VERSION,
    PA_BY_ORDER,
    PLATOON_ENABLED,
    PLATOON_FULL_WEIGHT_PA,
    PLATOON_WEIGHT_CAP,
)
from ingester.projection.matchup import MatchupResult, compute_matchup
from ingester.projection.park_adj import (
    BattedBallProfile,
    LEAGUE_AVERAGE_PROFILE,
    ParkAdjustments,
    ParkFactors,
    ParkGeometry,
    compute_park_adjustments,
    weather_carry_hr_mult,
)
from ingester.projection.pitcher_adj import (
    PitcherHandSplit,
    compute_pitcher_adjustments,
    resolve_pitcher_skill,
)
from ingester.projection.weather_adj import carry_delta_ft, compute_weather_adjustments
from ingester.projection.calibration import Calibrator

log = logging.getLogger(__name__)

_PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "CP", "TWP"})

# Monte-Carlo game simulator (game_sim.py) settings for the per-game sim run.
SIM_N_SIMS = 4000
SIM_FULL_HIST_MAX = 25   # combined-run histogram upper bin for the full game
SIM_F5_HIST_MAX = 15     # combined-run histogram upper bin for first five innings


@dataclass
class TeamSideProjection:
    """Result of projecting one team's hitters: expected runs plus the lineups the
    game simulator needs (same batters vs the opposing starter and vs the bullpen)."""
    expected_runs: float
    starter_projs: list[BatterProjection]
    bullpen_projs: list[BatterProjection]

# S3: optional per-market probability calibration, applied as a final post-process to
# every projection. Set by cmd_project/cmd_backtest (--calibrate); None = no-op.
_CALIBRATOR: Calibrator | None = None


def set_calibrator(calibrator: Calibrator | None) -> None:
    """Install (or clear) the process-wide projection calibrator."""
    global _CALIBRATOR
    _CALIBRATOR = calibrator


def _maybe_calibrate(proj):
    """Recalibrate a projection's market probabilities if a calibrator is installed."""
    return _CALIBRATOR.apply(proj) if _CALIBRATOR is not None else proj


# Backtest-only: when set, the backtest path personalizes the park HR factor using
# each hitter's PRIOR-season batted-ball profile (leak-free — the prior season is
# entirely before the backtest game). Off by default so existing backtests are
# unchanged. The live path always personalizes from the current-season profile.
_BACKTEST_PARK_PERSONALIZED: bool = False


def set_backtest_park_personalized(flag: bool) -> None:
    """Toggle prior-season park personalization in the backtest projection path."""
    global _BACKTEST_PARK_PERSONALIZED
    _BACKTEST_PARK_PERSONALIZED = flag


@dataclass
class ProjectSummary:
    game_date: date
    games_seen: int = 0
    games_projected: int = 0
    games_skipped: int = 0
    batter_rows: int = 0
    skip_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SlateGame:
    game_id: int
    home_team_id: int
    away_team_id: int
    home_probable_pitcher_id: int | None
    away_probable_pitcher_id: int | None
    temperature_f: float | None
    wind_speed_mph: float | None
    wind_from_degrees: float | None
    relative_humidity_pct: float | None
    surface_pressure_hpa: float | None
    weather_fetched_at: datetime | None
    is_dome: bool
    is_retractable: bool
    cf_bearing_degrees: float
    altitude_feet: float | None
    park_factor_hits: float
    park_factor_hr_lhb: float
    park_factor_hr_rhb: float
    lf_line_ft: float | None = None
    cf_ft: float | None = None
    rf_line_ft: float | None = None
    lf_wall_ft: float | None = None
    cf_wall_ft: float | None = None
    rf_wall_ft: float | None = None


@dataclass(frozen=True)
class HitterCandidate:
    player_id: int
    bats: str
    pa_l30: int


@dataclass(frozen=True)
class LineupHitter:
    """A batter to project for one team side, with its expected-PA source resolved."""

    player_id: int
    bats: str
    expected_pa: float
    lineup_position: int | None  # 1-9 when confirmed, else None
    lineup_confirmed: bool


def infer_season(game_date: date) -> int:
    """Map a game date to its MLB season year (calendar year for skill lookup)."""
    return game_date.year


def _as_float(val) -> float | None:
    if val is None:
        return None
    return float(val)


def _load_slate_games(conn: psycopg.Connection, game_date: date) -> list[SlateGame]:
    rows = conn.execute(
        """
        SELECT
            g.id,
            g.home_team_id,
            g.away_team_id,
            g.home_probable_pitcher_id,
            g.away_probable_pitcher_id,
            g.temperature_f,
            g.wind_speed_mph,
            g.wind_direction_degrees,
            g.weather_fetched_at,
            s.is_dome,
            COALESCE(s.is_retractable, FALSE),
            s.cf_bearing_degrees,
            COALESCE(s.park_factor_hits, 1.0),
            COALESCE(s.park_factor_hr_lhb, 1.0),
            COALESCE(s.park_factor_hr_rhb, 1.0),
            g.relative_humidity_pct,
            g.surface_pressure_hpa,
            s.altitude_feet,
            s.lf_line_ft,
            s.cf_ft,
            s.rf_line_ft,
            s.lf_wall_ft,
            s.cf_wall_ft,
            s.rf_wall_ft
        FROM games g
        JOIN stadiums s ON s.id = g.stadium_id
        WHERE g.game_date = %s
          AND g.stadium_id IS NOT NULL
        ORDER BY g.start_time_utc
        """,
        (game_date,),
    ).fetchall()

    games: list[SlateGame] = []
    for row in rows:
        games.append(
            SlateGame(
                game_id=int(row[0]),
                home_team_id=int(row[1]),
                away_team_id=int(row[2]),
                home_probable_pitcher_id=row[3],
                away_probable_pitcher_id=row[4],
                temperature_f=_as_float(row[5]),
                wind_speed_mph=_as_float(row[6]),
                wind_from_degrees=_as_float(row[7]),
                relative_humidity_pct=_as_float(row[15]),
                surface_pressure_hpa=_as_float(row[16]),
                weather_fetched_at=row[8],
                is_dome=bool(row[9]),
                is_retractable=bool(row[10]),
                cf_bearing_degrees=float(row[11]),
                altitude_feet=_as_float(row[17]),
                park_factor_hits=float(row[12]),
                park_factor_hr_lhb=float(row[13]),
                park_factor_hr_rhb=float(row[14]),
                lf_line_ft=_as_float(row[18]),
                cf_ft=_as_float(row[19]),
                rf_line_ft=_as_float(row[20]),
                lf_wall_ft=_as_float(row[21]),
                cf_wall_ft=_as_float(row[22]),
                rf_wall_ft=_as_float(row[23]),
            )
        )
    return games


def _likely_hitters(
    conn: psycopg.Connection,
    team_id: int,
    as_of: date,
) -> list[HitterCandidate]:
    """
    v1 lineup proxy: top ``LINEUP_SIZE_HITTERS`` non-pitchers by PA in the last 30 days.

    Not a confirmed lineup — order is by recent playing time only.
    """
    window_start = as_of - timedelta(days=30)
    window_end = as_of - timedelta(days=1)
    rows = conn.execute(
        """
        SELECT
            p.id,
            COALESCE(p.bats, 'R') AS bats,
            SUM(pgs.plate_appearances)::int AS pa_l30
        FROM player_game_stats pgs
        JOIN players p ON p.id = pgs.player_id
        WHERE p.team_id = %s
          AND pgs.game_date BETWEEN %s AND %s
          AND pgs.plate_appearances IS NOT NULL
          AND pgs.plate_appearances > 0
          AND NOT (COALESCE(p.position, '') = ANY(%s))
        GROUP BY p.id, p.bats
        ORDER BY pa_l30 DESC
        LIMIT %s
        """,
        (team_id, window_start, window_end, list(_PITCHER_POSITIONS), LINEUP_SIZE_HITTERS),
    ).fetchall()
    return [
        HitterCandidate(player_id=int(r[0]), bats=str(r[1]), pa_l30=int(r[2]))
        for r in rows
    ]


def _resolve_lineup(
    conn: psycopg.Connection,
    *,
    game_id: int,
    team_id: int,
    is_home: bool,
    as_of: date,
) -> list[LineupHitter]:
    """
    Resolve the batting order to project for one team side.

    Project ONLY a confirmed lineup (game_lineups holds all nine slots), in order, with
    expected PA weighted by lineup position (``PA_BY_ORDER``). If the lineup is not yet
    confirmed, return [] so the caller skips this side: the old L30 "likely hitters" proxy
    guessed both the roster and the order and was unreliable (off-roster names, scrambled
    order), and a wrong projection is worse than none. The afternoon ``daily --quick`` loop
    re-projects as real lineups post.
    """
    rows = conn.execute(
        """
        SELECT gl.batting_order, gl.player_id, COALESCE(p.bats, 'R')
        FROM game_lineups gl
        JOIN players p ON p.id = gl.player_id
        WHERE gl.game_id = %s AND gl.is_home = %s
        ORDER BY gl.batting_order
        """,
        (game_id, is_home),
    ).fetchall()

    if len(rows) == LINEUP_STARTERS:
        return [
            LineupHitter(
                player_id=int(order_pid_bats[1]),
                bats=str(order_pid_bats[2]),
                expected_pa=PA_BY_ORDER[int(order_pid_bats[0])],
                lineup_position=int(order_pid_bats[0]),
                lineup_confirmed=True,
            )
            for order_pid_bats in rows
        ]

    return []


def _load_batter_skill(
    conn: psycopg.Connection, player_id: int
) -> BatterSkillInput | None:
    row = conn.execute(
        """
        SELECT xwoba, xwoba_l30, k_rate, k_rate_l30, iso, iso_l30, pa_l30
        FROM batter_skill
        WHERE player_id = %s
        """,
        (player_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    xwoba = float(row[0])
    k_rate = float(row[2]) if row[2] is not None else 0.0
    iso = float(row[4]) if row[4] is not None else 0.0
    return BatterSkillInput(
        xwoba=xwoba,
        xwoba_l30=float(row[1]) if row[1] is not None else xwoba,
        k_rate=k_rate,
        k_rate_l30=float(row[3]) if row[3] is not None else k_rate,
        iso=iso,
        iso_l30=float(row[5]) if row[5] is not None else iso,
        pa_l30=int(row[6] or 0),
    )


def _park_geometry(game: SlateGame) -> ParkGeometry | None:
    """ParkGeometry for personalization, or None if any fence dimension is absent."""
    dims = (
        game.lf_line_ft, game.cf_ft, game.rf_line_ft,
        game.lf_wall_ft, game.cf_wall_ft, game.rf_wall_ft,
    )
    if any(d is None for d in dims):
        return None
    return ParkGeometry(
        lf_line_ft=float(game.lf_line_ft),
        cf_ft=float(game.cf_ft),
        rf_line_ft=float(game.rf_line_ft),
        lf_wall_ft=float(game.lf_wall_ft),
        cf_wall_ft=float(game.cf_wall_ft),
        rf_wall_ft=float(game.rf_wall_ft),
    )


def _load_batted_ball_profile(
    conn: psycopg.Connection, player_id: int, season: int
) -> BattedBallProfile | None:
    """Per-batter spray + EV profile for park personalization (None if missing)."""
    row = conn.execute(
        """
        SELECT pull_pct, center_pct, oppo_pct, fb_pct, avg_launch_speed
        FROM batter_batted_ball
        WHERE player_id = %s AND season = %s
        """,
        (player_id, season),
    ).fetchone()
    if row is None or any(v is None for v in row):
        return None
    return BattedBallProfile(
        pull_pct=float(row[0]),
        center_pct=float(row[1]),
        oppo_pct=float(row[2]),
        fb_pct=float(row[3]),
        avg_launch_speed=float(row[4]),
    )


def _load_pitcher_splits(
    conn: psycopg.Connection, pitcher_id: int, season: int
) -> list[PitcherHandSplit]:
    rows = conn.execute(
        """
        SELECT vs_handedness, batters_faced, hits_per_pa, hr_per_pa, k_rate
        FROM pitcher_skill
        WHERE player_id = %s AND season = %s
        """,
        (pitcher_id, season),
    ).fetchall()
    splits: list[PitcherHandSplit] = []
    for r in rows:
        if r[2] is None or r[3] is None or r[4] is None:
            continue
        splits.append(
            PitcherHandSplit(
                vs_handedness=str(r[0]),
                batters_faced=int(r[1]),
                hits_per_pa=float(r[2]),
                hr_per_pa=float(r[3]),
                k_rate=float(r[4]),
            )
        )
    return splits


def _load_bullpen_splits(
    conn: psycopg.Connection, team_id: int, season: int
) -> list[PitcherHandSplit]:
    """Load a team's relief-pitching skill (bullpen_skill) as pitcher splits by hand.

    Reuses PitcherHandSplit so the same resolve/adjust path serves starter and bullpen.
    The opposing team's bullpen faces a hitter's later PAs (see expected_team_runs).
    """
    rows = conn.execute(
        """
        SELECT vs_hand, bf, hits_per_pa, hr_per_pa, k_rate
        FROM bullpen_skill
        WHERE team_id = %s AND season = %s
        """,
        (team_id, season),
    ).fetchall()
    splits: list[PitcherHandSplit] = []
    for r in rows:
        if r[2] is None or r[3] is None or r[4] is None:
            continue
        splits.append(
            PitcherHandSplit(
                vs_handedness=str(r[0]),
                batters_faced=int(r[1]),
                hits_per_pa=float(r[2]),
                hr_per_pa=float(r[3]),
                k_rate=float(r[4]),
            )
        )
    return splits


def _load_pitcher_throws(conn: psycopg.Connection, pitcher_id: int) -> str:
    row = conn.execute(
        "SELECT throws FROM players WHERE id = %s",
        (pitcher_id,),
    ).fetchone()
    if row is None or row[0] is None:
        log.warning(
            "pitcher %s missing throws hand; assuming R",
            pitcher_id,
        )
        return "R"
    return str(row[0])


def _effective_bat_side(bats: str, pitcher_throws: str) -> str:
    """Side the batter actually hits from (switch hitters bat opposite the pitcher)."""
    if bats == "S":
        return "L" if pitcher_throws == "R" else "R"
    return bats if bats in ("L", "R") else "R"


def _resolve_matchup(
    conn: psycopg.Connection,
    *,
    batter_id: int,
    bats: str,
    skill: BatterSkillInput,
    pitcher_id: int,
    pitcher_throws: str,
    as_of_date: date,
    season: int,
) -> MatchupResult:
    """Build the pitch-mix matchup for one batter vs the opposing starter.

    v2.1 driver: the resulting xwOBA / k_rate / ISO replace the season blend in
    project_batter (and are stored for audit/UI). The v2.0.0 season/L30 blend is the
    fallback baseline passed as ``overall_*``; compute_matchup returns it verbatim
    (quality='fallback_overall') when arsenal or pitch-type data is too thin.
    """
    overall = blend_batter_skills(skill)
    ov_xwoba, ov_k, ov_iso = overall.xwoba, overall.k_rate, overall.iso
    if PLATOON_ENABLED:
        ov_xwoba, ov_k, ov_iso = _platoon_adjust(
            conn, batter_id, season, pitcher_throws, ov_xwoba, ov_k, ov_iso
        )
    return compute_matchup(
        conn,
        batter_id=batter_id,
        pitcher_id=pitcher_id,
        batter_hand=_effective_bat_side(bats, pitcher_throws),
        pitcher_hand=pitcher_throws,
        as_of_date=as_of_date,
        season=season,
        overall_xwoba=ov_xwoba,
        overall_k_rate=ov_k,
        overall_iso=ov_iso,
    )


def _platoon_adjust(
    conn: psycopg.Connection,
    batter_id: int,
    season: int,
    pitcher_throws: str,
    xwoba: float,
    k_rate: float,
    iso: float,
) -> tuple[float, float, float]:
    """Blend a batter's overall skill toward their split vs the pitcher's throwing hand.

    Weight scales with the split's PA up to PLATOON_WEIGHT_CAP. Returns the inputs
    unchanged when the split is missing or too thin. (Season-aggregate table; not
    point-in-time, so this leaks in backtest — used only as a leak-optimistic screen.)
    """
    if pitcher_throws not in ("L", "R"):
        return xwoba, k_rate, iso
    row = conn.execute(
        """
        SELECT pa, xwoba, k_rate, iso FROM batter_platoon_skill
        WHERE player_id = %s AND season = %s AND vs_hand = %s
        """,
        (batter_id, season, pitcher_throws),
    ).fetchone()
    if row is None or row[0] is None or row[0] < MIN_PLATOON_PA:
        return xwoba, k_rate, iso
    pa, p_xwoba, p_k, p_iso = int(row[0]), row[1], row[2], row[3]
    w = min(pa / PLATOON_FULL_WEIGHT_PA, PLATOON_WEIGHT_CAP)

    def _blend(base: float, split) -> float:
        return base if split is None else (1.0 - w) * base + w * float(split)

    return _blend(xwoba, p_xwoba), _blend(k_rate, p_k), _blend(iso, p_iso)


def _game_ready(game: SlateGame) -> str | None:
    if game.home_probable_pitcher_id is None or game.away_probable_pitcher_id is None:
        return "missing probable pitcher"
    # Weather is an optional refinement, not a requirement: when temp/wind are absent the
    # projector neutralizes them (70°F, no wind). A flaky weather API must NOT zero out the
    # whole slate (this previously returned "missing weather" and skipped every open-air game).
    # Matches _game_ready_backtest, which already gates only on probable pitchers.
    return None


def _upsert_batter_projection(
    conn: psycopg.Connection,
    game_id: int,
    player_id: int,
    opposing_pitcher_id: int,
    is_home: bool,
    proj,
    pitcher_data_quality: str,
    lineup_position: int | None,
    lineup_confirmed: bool,
    matchup_xwoba: float | None,
    matchup_quality: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO batter_projections (
            game_id, player_id, opposing_pitcher_id, is_home,
            expected_pa,
            p_hit_1plus, p_hit_2plus, p_hr, p_k_1plus,
            expected_hits, expected_total_bases,
            adj_park, adj_pitcher, adj_weather_hr, adj_weather_hits,
            pitcher_data_quality,
            lineup_position, lineup_confirmed,
            matchup_xwoba, matchup_quality,
            computed_at
        )
        VALUES (
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            %s,
            %s, %s,
            %s, %s,
            NOW()
        )
        ON CONFLICT (game_id, player_id) DO UPDATE SET
            opposing_pitcher_id   = EXCLUDED.opposing_pitcher_id,
            is_home               = EXCLUDED.is_home,
            expected_pa           = EXCLUDED.expected_pa,
            p_hit_1plus           = EXCLUDED.p_hit_1plus,
            p_hit_2plus           = EXCLUDED.p_hit_2plus,
            p_hr                  = EXCLUDED.p_hr,
            p_k_1plus             = EXCLUDED.p_k_1plus,
            expected_hits         = EXCLUDED.expected_hits,
            expected_total_bases  = EXCLUDED.expected_total_bases,
            adj_park              = EXCLUDED.adj_park,
            adj_pitcher           = EXCLUDED.adj_pitcher,
            adj_weather_hr        = EXCLUDED.adj_weather_hr,
            adj_weather_hits      = EXCLUDED.adj_weather_hits,
            pitcher_data_quality  = EXCLUDED.pitcher_data_quality,
            lineup_position       = EXCLUDED.lineup_position,
            lineup_confirmed      = EXCLUDED.lineup_confirmed,
            matchup_xwoba         = EXCLUDED.matchup_xwoba,
            matchup_quality       = EXCLUDED.matchup_quality,
            computed_at           = NOW()
        """,
        (
            game_id,
            player_id,
            opposing_pitcher_id,
            is_home,
            round(proj.expected_pa, 2),
            proj.probabilities.p_hit_1plus,
            proj.probabilities.p_hit_2plus,
            proj.probabilities.p_hr,
            proj.probabilities.p_k_1plus,
            round(proj.expected_hits, 3),
            round(proj.expected_total_bases, 3),
            round(proj.adj_park_hit, 3),
            round(proj.adj_pitcher_hit, 3),
            round(proj.adj_weather_hr, 3),
            round(proj.adj_weather_hit, 3),
            pitcher_data_quality,
            lineup_position,
            lineup_confirmed,
            matchup_xwoba,
            matchup_quality,
        ),
    )


def _pad_confirmed_projs(
    starter_projs: list[BatterProjection],
    lineup_confirmed: bool,
    bullpen_projs: list[BatterProjection] | None = None,
) -> None:
    """
    Backfill the team-run inputs to nine slots for a confirmed lineup (in place).

    A confirmed lineup is exactly nine batters; if one lacks batter_skill we still want
    a run projection rather than dropping the whole game. Pad the missing slots with a
    league-average projection so ``expected_team_runs`` sees nine batters. Individual
    batter rows are unaffected — only batters we could actually project were written.
    No-op for the projected fallback, which has bench-depth slack.
    """
    if not lineup_confirmed:
        return
    if not (0 < len(starter_projs) < LINEUP_STARTERS):
        return
    pad = LINEUP_STARTERS - len(starter_projs)
    starter_projs.extend(
        league_average_projection(EXPECTED_PA_PER_STARTER) for _ in range(pad)
    )
    if bullpen_projs is not None:
        bullpen_projs.extend(
            league_average_projection(EXPECTED_PA_PER_STARTER) for _ in range(pad)
        )


def _project_team_side(
    conn: psycopg.Connection,
    *,
    game: SlateGame,
    team_id: int,
    opposing_pitcher_id: int,
    opposing_team_id: int,
    is_home: bool,
    season: int,
    park: ParkFactors,
    summary: ProjectSummary,
    bundle=None,
) -> TeamSideProjection | None:
    """Project hitters for one team; return expected runs + lineups, or None if insufficient data."""
    hitters = _resolve_lineup(
        conn, game_id=game.game_id, team_id=team_id, is_home=is_home, as_of=summary.game_date
    )
    if len(hitters) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d hitters available (need %d)",
            game.game_id,
            team_id,
            len(hitters),
            LINEUP_STARTERS,
        )
        return None

    lineup_confirmed = hitters[0].lineup_confirmed  # confirmation is per-side, all-or-nothing

    pitcher_throws = _load_pitcher_throws(conn, opposing_pitcher_id)

    splits = _load_pitcher_splits(conn, opposing_pitcher_id, season)
    if not splits:
        log.info(
            "game %s: no pitcher_skill for pitcher %s — using league-avg fallback",
            game.game_id,
            opposing_pitcher_id,
        )

    # v2.2: the opposing team's bullpen faces a hitter's later PAs (blended in
    # expected_team_runs). Empty → resolve_pitcher_skill yields the league-average
    # pitcher, so the bullpen-faced leg simply regresses the matchup toward league.
    bullpen_splits = _load_bullpen_splits(conn, opposing_team_id, season)

    # v1: retractable domes assumed closed (no open/closed flag on games yet).
    is_retractable_open = False

    starter_projs: list[BatterProjection] = []
    bullpen_projs: list[BatterProjection] = []

    for hitter in hitters:
        skill = _load_batter_skill(conn, hitter.player_id)
        if skill is None:
            log.warning(
                "game %s: skip batter %s — no batter_skill",
                game.game_id,
                hitter.player_id,
            )
            continue

        pitcher_split, pitcher_quality = resolve_pitcher_skill(
            splits, hitter.bats, pitcher_throws
        )
        bb_profile = _load_batted_ball_profile(conn, hitter.player_id, season)
        park_adj = compute_park_adjustments(
            park, hitter.bats, pitcher_throws, profile=bb_profile
        )
        pitcher_adj = compute_pitcher_adjustments(pitcher_split)
        # Hit side keeps the temperature scalar (and dome handling); the HR side is the
        # v2.6 trajectory model: weather shifts fly-ball carry, and the HR effect is the
        # change in P(clear the fence) for THIS batter (own profile, else league-average).
        adj_weather_hit, _ = compute_weather_adjustments(
            temperature_f=game.temperature_f or 70.0,
            wind_speed_mph=game.wind_speed_mph or 0.0,
            wind_from_degrees=game.wind_from_degrees or 0.0,
            cf_bearing_degrees=game.cf_bearing_degrees,
            bats=hitter.bats,
            pitcher_throws=pitcher_throws,
            is_dome=game.is_dome,
            is_retractable_open=is_retractable_open,
            humidity_pct=game.relative_humidity_pct,
            surface_pressure_hpa=game.surface_pressure_hpa,
            altitude_ft=game.altitude_feet,
        )
        d_carry = carry_delta_ft(
            temperature_f=game.temperature_f or 70.0,
            wind_speed_mph=game.wind_speed_mph or 0.0,
            wind_from_degrees=game.wind_from_degrees or 0.0,
            cf_bearing_degrees=game.cf_bearing_degrees,
            bats=hitter.bats,
            pitcher_throws=pitcher_throws,
            is_dome=game.is_dome,
            is_retractable_open=is_retractable_open,
            humidity_pct=game.relative_humidity_pct,
            surface_pressure_hpa=game.surface_pressure_hpa,
            altitude_ft=game.altitude_feet,
        )
        adj_weather_hr = weather_carry_hr_mult(
            park.geometry,
            bb_profile if bb_profile is not None else LEAGUE_AVERAGE_PROFILE,
            _effective_bat_side(hitter.bats, pitcher_throws),
            d_carry,
        )

        # v2.1: the matchup drives the batter's hit/K/HR rates and is stored for audit/UI.
        matchup = _resolve_matchup(
            conn,
            batter_id=hitter.player_id,
            bats=hitter.bats,
            skill=skill,
            pitcher_id=opposing_pitcher_id,
            pitcher_throws=pitcher_throws,
            as_of_date=summary.game_date,
            season=season,
        )

        proj = project_batter(
            skill,
            pitcher_adj,
            park_adj,
            adj_weather_hit,
            adj_weather_hr,
            expected_pa=hitter.expected_pa,
            matchup_xwoba=matchup.xwoba,
            matchup_k_rate=matchup.k_rate,
            matchup_iso=matchup.iso,
        )
        if bundle is not None:
            proj = _xgb_apply(
                conn, hitter=hitter, opposing_pitcher_id=opposing_pitcher_id,
                pitcher_throws=pitcher_throws, is_home=is_home, park=park,
                as_of_date=summary.game_date, season=season, bundle=bundle, proj=proj,
            )
        proj = _maybe_calibrate(proj)
        _upsert_batter_projection(
            conn,
            game.game_id,
            hitter.player_id,
            opposing_pitcher_id,
            is_home,
            proj,
            pitcher_quality,
            hitter.lineup_position,
            hitter.lineup_confirmed,
            matchup.xwoba,
            matchup.quality,
        )
        summary.batter_rows += 1

        if len(starter_projs) < LINEUP_STARTERS:
            starter_projs.append(proj)
            # Same batter (matchup-based skill), re-projected against the opposing
            # bullpen's pitcher quality — only the pitcher adjustment changes.
            pen_split, _pen_quality = resolve_pitcher_skill(
                bullpen_splits, hitter.bats, pitcher_throws
            )
            pen_adj = compute_pitcher_adjustments(pen_split)
            bullpen_projs.append(
                project_batter(
                    skill,
                    pen_adj,
                    park_adj,
                    adj_weather_hit,
                    adj_weather_hr,
                    expected_pa=hitter.expected_pa,
                    matchup_xwoba=matchup.xwoba,
                    matchup_k_rate=matchup.k_rate,
                    matchup_iso=matchup.iso,
                )
            )

    _pad_confirmed_projs(starter_projs, lineup_confirmed, bullpen_projs)

    if len(starter_projs) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d batters projected (need %d for team runs)",
            game.game_id,
            team_id,
            len(starter_projs),
            LINEUP_STARTERS,
        )
        return None

    # The opposing starter's projected line is the aggregate of this lineup vs him.
    # His team is the other side, so is_home flips.
    _upsert_pitcher_projection(
        conn,
        game.game_id,
        opposing_pitcher_id,
        not is_home,
        pitcher_line_from_lineup(starter_projs),
    )

    return TeamSideProjection(
        expected_runs=expected_team_runs(starter_projs, bullpen_projs),
        starter_projs=starter_projs,
        bullpen_projs=bullpen_projs,
    )


def _upsert_pitcher_projection(
    conn: psycopg.Connection,
    game_id: int,
    pitcher_id: int,
    is_home: bool,
    line,
) -> None:
    conn.execute(
        """
        INSERT INTO pitcher_projections (
            game_id, pitcher_id, is_home, expected_bf, expected_outs, expected_ip,
            expected_k, expected_h, expected_hr, expected_bb, expected_runs, computed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (game_id, pitcher_id) DO UPDATE SET
            is_home       = EXCLUDED.is_home,
            expected_bf   = EXCLUDED.expected_bf,
            expected_outs = EXCLUDED.expected_outs,
            expected_ip   = EXCLUDED.expected_ip,
            expected_k    = EXCLUDED.expected_k,
            expected_h    = EXCLUDED.expected_h,
            expected_hr   = EXCLUDED.expected_hr,
            expected_bb   = EXCLUDED.expected_bb,
            expected_runs = EXCLUDED.expected_runs,
            computed_at   = NOW()
        """,
        (
            game_id, pitcher_id, is_home,
            round(line.expected_bf, 2), round(line.expected_outs, 2), round(line.expected_ip, 2),
            round(line.expected_k, 2), round(line.expected_h, 2), round(line.expected_hr, 2),
            round(line.expected_bb, 2), round(line.expected_runs, 2),
        ),
    )


def _project_game(
    conn: psycopg.Connection,
    game: SlateGame,
    season: int,
    summary: ProjectSummary,
    bundle=None,
) -> bool:
    reason = _game_ready(game)
    if reason:
        summary.skip_reasons.append(f"game {game.game_id}: {reason}")
        return False

    park = ParkFactors(
        park_factor_hits=game.park_factor_hits,
        park_factor_hr_lhb=game.park_factor_hr_lhb,
        park_factor_hr_rhb=game.park_factor_hr_rhb,
        geometry=_park_geometry(game),
    )

    home = _project_team_side(
        conn,
        game=game,
        team_id=game.home_team_id,
        opposing_pitcher_id=game.away_probable_pitcher_id,
        opposing_team_id=game.away_team_id,
        is_home=True,
        season=season,
        park=park,
        summary=summary,
        bundle=bundle,
    )
    away = _project_team_side(
        conn,
        game=game,
        team_id=game.away_team_id,
        opposing_pitcher_id=game.home_probable_pitcher_id,
        opposing_team_id=game.home_team_id,
        is_home=False,
        season=season,
        park=park,
        summary=summary,
        bundle=bundle,
    )
    if home is None or away is None:
        summary.skip_reasons.append(
            f"game {game.game_id}: incomplete team projection"
        )
        return False

    home_runs = home.expected_runs
    away_runs = away.expected_runs
    p_yrfi, efir = yrfi_probability(home_runs, away_runs)
    conn.execute(
        """
        INSERT INTO game_projections (
            game_id, expected_home_runs, expected_away_runs,
            expected_total_runs, p_yrfi, expected_first_inning_runs, computed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (game_id) DO UPDATE SET
            expected_home_runs  = EXCLUDED.expected_home_runs,
            expected_away_runs  = EXCLUDED.expected_away_runs,
            expected_total_runs = EXCLUDED.expected_total_runs,
            p_yrfi              = EXCLUDED.p_yrfi,
            expected_first_inning_runs = EXCLUDED.expected_first_inning_runs,
            computed_at         = NOW()
        """,
        (
            game.game_id,
            round(home_runs, 2),
            round(away_runs, 2),
            round(home_runs + away_runs, 2),
            round(p_yrfi, 3),
            round(efir, 2),
        ),
    )

    # Unified Monte-Carlo sim: full-game (starter -> bullpen after the 5th) plus the
    # starter-driven first-N-innings markets (F1/F5). Seeded by game_id for repeatability.
    sim = simulate_game(
        home.starter_projs,
        away.starter_projs,
        n_sims=SIM_N_SIMS,
        seed=int(game.game_id),
        home_bullpen=home.bullpen_projs,
        away_bullpen=away.bullpen_projs,
    )
    _upsert_game_sim_projection(conn, game.game_id, sim)

    conn.execute(
        "UPDATE games SET projected_at = NOW() WHERE id = %s",
        (game.game_id,),
    )
    return True


def _upsert_game_sim_projection(
    conn: psycopg.Connection, game_id: int, sim: GameSim
) -> None:
    """Persist the Monte-Carlo sim's distributional outputs for one game."""
    full = sim.full
    f5 = sim.f5
    conn.execute(
        """
        INSERT INTO game_sim_projections (
            game_id, n_sims,
            expected_home_runs, expected_away_runs, expected_total, p_home_win, total_hist,
            f5_expected_home, f5_expected_away, f5_expected_total,
            f5_p_home_lead, f5_p_away_lead, f5_p_tie, f5_total_hist,
            p_yrfi, computed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (game_id) DO UPDATE SET
            n_sims             = EXCLUDED.n_sims,
            expected_home_runs = EXCLUDED.expected_home_runs,
            expected_away_runs = EXCLUDED.expected_away_runs,
            expected_total     = EXCLUDED.expected_total,
            p_home_win         = EXCLUDED.p_home_win,
            total_hist         = EXCLUDED.total_hist,
            f5_expected_home   = EXCLUDED.f5_expected_home,
            f5_expected_away   = EXCLUDED.f5_expected_away,
            f5_expected_total  = EXCLUDED.f5_expected_total,
            f5_p_home_lead     = EXCLUDED.f5_p_home_lead,
            f5_p_away_lead     = EXCLUDED.f5_p_away_lead,
            f5_p_tie           = EXCLUDED.f5_p_tie,
            f5_total_hist      = EXCLUDED.f5_total_hist,
            p_yrfi             = EXCLUDED.p_yrfi,
            computed_at        = NOW()
        """,
        (
            game_id,
            sim.n_sims,
            round(full.expected_home, 2),
            round(full.expected_away, 2),
            round(full.expected_total, 2),
            round(sim.p_home_win, 3),
            full.total_hist(SIM_FULL_HIST_MAX),
            round(f5.expected_home, 2),
            round(f5.expected_away, 2),
            round(f5.expected_total, 2),
            round(f5.p_home_lead, 3),
            round(f5.p_away_lead, 3),
            round(f5.p_tie, 3),
            f5.total_hist(SIM_F5_HIST_MAX),
            round(sim.p_yrfi, 3),
        ),
    )


def _clear_slate_projections(conn: psycopg.Connection, game_date: date) -> int:
    """
    Drop projections for the slate date and any earlier date before recomputing.

    The write path has no DELETE, so batter_projections / game_projections rows from
    prior days pile up: each day's slate has fresh game_ids, so the (game_id, player_id)
    PK never collides and old rows are never overwritten. A player then appears once per
    past day in any cross-day query — the "duplicate rows" bug. We recompute the entire
    slate from scratch on every run, so it is safe to clear:

      * the current date — makes re-runs idempotent and drops a batter who fell out of a
        (now confirmed) lineup, and
      * strictly-earlier dates — phases out the accumulated stale rows.

    Future-dated projections, if any were ever written, are left untouched. Returns the
    number of batter_projections rows removed (for logging).
    """
    deleted = conn.execute(
        """
        DELETE FROM batter_projections
        WHERE game_id IN (SELECT id FROM games WHERE game_date <= %s)
        """,
        (game_date,),
    ).rowcount
    conn.execute(
        """
        DELETE FROM game_projections
        WHERE game_id IN (SELECT id FROM games WHERE game_date <= %s)
        """,
        (game_date,),
    )
    conn.execute(
        """
        DELETE FROM pitcher_projections
        WHERE game_id IN (SELECT id FROM games WHERE game_date <= %s)
        """,
        (game_date,),
    )
    conn.execute(
        """
        DELETE FROM game_sim_projections
        WHERE game_id IN (SELECT id FROM games WHERE game_date <= %s)
        """,
        (game_date,),
    )
    return deleted


def run_projections(
    conn: psycopg.Connection, game_date: date, bundle=None
) -> ProjectSummary:
    summary = ProjectSummary(game_date=game_date)
    season = infer_season(game_date)
    games = _load_slate_games(conn, game_date)
    summary.games_seen = len(games)

    if not games:
        log.info("no games on slate for %s", game_date)
        return summary

    # Clear stale + current-slate rows up front so the live table only ever holds the
    # slate we are about to (re)compute. Only runs once we know the slate is non-empty,
    # so an empty/failed slate fetch can't wipe a previously good day. See PART A.
    cleared = _clear_slate_projections(conn, game_date)
    if cleared:
        log.info("cleared %d stale/prior batter_projection row(s) before recompute", cleared)

    for game in games:
        if _project_game(conn, game, season, summary, bundle=bundle):
            summary.games_projected += 1
        else:
            summary.games_skipped += 1

    return summary


# ---------------------------------------------------------------------------
# Backtest projection mode (project --as-of YYYY-MM-DD)
# Reads from *_snapshots tables; writes to backtest_projections.
# Kept intentionally separate from the prod codepath above.
# ---------------------------------------------------------------------------

def _load_batter_skill_snapshot(
    conn: psycopg.Connection,
    player_id: int,
    as_of_date: date,
) -> BatterSkillInput | None:
    """Read the most recent batter_skill_snapshot with as_of_date <= as_of_date."""
    row = conn.execute(
        """
        SELECT xwoba, xwoba_l30, k_rate, k_rate_l30, iso, iso_l30, pa_l30
        FROM batter_skill_snapshots
        WHERE player_id = %s AND as_of_date <= %s
        ORDER BY as_of_date DESC
        LIMIT 1
        """,
        (player_id, as_of_date),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    xwoba = float(row[0])
    k_rate = float(row[2]) if row[2] is not None else 0.0
    iso = float(row[4]) if row[4] is not None else 0.0
    return BatterSkillInput(
        xwoba=xwoba,
        xwoba_l30=float(row[1]) if row[1] is not None else xwoba,
        k_rate=k_rate,
        k_rate_l30=float(row[3]) if row[3] is not None else k_rate,
        iso=iso,
        iso_l30=float(row[5]) if row[5] is not None else iso,
        pa_l30=int(row[6] or 0),
    )


def _load_pitcher_splits_snapshot(
    conn: psycopg.Connection,
    pitcher_id: int,
    season: int,
    as_of_date: date,
) -> list[PitcherHandSplit]:
    """Read pitcher splits from the most recent snapshot with as_of_date <= as_of_date."""
    rows = conn.execute(
        """
        SELECT vs_handedness, batters_faced, hits_per_pa, hr_per_pa, k_rate
        FROM pitcher_skill_snapshots
        WHERE player_id = %s
          AND season = %s
          AND as_of_date = (
              SELECT MAX(as_of_date)
              FROM pitcher_skill_snapshots
              WHERE player_id = %s AND season = %s AND as_of_date <= %s
          )
        """,
        (pitcher_id, season, pitcher_id, season, as_of_date),
    ).fetchall()
    splits: list[PitcherHandSplit] = []
    for r in rows:
        if r[2] is None or r[3] is None or r[4] is None:
            continue
        splits.append(
            PitcherHandSplit(
                vs_handedness=str(r[0]),
                batters_faced=int(r[1]),
                hits_per_pa=float(r[2]),
                hr_per_pa=float(r[3]),
                k_rate=float(r[4]),
            )
        )
    return splits


def _upsert_backtest_projection(
    conn: psycopg.Connection,
    backtest_run_id: int,
    game_id: int,
    player_id: int,
    as_of_date: date,
    proj,
    matchup_xwoba: float | None = None,
    matchup_quality: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO backtest_projections (
            backtest_run_id, game_id, player_id, as_of_date,
            expected_pa,
            p_hit_1plus, p_hit_2plus, p_hr, p_k_1plus,
            expected_hits, expected_total_bases,
            matchup_xwoba, matchup_quality
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (backtest_run_id, game_id, player_id) DO UPDATE SET
            as_of_date           = EXCLUDED.as_of_date,
            expected_pa          = EXCLUDED.expected_pa,
            p_hit_1plus          = EXCLUDED.p_hit_1plus,
            p_hit_2plus          = EXCLUDED.p_hit_2plus,
            p_hr                 = EXCLUDED.p_hr,
            p_k_1plus            = EXCLUDED.p_k_1plus,
            expected_hits        = EXCLUDED.expected_hits,
            expected_total_bases = EXCLUDED.expected_total_bases,
            matchup_xwoba        = EXCLUDED.matchup_xwoba,
            matchup_quality      = EXCLUDED.matchup_quality
        """,
        (
            backtest_run_id,
            game_id,
            player_id,
            as_of_date,
            round(proj.expected_pa, 2),
            proj.probabilities.p_hit_1plus,
            proj.probabilities.p_hit_2plus,
            proj.probabilities.p_hr,
            proj.probabilities.p_k_1plus,
            round(proj.expected_hits, 3),
            round(proj.expected_total_bases, 3),
            matchup_xwoba,
            matchup_quality,
        ),
    )


def _game_ready_backtest(game: SlateGame) -> str | None:
    """Backtest skip check: only gate on missing probable pitchers, not weather."""
    if game.home_probable_pitcher_id is None or game.away_probable_pitcher_id is None:
        return "missing probable pitcher"
    return None


# Neutral multiplier applied when weather is skipped (historical/stale games).
_NEUTRAL_WEATHER_ADJ = 1.0


def _backtest_weather_skipped(game: SlateGame, game_date: date) -> bool:
    """
    Decide whether to skip weather adjustments for a backtested game.

    Skip weather only when the game has no stored snapshot at all. Backfilled games
    carry ACTUAL historical conditions (backfill-weather, Open-Meteo archive), so the
    old "more than a day in the past" guard — meant for stale live forecasts — no longer
    applies: real archive weather is exactly what happened and should be scored.
    """
    return game.weather_fetched_at is None


def _xgb_apply(
    conn, *, hitter, opposing_pitcher_id, pitcher_throws, is_home, park, as_of_date, season, bundle, proj
):
    """Score one hitter with the saved models and return an updated projection.

    Builds the feature row ONCE, replaces the four market probabilities (blended with the
    mechanistic probs when bundle.blend is set), and — when count regressors are loaded —
    the expected hits / total bases. Returns proj unchanged when no feature row can be
    built (sub-threshold batter) so it falls back to the mechanistic projection.
    """
    from ingester.ml.features import build_feature_row  # lazy: keeps xgboost off the default path

    feat = build_feature_row(
        conn, batter_id=hitter.player_id, bats=hitter.bats,
        opposing_pitcher_id=opposing_pitcher_id, pitcher_throws=pitcher_throws,
        lineup_position=hitter.lineup_position, is_home=is_home, park=park,
        as_of_date=as_of_date, season=season,
    )
    if feat is None:
        return proj
    p = bundle.predict(feat)
    xprobs = BatterProbabilities(
        p_hit_1plus=round(p["h1"], 4), p_hit_2plus=round(p["h2"], 4),
        p_hr=round(p["hr"], 4), p_k_1plus=round(p["k"], 4),
    )
    if bundle.blend is not None:
        xprobs = _blend_probabilities(proj.probabilities, xprobs, bundle.blend)
    updated = {"probabilities": xprobs}
    counts = bundle.predict_counts(feat)
    if counts is not None:
        updated["expected_hits"] = round(max(counts["exp_hits"], 0.0), 3)
        updated["expected_total_bases"] = round(max(counts["exp_tb"], 0.0), 3)
    return replace(proj, **updated)


def _blend_probabilities(
    mech: BatterProbabilities, xgb: BatterProbabilities, weights: dict
) -> BatterProbabilities:
    """Per-market w*p_mech + (1-w)*p_xgb (w = weight on mechanistic)."""
    def b(market, m, x):
        w = float(weights.get(market, 0.5))
        return round(w * m + (1.0 - w) * x, 4)
    return BatterProbabilities(
        p_hit_1plus=b("h1", mech.p_hit_1plus, xgb.p_hit_1plus),
        p_hit_2plus=b("h2", mech.p_hit_2plus, xgb.p_hit_2plus),
        p_hr=b("hr", mech.p_hr, xgb.p_hr),
        p_k_1plus=b("k", mech.p_k_1plus, xgb.p_k_1plus),
    )


def _project_team_side_backtest(
    conn: psycopg.Connection,
    *,
    game: SlateGame,
    team_id: int,
    opposing_pitcher_id: int,
    is_home: bool,
    season: int,
    park: ParkFactors,
    as_of_date: date,
    backtest_run_id: int,
    summary: ProjectSummary,
    bundle=None,
) -> float | None:
    """Project one team side using snapshot skill tables; return expected_team_runs or None."""
    hitters = _resolve_lineup(
        conn, game_id=game.game_id, team_id=team_id, is_home=is_home, as_of=summary.game_date
    )
    if len(hitters) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d hitters available (need %d)",
            game.game_id, team_id, len(hitters), LINEUP_STARTERS,
        )
        return None

    lineup_confirmed = hitters[0].lineup_confirmed

    pitcher_throws = _load_pitcher_throws(conn, opposing_pitcher_id)
    splits = _load_pitcher_splits_snapshot(conn, opposing_pitcher_id, season, as_of_date)

    is_retractable_open = False
    starter_projs: list[BatterProjection] = []
    # No bullpen leg in backtest: bullpen_skill is a full-season aggregate, so using
    # it for a historical game would leak future data. The team-run formula change
    # (linear weights vs the v1 Pythagorean) is what this backtest measures.

    # Historical/stale games have no usable weather snapshot — neutralize weather so
    # the backtest measures only park + pitcher + skill. Decided once per game side.
    weather_skipped = _backtest_weather_skipped(game, summary.game_date)

    for hitter in hitters:
        skill = _load_batter_skill_snapshot(conn, hitter.player_id, as_of_date)
        if skill is None:
            log.warning(
                "game %s: skip batter %s — no batter_skill snapshot as of %s",
                game.game_id, hitter.player_id, as_of_date,
            )
            continue

        pitcher_split, _quality = resolve_pitcher_skill(splits, hitter.bats, pitcher_throws)
        # Leak-free park personalization for the A/B: prior-season batted-ball profile.
        bb_profile = (
            _load_batted_ball_profile(conn, hitter.player_id, season - 1)
            if _BACKTEST_PARK_PERSONALIZED
            else None
        )
        park_adj = compute_park_adjustments(
            park, hitter.bats, pitcher_throws, profile=bb_profile
        )
        pitcher_adj = compute_pitcher_adjustments(pitcher_split)
        if weather_skipped:
            adj_weather_hit = _NEUTRAL_WEATHER_ADJ
            adj_weather_hr = _NEUTRAL_WEATHER_ADJ
        else:
            adj_weather_hit, adj_weather_hr = compute_weather_adjustments(
                temperature_f=game.temperature_f or 70.0,
                wind_speed_mph=game.wind_speed_mph or 0.0,
                wind_from_degrees=game.wind_from_degrees or 0.0,
                cf_bearing_degrees=game.cf_bearing_degrees,
                bats=hitter.bats,
                pitcher_throws=pitcher_throws,
                is_dome=game.is_dome,
                is_retractable_open=is_retractable_open,
                humidity_pct=game.relative_humidity_pct,
                surface_pressure_hpa=game.surface_pressure_hpa,
                altitude_ft=game.altitude_feet,
            )

        # v2.1: the matchup drives the projection; store it so the backtest is auditable.
        matchup = _resolve_matchup(
            conn,
            batter_id=hitter.player_id,
            bats=hitter.bats,
            skill=skill,
            pitcher_id=opposing_pitcher_id,
            pitcher_throws=pitcher_throws,
            as_of_date=as_of_date,
            season=season,
        )

        proj = project_batter(
            skill, pitcher_adj, park_adj, adj_weather_hit, adj_weather_hr,
            expected_pa=hitter.expected_pa,
            matchup_xwoba=matchup.xwoba,
            matchup_k_rate=matchup.k_rate,
            matchup_iso=matchup.iso,
        )
        if bundle is not None:
            # Replace the four market probabilities (blended with mechanistic when
            # bundle.blend is set) and, if regressors are loaded, expected hits/TB.
            # Falls back per-batter when no feature row could be built.
            proj = _xgb_apply(
                conn, hitter=hitter, opposing_pitcher_id=opposing_pitcher_id,
                pitcher_throws=pitcher_throws, is_home=is_home, park=park,
                as_of_date=as_of_date, season=season, bundle=bundle, proj=proj,
            )
        proj = _maybe_calibrate(proj)
        _upsert_backtest_projection(
            conn, backtest_run_id, game.game_id, hitter.player_id, as_of_date, proj,
            matchup.xwoba, matchup.quality,
        )
        summary.batter_rows += 1

        if len(starter_projs) < LINEUP_STARTERS:
            starter_projs.append(proj)

    _pad_confirmed_projs(starter_projs, lineup_confirmed)

    if len(starter_projs) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d batters projected (need %d for team runs)",
            game.game_id, team_id, len(starter_projs), LINEUP_STARTERS,
        )
        return None

    return expected_team_runs(starter_projs)


def _project_game_backtest(
    conn: psycopg.Connection,
    game: SlateGame,
    season: int,
    as_of_date: date,
    backtest_run_id: int,
    summary: ProjectSummary,
    bundle=None,
) -> bool:
    reason = _game_ready_backtest(game)
    if reason:
        summary.skip_reasons.append(f"game {game.game_id}: {reason}")
        return False

    park = ParkFactors(
        park_factor_hits=game.park_factor_hits,
        park_factor_hr_lhb=game.park_factor_hr_lhb,
        park_factor_hr_rhb=game.park_factor_hr_rhb,
        geometry=_park_geometry(game),
    )

    home_runs = _project_team_side_backtest(
        conn, game=game, team_id=game.home_team_id,
        opposing_pitcher_id=game.away_probable_pitcher_id,
        is_home=True, season=season, park=park,
        as_of_date=as_of_date, backtest_run_id=backtest_run_id, summary=summary, bundle=bundle,
    )
    away_runs = _project_team_side_backtest(
        conn, game=game, team_id=game.away_team_id,
        opposing_pitcher_id=game.home_probable_pitcher_id,
        is_home=False, season=season, park=park,
        as_of_date=as_of_date, backtest_run_id=backtest_run_id, summary=summary, bundle=bundle,
    )
    if home_runs is None or away_runs is None:
        summary.skip_reasons.append(f"game {game.game_id}: incomplete team projection")
        return False

    # Persist the predicted game total so the harness can score run accuracy vs the
    # final score (backtest_game_runs). Per-batter rows already went to backtest_projections.
    conn.execute(
        """
        INSERT INTO backtest_game_runs (backtest_run_id, game_id, expected_total_runs)
        VALUES (%s, %s, %s)
        ON CONFLICT (backtest_run_id, game_id)
            DO UPDATE SET expected_total_runs = EXCLUDED.expected_total_runs
        """,
        (backtest_run_id, game.game_id, round(home_runs + away_runs, 2)),
    )
    return True


def run_backtest_projections(
    conn: psycopg.Connection,
    game_date: date,
    as_of_date: date,
    backtest_run_id: int | None = None,
    bundle=None,
) -> ProjectSummary:
    """
    Project a historical game_date using skill snapshots as of as_of_date.
    Writes to backtest_projections; never touches batter_projections.

    backtest_run_id: must be a valid backtest_runs.id after V7 migration.
    When None, a date-derived surrogate is used (pre-V7 compatibility only).
    bundle: a loaded ml.infer.ModelBundle to score the four markets with XGBoost
    instead of the mechanistic probabilities (None = mechanistic).
    """
    summary = ProjectSummary(game_date=game_date)
    season = infer_season(game_date)
    games = _load_slate_games(conn, game_date)
    summary.games_seen = len(games)

    if backtest_run_id is None:
        # Surrogate for ad-hoc usage; breaks after V7 adds the FK.
        backtest_run_id = int(as_of_date.strftime("%Y%m%d"))

    if not games:
        log.info("no games on slate for %s", game_date)
        return summary

    for game in games:
        if _project_game_backtest(conn, game, season, as_of_date, backtest_run_id, summary, bundle=bundle):
            summary.games_projected += 1
        else:
            summary.games_skipped += 1

    return summary


def create_adhoc_backtest_run(
    conn: psycopg.Connection,
    game_date: date,
    as_of_date: date,
) -> int:
    """
    Insert a minimal backtest_runs row for an ad-hoc 'project --as-of' call.
    Returns the new run id.
    """
    row = conn.execute(
        """
        INSERT INTO backtest_runs (
            range_start, range_end, model_version, model_constants, notes
        )
        VALUES (%s, %s, %s, %s::jsonb, 'ad-hoc via project --as-of')
        RETURNING id
        """,
        (game_date, game_date, MODEL_VERSION, json.dumps({})),
    ).fetchone()
    conn.commit()
    return int(row[0])


def cmd_project(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    game_date = args.date if args.date is not None else eastern_today()
    as_of_date: date | None = getattr(args, "as_of", None)
    model: str = getattr(args, "model", "mechanistic")

    bundle = None
    if model in ("xgb", "blend"):
        from ingester.ml.infer import ModelBundle  # lazy: keeps xgboost off the default path
        bundle = ModelBundle.load(blend=(model == "blend"))
        if bundle is None:
            # Production must never hard-fail on missing (git-ignored) artifacts.
            need = "train-xgb --target all --save" + (" then tune-blend" if model == "blend" else "")
            print(f"[project] WARNING: --model {model} requested but models/weights missing "
                  f"(run {need}); falling back to mechanistic.")
            model = "mechanistic"

    # S3: close the accuracy loop — apply per-market calibration by default when a
    # fitted map exists (safe no-op if missing). --no-calibrate opts out.
    if not getattr(args, "no_calibrate", False):
        cal = Calibrator.load(getattr(args, "models_dir", None) and f"{args.models_dir}/calibration.json")
        if cal is not None:
            set_calibrator(cal)
            print("[project] Calibration: ON (models/calibration.json)")

    if as_of_date is not None:
        print(
            f"[project] Backtest mode: game_date={game_date}, as_of={as_of_date} "
            f"(writes to backtest_projections)"
        )
        conn = get_connection()
        try:
            run_id = create_adhoc_backtest_run(conn, game_date, as_of_date)
            summary = run_backtest_projections(conn, game_date, as_of_date, run_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        print(f"[project] Backtest run_id={run_id}")
    else:
        print(f"[project] Computing projections for {game_date} (model={model})…")
        conn = get_connection()
        try:
            summary = run_projections(conn, game_date, bundle=bundle)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    print(
        f"[project] Slate: {summary.games_seen} game(s) — "
        f"{summary.games_projected} projected, "
        f"{summary.games_skipped} skipped, "
        f"{summary.batter_rows} batter row(s)"
    )
    for reason in summary.skip_reasons:
        print(f"  skip: {reason}")


@dataclass
class ProjectionVerifyResult:
    slate_hitter_count: int
    projectable_hitter_count: int
    batter_projection_rows: int
    game_projection_rows: int
    per_game: list[tuple[int, int, int]]  # game_id, expected, actual


def count_batter_projections(conn: psycopg.Connection, game_date: date) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM batter_projections bp
        JOIN games g ON g.id = bp.game_id
        WHERE g.game_date = %s
        """,
        (game_date,),
    ).fetchone()
    return int(row[0])


def count_game_projections(conn: psycopg.Connection, game_date: date) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM game_projections gp
        JOIN games g ON g.id = gp.game_id
        WHERE g.game_date = %s
        """,
        (game_date,),
    ).fetchone()
    return int(row[0])


def verify_projection_counts(
    conn: psycopg.Connection, game_date: date
) -> ProjectionVerifyResult:
    """
    Compare batter_projection rows to the resolved lineup on projected games.

    Uses the same ``_resolve_lineup`` the runner does (confirmed batting order, or the
    L30-PA proxy), so the expected count tracks confirmed (9) vs projected lineups.
    ``projectable_hitter_count`` = resolved hitters with ``batter_skill``; the runner
    should write exactly that many rows (one per projectable hitter).
    """
    projected = conn.execute(
        """
        SELECT id, home_team_id, away_team_id
        FROM games
        WHERE game_date = %s AND projected_at IS NOT NULL
        ORDER BY id
        """,
        (game_date,),
    ).fetchall()

    slate_total = 0
    projectable = 0
    per_game: list[tuple[int, int, int]] = []

    for game_id, home_id, away_id in projected:
        expected = 0
        for team_id, is_home in ((home_id, True), (away_id, False)):
            for hitter in _resolve_lineup(
                conn, game_id=game_id, team_id=team_id, is_home=is_home, as_of=game_date
            ):
                slate_total += 1
                if _load_batter_skill(conn, hitter.player_id) is not None:
                    projectable += 1
                    expected += 1

        row = conn.execute(
            "SELECT COUNT(*) FROM batter_projections WHERE game_id = %s",
            (game_id,),
        ).fetchone()
        actual = int(row[0])
        per_game.append((int(game_id), expected, actual))

    return ProjectionVerifyResult(
        slate_hitter_count=slate_total,
        projectable_hitter_count=projectable,
        batter_projection_rows=count_batter_projections(conn, game_date),
        game_projection_rows=count_game_projections(conn, game_date),
        per_game=per_game,
    )


def cmd_smoke_project(args: argparse.Namespace) -> None:
    """Run ``project`` then verify projection row counts match the lineup proxy."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    game_date = args.date if args.date is not None else eastern_today()
    print(f"[smoke-project] Running projections for {game_date}…")

    conn = get_connection()
    try:
        summary = run_projections(conn, game_date)
        conn.commit()
        verify = verify_projection_counts(conn, game_date)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[smoke-project] Projected {summary.games_projected}/{summary.games_seen} game(s), "
        f"{summary.batter_rows} batter row(s) written"
    )
    print(
        f"[smoke-project] Slate hitters on projected games: {verify.slate_hitter_count} "
        f"(projectable with batter_skill: {verify.projectable_hitter_count})"
    )
    print(
        f"[smoke-project] DB rows — batter_projections: {verify.batter_projection_rows}, "
        f"game_projections: {verify.game_projection_rows}"
    )

    ok = True
    if summary.batter_rows != verify.batter_projection_rows:
        print(
            "[smoke-project] FAIL: runner batter_rows != DB batter_projections count"
        )
        ok = False
    if verify.batter_projection_rows != verify.projectable_hitter_count:
        print(
            "[smoke-project] FAIL: batter_projections count != projectable slate hitters"
        )
        ok = False
    if verify.game_projection_rows != summary.games_projected:
        print(
            "[smoke-project] FAIL: game_projections count != games projected"
        )
        ok = False
    for game_id, expected, actual in verify.per_game:
        if expected != actual:
            print(
                f"[smoke-project] FAIL: game {game_id} expected {expected} rows, got {actual}"
            )
            ok = False

    if summary.games_projected == 0:
        print(
            "[smoke-project] WARN: no games projected — "
            "run daily-slate, refresh-weather, refresh-skills first"
        )
        if verify.slate_hitter_count == 0:
            ok = False

    if ok and summary.games_projected > 0:
        print("[smoke-project] OK — projection counts match slate hitters")
    elif ok:
        print("[smoke-project] OK — no games to project (empty or skipped slate)")
    else:
        sys.exit(1)
