"""backfill-pitcher-starts: per-start workload lines from MLB Stats API boxscores.

player_game_stats (Statcast) has pitcher K/BF but no outs/innings; boxscores carry
outs directly, plus pitches and earned runs. One row per START (gamesStarted == 1).
Idempotent upsert; only fetches games on/after --start that are in the games table
and already played (final score present, or game_date < today as a fallback).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from ingester.db import eastern_today, get_connection

BOX_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
WORKERS = 8


def _fetch_start_rows(game: tuple) -> list[dict]:
    """All starter pitching lines for one game: (game_id, date, home_id, away_id)."""
    game_id, game_date, home_id, away_id = game
    try:
        box = requests.get(BOX_URL.format(game_pk=game_id), timeout=20).json()
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't kill the backfill
        return []
    rows: list[dict] = []
    for side, team_id, opp_id in (("home", home_id, away_id), ("away", away_id, home_id)):
        for pl in box.get("teams", {}).get(side, {}).get("players", {}).values():
            pit = pl.get("stats", {}).get("pitching", {})
            if pit.get("gamesStarted") != 1 or pit.get("outs") is None:
                continue
            rows.append({
                "player_id": pl["person"]["id"],
                "game_id": game_id,
                "game_date": game_date,
                "team_id": team_id,
                "opponent_id": opp_id,
                "is_home": side == "home",
                "outs": int(pit["outs"]),
                "batters_faced": pit.get("battersFaced"),
                "strikeouts": pit.get("strikeOuts"),
                "walks": pit.get("baseOnBalls"),
                "hits_allowed": pit.get("hits"),
                "hr_allowed": pit.get("homeRuns"),
                "earned_runs": pit.get("earnedRuns"),
                "pitches": pit.get("numberOfPitches"),
            })
    return rows


def cmd_backfill_pitcher_starts(args: argparse.Namespace) -> None:
    start: date = getattr(args, "start", None) or date(2023, 3, 1)
    end: date = getattr(args, "end", None) or eastern_today()

    conn = get_connection()
    games = conn.execute(
        """
        SELECT id, game_date, home_team_id, away_team_id
        FROM games
        WHERE game_date BETWEEN %s AND %s
          AND (home_score IS NOT NULL OR game_date < %s)
        ORDER BY game_date
        """,
        (start, end, eastern_today()),
    ).fetchall()
    known_players = {int(r[0]) for r in conn.execute("SELECT id FROM players").fetchall()}
    print(f"[backfill-pitcher-starts] {len(games)} games {start} → {end}, {WORKERS} workers…")

    written = skipped_unknown = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for rows in pool.map(_fetch_start_rows, games):
            for r in rows:
                if r["player_id"] not in known_players:
                    skipped_unknown += 1
                    continue
                conn.execute(
                    """
                    INSERT INTO pitcher_starts (
                        player_id, game_id, game_date, team_id, opponent_id, is_home,
                        outs, batters_faced, strikeouts, walks, hits_allowed,
                        hr_allowed, earned_runs, pitches
                    ) VALUES (
                        %(player_id)s, %(game_id)s, %(game_date)s, %(team_id)s,
                        %(opponent_id)s, %(is_home)s, %(outs)s, %(batters_faced)s,
                        %(strikeouts)s, %(walks)s, %(hits_allowed)s, %(hr_allowed)s,
                        %(earned_runs)s, %(pitches)s
                    )
                    ON CONFLICT (player_id, game_id) DO UPDATE SET
                        outs=EXCLUDED.outs, batters_faced=EXCLUDED.batters_faced,
                        strikeouts=EXCLUDED.strikeouts, walks=EXCLUDED.walks,
                        hits_allowed=EXCLUDED.hits_allowed, hr_allowed=EXCLUDED.hr_allowed,
                        earned_runs=EXCLUDED.earned_runs, pitches=EXCLUDED.pitches
                    """,
                    r,
                )
                written += 1
    conn.commit()
    conn.close()
    print(f"[backfill-pitcher-starts] {written} start rows upserted "
          f"({skipped_unknown} skipped: pitcher not in players).")
