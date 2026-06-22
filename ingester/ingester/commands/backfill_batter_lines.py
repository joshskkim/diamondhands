"""backfill-batter-lines: same-day batting actuals from MLB Stats API boxscores.

The richer batter game logs come from Statcast (``backfill-stats`` via pybaseball), but
Statcast lags ~a day, so today's batter prop badges (hit/HR/K/BB) can't grade off it until
the next morning. Boxscores are available live, so this fills the outcome columns
(``hits``/``home_runs``/``strikeouts``/``walks``/``total_bases``/PA) into player_game_stats
as games go final — the next-morning ``backfill-stats`` run then overwrites/enriches the same
rows with the full Statcast aggregation (both upserts COALESCE, so neither clobbers the other).

Mirrors ``backfill-pitcher-starts``: same boxscore endpoint, same game-selection gate
(final score present, or a past date), same thread pool. Idempotent upsert keyed on the
player_game_stats PK (player_id, game_date, game_id).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import requests

from ingester.db import eastern_today, get_connection

BOX_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
WORKERS = 8

# Only the actual-outcome columns grading needs. Skill columns (xwoba/woba) are left to the
# Statcast backfill; COALESCE means this upsert never nulls them and the later run wins.
_UPSERT = """
INSERT INTO player_game_stats (
    player_id, game_date, game_id, opponent_team_id, is_home,
    plate_appearances, at_bats, hits, home_runs, total_bases, strikeouts, walks
) VALUES (
    %(player_id)s, %(game_date)s, %(game_id)s, %(opponent_team_id)s, %(is_home)s,
    %(plate_appearances)s, %(at_bats)s, %(hits)s, %(home_runs)s, %(total_bases)s,
    %(strikeouts)s, %(walks)s
)
ON CONFLICT (player_id, game_date, game_id) DO UPDATE
    SET opponent_team_id  = COALESCE(EXCLUDED.opponent_team_id,  player_game_stats.opponent_team_id),
        is_home           = EXCLUDED.is_home,
        plate_appearances = COALESCE(EXCLUDED.plate_appearances, player_game_stats.plate_appearances),
        at_bats           = COALESCE(EXCLUDED.at_bats,           player_game_stats.at_bats),
        hits              = COALESCE(EXCLUDED.hits,              player_game_stats.hits),
        home_runs         = COALESCE(EXCLUDED.home_runs,         player_game_stats.home_runs),
        total_bases       = COALESCE(EXCLUDED.total_bases,       player_game_stats.total_bases),
        strikeouts        = COALESCE(EXCLUDED.strikeouts,        player_game_stats.strikeouts),
        walks             = COALESCE(EXCLUDED.walks,             player_game_stats.walks)
"""


def _fetch_batter_rows(game: tuple) -> list[dict]:
    """All batting lines (PA > 0) for one game: (game_id, date, home_id, away_id)."""
    game_id, game_date, home_id, away_id = game
    try:
        box = requests.get(BOX_URL.format(game_pk=game_id), timeout=20).json()
    except Exception:  # noqa: BLE001 — one bad fetch shouldn't kill the backfill
        return []
    rows: list[dict] = []
    for side, opp_id in (("home", away_id), ("away", home_id)):
        for pl in box.get("teams", {}).get(side, {}).get("players", {}).values():
            bat = pl.get("stats", {}).get("batting", {})
            if not bat.get("plateAppearances"):
                continue
            rows.append({
                "player_id": pl["person"]["id"],
                "game_id": game_id,
                "game_date": game_date,
                "opponent_team_id": opp_id,
                "is_home": side == "home",
                "plate_appearances": bat.get("plateAppearances"),
                "at_bats": bat.get("atBats"),
                "hits": bat.get("hits"),
                "home_runs": bat.get("homeRuns"),
                "total_bases": bat.get("totalBases"),
                "strikeouts": bat.get("strikeOuts"),
                "walks": bat.get("baseOnBalls"),
            })
    return rows


def cmd_backfill_batter_lines(args: argparse.Namespace) -> None:
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
    print(f"[backfill-batter-lines] {len(games)} games {start} → {end}, {WORKERS} workers…")

    written = skipped_unknown = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for rows in pool.map(_fetch_batter_rows, games):
            for r in rows:
                if r["player_id"] not in known_players:
                    skipped_unknown += 1
                    continue
                conn.execute(_UPSERT, r)
                written += 1
    conn.commit()
    conn.close()
    print(f"[backfill-batter-lines] {written} batting lines upserted "
          f"({skipped_unknown} skipped: batter not in players).")
