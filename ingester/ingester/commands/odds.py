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
from datetime import datetime, timezone

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


def _games_needing_odds(conn, game_date, force: bool = False) -> set[int]:
    """Game ids on the date that still need an odds pull (haven't started yet).

    A game is *locked* — skipped from further pulls — only once it has odds AND both
    lineups are confirmed AND its last pull happened after both confirmations. That
    guarantees exactly one final pull capturing the late-posting player props (books post
    props after lineups lock) for both teams, then we stop touching the API for it.

    A game therefore still needs a pull when any of these hold:
      • we've never pulled it (odds_pulled_at IS NULL) — the "new game" case,
      • either lineup isn't confirmed yet (lines/props still firming), or
      • we last pulled before the lineups locked (haven't captured the final board).

    ``force`` returns every not-yet-started game (the --force override).
    """
    rows = conn.execute(
        """
        SELECT g.id
        FROM games g
        WHERE g.game_date = %s
          AND g.start_time_utc > NOW()
          AND (
                %s
             OR g.odds_pulled_at IS NULL
             OR g.home_lineup_confirmed_at IS NULL
             OR g.away_lineup_confirmed_at IS NULL
             OR g.odds_pulled_at < GREATEST(g.home_lineup_confirmed_at,
                                            g.away_lineup_confirmed_at)
          )
        """,
        (game_date, force),
    ).fetchall()
    return {r[0] for r in rows}


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
    # One timestamp for the whole pull, so all of this run's odds_snapshots rows align.
    run_ts = datetime.now(timezone.utc)
    use_sample = getattr(args, "sample", False)
    force = getattr(args, "force", False)
    api_key = os.getenv("ODDS_API_KEY")

    if not use_sample and not api_key:
        print(
            "[refresh-odds] ODDS_API_KEY not set — skipping (no-op). "
            "Set it in ingester/.env or run with --sample to use fixtures."
        )
        return

    conn = get_connection()
    try:
        team_names = _team_name_map(conn)
        games = _games_by_team_pair(conn, game_date)

        # ── Pull gate: only fetch games that still need odds (see _games_needing_odds) ──
        changed_game_ids = _games_needing_odds(conn, game_date, force)

        # Slate-wide saver: if every game is locked (odds + both lineups confirmed),
        # never touch the API.
        if not changed_game_ids:
            print(
                f"[refresh-odds] {game_date}: no games need odds — "
                f"all pulled with confirmed lineups, no API call"
            )
            return

        # ── Fetch the slate-wide game-markets payload (one API call) ──
        if use_sample:
            print(f"[refresh-odds] {game_date}: SAMPLE mode (fixtures, no API calls)")
            events = odds_api.load_sample_game_odds()
            props_by_event = odds_api.load_sample_props()
        else:
            print(f"[refresh-odds] {game_date}: fetching game markets from The Odds API…")
            events = odds_api.fetch_game_odds(api_key)
            props_by_event = None  # fetched per-event below

        matched = 0
        unmatched_events = 0
        skipped = 0
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

            # Per-game gate: skip games that are already locked (odds pulled with both
            # lineups confirmed). This also skips the per-event player-props API call.
            if game_id not in changed_game_ids:
                skipped += 1
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
                    ON CONFLICT (game_id, bookmaker, market, side, line) DO NOTHING
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

            if prop_event:
                # Period (F5/F1) game markets ride along on the per-event payload.
                for r in odds_api.parse_game_markets(prop_event):
                    american = r["price_american"]
                    conn.execute(
                        """
                        INSERT INTO game_odds
                            (game_id, bookmaker, market, side, line,
                             price_american, price_decimal, implied_prob, last_update)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (game_id, bookmaker, market, side, line) DO NOTHING
                        """,
                        (
                            game_id, r["bookmaker"], r["market"], r["side"], r["line"],
                            american, odds_api.american_to_decimal(american),
                            odds_api.implied_prob(american), r["last_update"],
                        ),
                    )
                    game_rows_total += 1

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
                        ON CONFLICT (game_id, player_id, market, side, line, bookmaker)
                            DO NOTHING
                        """,
                        (
                            game_id, player_id, r["player_name"], r["market"], r["side"],
                            r["line"], american, odds_api.american_to_decimal(american),
                            odds_api.implied_prob(american), r["bookmaker"], r["last_update"],
                        ),
                    )
                    prop_rows_total += 1

            # ── Line-movement capture (append-only) ──
            # Snapshot the just-written current odds into odds_snapshots so future
            # pulls accrue an open→current history. Captures both game markets and
            # props for this game under the single run timestamp.
            conn.execute(
                """
                INSERT INTO odds_snapshots
                    (captured_at, game_id, scope, player_id, market, side, line,
                     bookmaker, price_american, price_decimal)
                SELECT %s, game_id, 'game', NULL, market, side, line,
                       bookmaker, price_american, price_decimal
                FROM game_odds WHERE game_id = %s
                """,
                (run_ts, game_id),
            )
            conn.execute(
                """
                INSERT INTO odds_snapshots
                    (captured_at, game_id, scope, player_id, market, side, line,
                     bookmaker, price_american, price_decimal)
                SELECT %s, game_id, 'prop', player_id, market, side, line,
                       bookmaker, price_american, price_decimal
                FROM player_prop_odds WHERE game_id = %s
                """,
                (run_ts, game_id),
            )

            # Stamp the pull time; the gate locks the game once this is after both
            # lineup confirmations (see _games_needing_odds).
            conn.execute(
                "UPDATE games SET odds_pulled_at = NOW() WHERE id = %s",
                (game_id,),
            )

        # Any game that still needs odds but for which the provider returned no event
        # stays un-pulled (odds_pulled_at unchanged), so the next run retries it.
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[refresh-odds] pulled {matched} game(s), skipped {skipped} (locked); "
        f"{unmatched_events} event(s) had no slate match; "
        f"{game_rows_total} game-odds rows, {prop_rows_total} prop rows"
        + (f", {unmatched_players} prop outcome(s) skipped (unmatched player)"
           if unmatched_players else "")
    )
