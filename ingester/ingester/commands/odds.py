"""refresh-odds: pull sportsbook odds (game markets + player props) for a slate.

Source is The Odds API. Each provider event is matched to one of our games by date
+ home/away team name; player props are matched to a player within that game's roster
by normalized name. We delete-then-insert per game (refresh semantics, like `project`),
which also sidesteps the NULL-line uniqueness gap on moneyline rows.

Without ODDS_API_KEY and without --sample this is a clean no-op, so it is safe to chain
inside `daily`.
"""
from __future__ import annotations

import argparse
import os
import re
import unicodedata

from dotenv import load_dotenv

from ingester.db import build_team_abbrev_map, eastern_today, get_connection
from ingester import odds_api


def _norm_name(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces (for name matching)."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9 ]", "", ascii_only.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _team_name_map(conn) -> dict[str, int]:
    """{normalized full team name: team_id}, e.g. 'los angeles angels' -> 108."""
    rows = conn.execute("SELECT id, name FROM teams").fetchall()
    return {_norm_name(name): tid for tid, name in rows}


def _games_by_team_pair(conn, game_date) -> dict[tuple[int, int], int]:
    """{(home_team_id, away_team_id): game_id} for the date."""
    rows = conn.execute(
        "SELECT id, home_team_id, away_team_id FROM games WHERE game_date = %s",
        (game_date,),
    ).fetchall()
    return {(home, away): gid for gid, home, away in rows}


def _game_roster(conn, game_id: int) -> dict[str, int]:
    """{normalized player name: player_id} for batters + probable pitchers in this game."""
    rows = conn.execute(
        """
        SELECT p.id, p.full_name
        FROM players p
        WHERE p.id IN (
            SELECT player_id FROM batter_projections WHERE game_id = %s
            UNION
            SELECT home_probable_pitcher_id FROM games WHERE id = %s
            UNION
            SELECT away_probable_pitcher_id FROM games WHERE id = %s
        )
        """,
        (game_id, game_id, game_id),
    ).fetchall()
    return {_norm_name(name): pid for pid, name in rows}


def cmd_refresh_odds(args: argparse.Namespace) -> None:
    load_dotenv()
    game_date = args.date if getattr(args, "date", None) is not None else eastern_today()
    use_sample = getattr(args, "sample", False)
    api_key = os.getenv("ODDS_API_KEY")

    if use_sample:
        print(f"[refresh-odds] {game_date}: SAMPLE mode (fixtures, no API calls)")
        events = odds_api.load_sample_game_odds()
        props_by_event = odds_api.load_sample_props()
    elif not api_key:
        print(
            "[refresh-odds] ODDS_API_KEY not set — skipping (no-op). "
            "Set it in ingester/.env or run with --sample to use fixtures."
        )
        return
    else:
        print(f"[refresh-odds] {game_date}: fetching game markets from The Odds API…")
        events = odds_api.fetch_game_odds(api_key)
        props_by_event = None  # fetched per-event below

    conn = get_connection()
    try:
        team_names = _team_name_map(conn)
        games = _games_by_team_pair(conn, game_date)

        matched = 0
        unmatched_events = 0
        game_rows_total = 0
        prop_rows_total = 0
        unmatched_players = 0

        for event in events:
            home_id = team_names.get(_norm_name(event.get("home_team", "")))
            away_id = team_names.get(_norm_name(event.get("away_team", "")))
            game_id = games.get((home_id, away_id)) if home_id and away_id else None
            if game_id is None:
                unmatched_events += 1
                continue
            matched += 1
            event_id = event.get("id")

            # Refresh semantics: clear this game's odds, then re-insert.
            conn.execute("DELETE FROM game_odds WHERE game_id = %s", (game_id,))
            conn.execute("DELETE FROM player_prop_odds WHERE game_id = %s", (game_id,))
            conn.execute(
                "UPDATE games SET odds_event_id = %s WHERE id = %s", (event_id, game_id)
            )

            # ── Game markets ──
            grows = odds_api.parse_game_markets(event)
            for r in grows:
                american = r["price_american"]
                conn.execute(
                    """
                    INSERT INTO game_odds
                        (game_id, bookmaker, market, side, line,
                         price_american, price_decimal, implied_prob, last_update)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        game_id, r["bookmaker"], r["market"], r["side"], r["line"],
                        american, odds_api.american_to_decimal(american),
                        odds_api.implied_prob(american), r["last_update"],
                    ),
                )
            game_rows_total += len(grows)

            # ── Player props ──
            if use_sample:
                prop_event = props_by_event.get(event_id)
            elif api_key:
                prop_event = odds_api.fetch_event_props(api_key, event_id)
            else:
                prop_event = None
            if not prop_event:
                continue

            roster = _game_roster(conn, game_id)
            for r in odds_api.parse_prop_markets(prop_event):
                player_id = roster.get(_norm_name(r["player_name"]))
                if player_id is None:
                    unmatched_players += 1
                    continue
                if r["line"] is None:
                    continue
                american = r["price_american"]
                conn.execute(
                    """
                    INSERT INTO player_prop_odds
                        (game_id, player_id, player_name, market, side, line,
                         price_american, price_decimal, implied_prob, bookmaker, last_update)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        game_id, player_id, r["player_name"], r["market"], r["side"],
                        r["line"], american, odds_api.american_to_decimal(american),
                        odds_api.implied_prob(american), r["bookmaker"], r["last_update"],
                    ),
                )
                prop_rows_total += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[refresh-odds] matched {matched} game(s) "
        f"({unmatched_events} event(s) had no slate match); "
        f"{game_rows_total} game-odds rows, {prop_rows_total} prop rows"
        + (f", {unmatched_players} prop outcome(s) skipped (unmatched player)"
           if unmatched_players else "")
    )
