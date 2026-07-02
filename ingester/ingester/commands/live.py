"""live-refresh: high-cadence in-game state (running score + current inning) into the
games.live_* columns, for the home board's real-time bet trackers.

Mirrors backfill-scores' single-fetch-then-UPDATE shape, but:
  - writes the live_* columns, NOT the Final home_score/away_score (those stay the
    grading source of truth — see V60__live_game_state.sql);
  - does NOT gate on Final, so in-progress games update every tick;
  - is meant to run frequently. To get a ~30s cadence without paying `docker compose
    run` container startup each tick, it can loop internally (--loop) for a bounded
    window (--for-minutes), then exit — cron tiles back-to-back loops across the game
    window (see deploy/crontab.example).
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import psycopg
import requests

from ingester.db import active_slate_date, get_connection
from ingester.mlb_api import (
    fetch_schedule,
    parse_game_first_inning,
    parse_game_linescore_live,
    parse_game_score,
)
from ingester.projection.constants import DEAD_GAME_STATUSES

# Hydrate the linescore so we get currentInning / inningState / running runs in one call.
_LIVE_HYDRATE = "linescore"

_BOX_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
_BOX_WORKERS = 8


def _live_game_tuples(raw_games: list[dict]) -> list[tuple]:
    """(game_pk, date, home_id, away_id) for every in-progress (not Final/dead) game."""
    out: list[tuple] = []
    for g in raw_games:
        game_pk = g.get("gamePk")
        if game_pk is None:
            continue
        if (g.get("status") or {}).get("detailedState") in DEAD_GAME_STATUSES:
            continue
        if parse_game_score(g) is not None:  # Final — handled by the live-state pass
            continue
        if parse_game_linescore_live(g) is None:  # not started yet
            continue
        teams = g.get("teams") or {}
        home_id = ((teams.get("home") or {}).get("team") or {}).get("id")
        away_id = ((teams.get("away") or {}).get("team") or {}).get("id")
        out.append((game_pk, g.get("officialDate"), home_id, away_id))
    return out


def _box_player_rows(box: dict, game_pk, game_date) -> tuple[list[dict], list[dict]]:
    """Pure extraction of (batter_rows, pitcher_rows) from a boxscore payload.

    Mirrors the field extraction in backfill_batter_lines / backfill_pitcher_starts but
    keeps only the columns player_game_live holds. A batter needs a plate appearance; a
    pitcher must be the starter (gamesStarted == 1) with outs recorded.
    """
    batters: list[dict] = []
    pitchers: list[dict] = []
    for side in ("home", "away"):
        for pl in box.get("teams", {}).get(side, {}).get("players", {}).values():
            pid = pl.get("person", {}).get("id")
            if pid is None:
                continue
            bat = pl.get("stats", {}).get("batting", {})
            if bat.get("plateAppearances"):
                batters.append({
                    "player_id": pid, "game_id": game_pk, "game_date": game_date,
                    "plate_appearances": bat.get("plateAppearances"),
                    "at_bats": bat.get("atBats"), "hits": bat.get("hits"),
                    "home_runs": bat.get("homeRuns"), "total_bases": bat.get("totalBases"),
                    "strikeouts": bat.get("strikeOuts"), "walks": bat.get("baseOnBalls"),
                    "runs": bat.get("runs"), "rbi": bat.get("rbi"),
                })
            pit = pl.get("stats", {}).get("pitching", {})
            if pit.get("gamesStarted") == 1 and pit.get("outs") is not None:
                pitchers.append({
                    "player_id": pid, "game_id": game_pk, "game_date": game_date,
                    "outs": int(pit["outs"]), "batters_faced": pit.get("battersFaced"),
                    "pitcher_strikeouts": pit.get("strikeOuts"),
                    "hits_allowed": pit.get("hits"), "earned_runs": pit.get("earnedRuns"),
                })
    return batters, pitchers


def _fetch_box_rows(game: tuple) -> tuple[list[dict], list[dict]]:
    """One boxscore fetch → (batter_rows, pitcher_rows) for an in-progress game."""
    game_pk, game_date, _home_id, _away_id = game
    try:
        box = requests.get(_BOX_URL.format(game_pk=game_pk), timeout=20).json()
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't kill the tick
        return [], []
    return _box_player_rows(box, game_pk, game_date)


_BATTER_UPSERT = """
INSERT INTO player_game_live (
    player_id, game_id, game_date,
    plate_appearances, at_bats, hits, home_runs, total_bases, strikeouts, walks,
    runs, rbi, updated_at
) VALUES (
    %(player_id)s, %(game_id)s, %(game_date)s,
    %(plate_appearances)s, %(at_bats)s, %(hits)s, %(home_runs)s, %(total_bases)s,
    %(strikeouts)s, %(walks)s, %(runs)s, %(rbi)s, NOW()
)
ON CONFLICT (player_id, game_id) DO UPDATE SET
    game_date = EXCLUDED.game_date,
    plate_appearances = EXCLUDED.plate_appearances, at_bats = EXCLUDED.at_bats,
    hits = EXCLUDED.hits, home_runs = EXCLUDED.home_runs, total_bases = EXCLUDED.total_bases,
    strikeouts = EXCLUDED.strikeouts, walks = EXCLUDED.walks,
    runs = EXCLUDED.runs, rbi = EXCLUDED.rbi, updated_at = NOW()
