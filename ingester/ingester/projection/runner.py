"""CLI runner: project today's slate into batter_projections and game_projections."""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

import psycopg

from ingester.db import eastern_today, get_connection
from ingester.projection.batter_model import (
    BatterSkillInput,
    expected_team_runs,
    project_batter,
)
from ingester.projection.constants import LINEUP_SIZE_HITTERS, LINEUP_STARTERS
from ingester.projection.park_adj import ParkAdjustments, ParkFactors, compute_park_adjustments
from ingester.projection.pitcher_adj import (
    PitcherHandSplit,
    pitcher_adjustments_for_batter,
)
from ingester.projection.weather_adj import compute_weather_adjustments

log = logging.getLogger(__name__)

# Keep in sync with ingester.statcast.SEASON_BOUNDARIES
_SEASON_BOUNDARIES: dict[int, tuple[date, date]] = {
    2025: (date(2025, 3, 18), date(2025, 9, 28)),
}

_PITCHER_POSITIONS = frozenset({"P", "SP", "RP", "CP", "TWP"})


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
    is_dome: bool
    is_retractable: bool
    cf_bearing_degrees: float
    park_factor_hits: float
    park_factor_hr_lhb: float
    park_factor_hr_rhb: float


@dataclass(frozen=True)
class HitterCandidate:
    player_id: int
    bats: str
    pa_l30: int


def infer_season(game_date: date) -> int:
    for season, (start, end) in _SEASON_BOUNDARIES.items():
        if start <= game_date <= end:
            return season
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
            s.is_dome,
            COALESCE(s.is_retractable, FALSE),
            s.cf_bearing_degrees,
            COALESCE(s.park_factor_hits, 1.0),
            COALESCE(s.park_factor_hr_lhb, 1.0),
            COALESCE(s.park_factor_hr_rhb, 1.0)
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
                is_dome=bool(row[8]),
                is_retractable=bool(row[9]),
                cf_bearing_degrees=float(row[10]),
                park_factor_hits=float(row[11]),
                park_factor_hr_lhb=float(row[12]),
                park_factor_hr_rhb=float(row[13]),
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