"""

_PITCHER_UPSERT = """
INSERT INTO player_game_live (
    player_id, game_id, game_date,
    outs, batters_faced, pitcher_strikeouts, hits_allowed, earned_runs, updated_at
) VALUES (
    %(player_id)s, %(game_id)s, %(game_date)s,
    %(outs)s, %(batters_faced)s, %(pitcher_strikeouts)s, %(hits_allowed)s, %(earned_runs)s, NOW()
)
ON CONFLICT (player_id, game_id) DO UPDATE SET
    game_date = EXCLUDED.game_date,
    outs = EXCLUDED.outs, batters_faced = EXCLUDED.batters_faced,
    pitcher_strikeouts = EXCLUDED.pitcher_strikeouts, hits_allowed = EXCLUDED.hits_allowed,
    earned_runs = EXCLUDED.earned_runs, updated_at = NOW()
"""


def _update_player_live(conn: psycopg.Connection, live_games: list[tuple]) -> int:
    """Upsert in-progress batter + pitcher box-score lines into player_game_live."""
    if not live_games:
        return 0
    n = 0
    with ThreadPoolExecutor(max_workers=_BOX_WORKERS) as pool:
        for batters, pitchers in pool.map(_fetch_box_rows, live_games):
            for r in batters:
                conn.execute(_BATTER_UPSERT, r)
                n += 1
            for r in pitchers:
                conn.execute(_PITCHER_UPSERT, r)
                n += 1
    return n


def _update_live(conn: psycopg.Connection, raw_games: list[dict]) -> int:
    """Update game state for in-progress and just-finished games. Returns rows updated.

    While a game is live we write the live_* columns. The moment the schedule reports it
    Final we set the Final score (+ first-inning runs) and clear live_* in the SAME pass —
    so the board ends the game promptly at the live cadence instead of waiting for the
    slower backfill-scores cron (which is what left finished games stuck "bottom 9th").
    """
    n = 0
    for g in raw_games:
        game_pk = g.get("gamePk")
        if game_pk is None:
            continue
        status = (g.get("status") or {}).get("abstractGameState")
        if (g.get("status") or {}).get("detailedState") in DEAD_GAME_STATUSES:
            continue

        final = parse_game_score(g)  # not None only once the game is Final
        if final is not None:
            home, away = final
            first = parse_game_first_inning(g)
            home_1st, away_1st = first if first is not None else (None, None)
            n += conn.execute(
                "UPDATE games SET status = %s, home_score = %s, away_score = %s,"
                " home_score_1st = COALESCE(%s, home_score_1st),"
                " away_score_1st = COALESCE(%s, away_score_1st),"
                " live_home_score = NULL, live_away_score = NULL,"
                " live_current_inning = NULL, live_inning_state = NULL,"
                " live_is_top = NULL, live_updated_at = NOW() WHERE id = %s",
                (status, home, away, home_1st, away_1st, game_pk),
            ).rowcount
            continue

        live = parse_game_linescore_live(g)
        if live is None:
            continue
        n += conn.execute(
            "UPDATE games SET status = %s, live_home_score = %s, live_away_score = %s,"
            " live_current_inning = %s, live_inning_state = %s, live_is_top = %s,"
            " live_updated_at = NOW() WHERE id = %s",
            (
                status, live["home"], live["away"], live["inning"],
                live["inning_state"], live["is_top"], game_pk,
            ),
        ).rowcount
    return n


def _tick(conn: psycopg.Connection, game_date: date) -> tuple[int, int]:
    """Returns (game rows updated, player rows upserted)."""
    raw = fetch_schedule(game_date, hydrate=_LIVE_HYDRATE)
    games_n = _update_live(conn, raw)
    players_n = _update_player_live(conn, _live_game_tuples(raw))
    conn.commit()
    return games_n, players_n


def cmd_live_refresh(args: argparse.Namespace) -> None:
    loop: bool = getattr(args, "loop", False)
    interval: int = getattr(args, "interval_seconds", 30)
    for_minutes: int = getattr(args, "for_minutes", 30)

    conn = get_connection()
    try:
        # Default to the active slate (latest with games), NOT eastern_today() — so a late
        # game that crosses midnight ET keeps getting ticked + finalized (see active_slate_date).
        game_date = getattr(args, "date", None) or active_slate_date(conn)
        if not loop:
            games_n, players_n = _tick(conn, game_date)
            print(f"[live-refresh] updated {games_n} game(s), {players_n} player line(s).")
            return

        deadline = time.monotonic() + for_minutes * 60
        ticks = 0
        while True:
            try:
                games_n, players_n = _tick(conn, game_date)
                ticks += 1
                print(f"[live-refresh] tick {ticks}: {games_n} game(s), "
                      f"{players_n} player line(s).", flush=True)
            except Exception as exc:  # noqa: BLE001 — one bad poll shouldn't kill the loop
                conn.rollback()
                print(f"[live-refresh] tick failed: {exc}", flush=True)
            if time.monotonic() + interval >= deadline:
                break
            time.sleep(interval)
        print(f"[live-refresh] done after {ticks} tick(s) over ~{for_minutes}m.")
    finally:
        conn.close()