def _load_pitcher_throws(conn: psycopg.Connection, pitcher_id: int) -> str | None:
    row = conn.execute(
        "SELECT throws FROM players WHERE id = %s",
        (pitcher_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def _game_ready(game: SlateGame) -> str | None:
    if game.home_probable_pitcher_id is None or game.away_probable_pitcher_id is None:
        return "missing probable pitcher"
    if not game.is_dome or game.is_retractable:
        if (
            game.temperature_f is None
            or game.wind_speed_mph is None
            or game.wind_from_degrees is None
        ):
            return "missing weather"
    return None


def _upsert_batter_projection(
    conn: psycopg.Connection,
    game_id: int,
    player_id: int,
    opposing_pitcher_id: int,
    is_home: bool,
    proj,
) -> None:
    conn.execute(
        """
        INSERT INTO batter_projections (
            game_id, player_id, opposing_pitcher_id, is_home,
            expected_pa,
            p_hit_1plus, p_hit_2plus, p_hr, p_k_1plus,
            expected_hits, expected_total_bases,
            adj_park, adj_pitcher, adj_weather_hr, adj_weather_hits,
            computed_at
        )
        VALUES (
            %s, %s, %s, %s,
            %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s,
            NOW()
        )
        ON CONFLICT (game_id, player_id) DO UPDATE SET
            opposing_pitcher_id = EXCLUDED.opposing_pitcher_id,
            is_home             = EXCLUDED.is_home,
            expected_pa         = EXCLUDED.expected_pa,
            p_hit_1plus         = EXCLUDED.p_hit_1plus,
            p_hit_2plus         = EXCLUDED.p_hit_2plus,
            p_hr                = EXCLUDED.p_hr,
            p_k_1plus           = EXCLUDED.p_k_1plus,
            expected_hits       = EXCLUDED.expected_hits,
            expected_total_bases = EXCLUDED.expected_total_bases,
            adj_park            = EXCLUDED.adj_park,
            adj_pitcher         = EXCLUDED.adj_pitcher,
            adj_weather_hr      = EXCLUDED.adj_weather_hr,
            adj_weather_hits    = EXCLUDED.adj_weather_hits,
            computed_at         = NOW()
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
        ),
    )


def _project_team_side(
    conn: psycopg.Connection,
    *,
    game: SlateGame,
    team_id: int,
    opposing_pitcher_id: int,
    is_home: bool,
    season: int,
    park: ParkFactors,
    summary: ProjectSummary,
) -> float | None:
    """Project hitters for one team; return expected_team_runs or None if insufficient data."""
    hitters = _likely_hitters(conn, team_id, summary.game_date)
    if len(hitters) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d hitters with L30 PA (need %d)",
            game.game_id,
            team_id,
            len(hitters),
            LINEUP_STARTERS,
        )
        return None

    pitcher_throws = _load_pitcher_throws(conn, opposing_pitcher_id)
    if pitcher_throws is None:
        log.warning(
            "game %s: opposing pitcher %s missing throws hand",
            game.game_id,
            opposing_pitcher_id,
        )
        return None

    splits = _load_pitcher_splits(conn, opposing_pitcher_id, season)
    if not splits:
        log.warning(
            "game %s: no pitcher_skill for pitcher %s",
            game.game_id,
            opposing_pitcher_id,
        )
        return None

    # v1: retractable domes assumed closed (no open/closed flag on games yet).
    is_retractable_open = False

    starter_xwobas: list[float] = []
    weather_hits: list[float] = []
    rows_written = 0

    for hitter in hitters:
        skill = _load_batter_skill(conn, hitter.player_id)
        if skill is None:
            log.warning(
                "game %s: skip batter %s — no batter_skill",
                game.game_id,
                hitter.player_id,
            )
            continue

        park_adj = compute_park_adjustments(
            park, hitter.bats, pitcher_throws
        )
        pitcher_adj = pitcher_adjustments_for_batter(
            splits, hitter.bats, pitcher_throws
        )
        adj_weather_hit, adj_weather_hr = compute_weather_adjustments(
            temperature_f=game.temperature_f or 70.0,
            wind_speed_mph=game.wind_speed_mph or 0.0,
            wind_from_degrees=game.wind_from_degrees or 0.0,
            cf_bearing_degrees=game.cf_bearing_degrees,
            bats=hitter.bats,
            pitcher_throws=pitcher_throws,
            is_dome=game.is_dome,
            is_retractable_open=is_retractable_open,
        )

        proj = project_batter(
            skill,
            pitcher_adj,
            park_adj,
            adj_weather_hit,
            adj_weather_hr,
        )
        _upsert_batter_projection(
            conn,
            game.game_id,
            hitter.player_id,
            opposing_pitcher_id,
            is_home,
            proj,
        )
        rows_written += 1
        summary.batter_rows += 1

        if len(starter_xwobas) < LINEUP_STARTERS:
            starter_xwobas.append(proj.xwoba_blend)
            weather_hits.append(adj_weather_hit)

    if len(starter_xwobas) < LINEUP_STARTERS:
        log.warning(
            "game %s team %s: only %d batters projected (need %d for team runs)",
            game.game_id,
            team_id,
            len(starter_xwobas),
            LINEUP_STARTERS,
        )
        return None

    adj_weather_hit_avg = sum(weather_hits) / len(weather_hits)
    return expected_team_runs(
        starter_xwobas,
        park.park_factor_hits,
        adj_weather_hit_avg,
    )


def _project_game(
    conn: psycopg.Connection,
    game: SlateGame,
    season: int,
    summary: ProjectSummary,
) -> bool:
    reason = _game_ready(game)
    if reason:
        summary.skip_reasons.append(f"game {game.game_id}: {reason}")
        return False

    park = ParkFactors(
        park_factor_hits=game.park_factor_hits,
        park_factor_hr_lhb=game.park_factor_hr_lhb,
        park_factor_hr_rhb=game.park_factor_hr_rhb,
    )

    home_runs = _project_team_side(
        conn,
        game=game,
        team_id=game.home_team_id,
        opposing_pitcher_id=game.away_probable_pitcher_id,
        is_home=True,
        season=season,
        park=park,
        summary=summary,
    )
    away_runs = _project_team_side(
        conn,
        game=game,
        team_id=game.away_team_id,
        opposing_pitcher_id=game.home_probable_pitcher_id,
        is_home=False,
        season=season,
        park=park,
        summary=summary,
    )
    if home_runs is None or away_runs is None:
        summary.skip_reasons.append(
            f"game {game.game_id}: incomplete team projection"
        )
        return False

    conn.execute(
        """
        INSERT INTO game_projections (
            game_id, expected_home_runs, expected_away_runs,
            expected_total_runs, computed_at
        )
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (game_id) DO UPDATE SET
            expected_home_runs  = EXCLUDED.expected_home_runs,
            expected_away_runs  = EXCLUDED.expected_away_runs,
            expected_total_runs = EXCLUDED.expected_total_runs,
            computed_at         = NOW()
        """,
        (
            game.game_id,
            round(home_runs, 2),
            round(away_runs, 2),
            round(home_runs + away_runs, 2),
        ),
    )
    conn.execute(
        "UPDATE games SET projected_at = NOW() WHERE id = %s",
        (game.game_id,),
    )
    return True


def run_projections(
    conn: psycopg.Connection, game_date: date
) -> ProjectSummary:
    summary = ProjectSummary(game_date=game_date)
    season = infer_season(game_date)
    games = _load_slate_games(conn, game_date)
    summary.games_seen = len(games)

    if not games:
        log.info("no games on slate for %s", game_date)
        return summary

    for game in games:
        if _project_game(conn, game, season, summary):
            summary.games_projected += 1
        else:
            summary.games_skipped += 1

    return summary


def cmd_project(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    game_date = args.date if args.date is not None else eastern_today()
    print(f"[project] Computing projections for {game_date}…")

    conn = get_connection()
    try:
        summary = run_projections(conn, game_date)
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
    Compare batter_projection rows to the v1 lineup proxy on projected games.

    ``projectable_hitter_count`` = slate hitters with ``batter_skill``; the runner
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
        for team_id in (home_id, away_id):
            for hitter in _likely_hitters(conn, team_id, game_date):
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
