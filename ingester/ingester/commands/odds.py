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
import hashlib
import os
import re
import unicodedata
from datetime import datetime, timezone

from dotenv import load_dotenv

from ingester.db import eastern_today, get_connection
from ingester import odds_api


def odds_input_hash(inputs: tuple) -> str:
    """sha256 of a game's odds-relevant inputs (pure; no DB).

    `inputs` is a tuple of the values that, when changed, should trigger a fresh
    odds pull: confirmed-lineup timestamps, weather (temp / wind speed / wind
    direction / weather-fetched-at), and the two probable pitcher ids. We render
    each element to a stable string ("" for None) joined by a separator that
    cannot appear in the rendered values, then sha256 it. Returns the first 64
    hex chars (a full sha256 digest is 64 chars, so this is the whole digest).
    """
    canonical = "|".join("" if v is None else str(v) for v in inputs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:64]


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


def _slate_hashes(conn, game_date) -> dict[int, str]:
    """{game_id: freshly-computed odds_input_hash} for every game on the date.

    The hash covers only inputs that should force a fresh odds pull when they
    change: confirmed-lineup timestamps, weather, and probable pitcher ids.
    """
    rows = conn.execute(
        """
        SELECT id,
               home_lineup_confirmed_at, away_lineup_confirmed_at,
               temperature_f, wind_speed_mph, wind_direction_degrees, weather_fetched_at,
               home_probable_pitcher_id, away_probable_pitcher_id
        FROM games
        WHERE game_date = %s
        """,
        (game_date,),
    ).fetchall()
    return {row[0]: odds_input_hash(tuple(row[1:])) for row in rows}


def _stored_hashes(conn, game_date) -> dict[int, str | None]:
    """{game_id: stored games.odds_input_hash} for every game on the date."""
    rows = conn.execute(
        "SELECT id, odds_input_hash FROM games WHERE game_date = %s",
        (game_date,),
    ).fetchall()
    return {gid: h for gid, h in rows}


def _games_needing_props(conn, game_date) -> set[int]:
    """Game ids on the date with no player-prop rows yet that haven't started.

    Books post player props later than game markets — usually after our first
    pull of the day. The input-hash gate keys only on lineup/weather/pitcher
    inputs, so once those lock it would skip the game forever and never capture
    late-posting props (nor the provider's refreshed event id). We force a
    re-pull of such games until first pitch or until at least one prop row lands.
    """
    rows = conn.execute(
        """
        SELECT g.id
        FROM games g
        WHERE g.game_date = %s
          AND g.start_time_utc > NOW()
          AND NOT EXISTS (SELECT 1 FROM player_prop_odds p WHERE p.game_id = g.id)
        """,
        (game_date,),
    ).fetchall()
    return {r[0] for r in rows}


def _game_roster(conn, game_id: int) -> dict[str, int]:
    """{normalized player name: player_id} for everyone on either team in this game.

    Resolves against the two teams' rosters (players.team_id, refreshed nightly from the MLB
    roster) plus the probable pitchers — NOT the projected lineup. Books post props (and we
    want to store them) hours before confirmed lineups land, so keying off batter_projections
    meant an unprojected game's props were all "unmatched player" and discarded, then re-pulled
    every tick. Team rosters let a prop store on the first pull regardless of projection, which
    also drops the game out of `_games_needing_props` so the per-tick re-pull loop stops.
    """
    rows = conn.execute(
        """
        SELECT p.id, p.full_name
        FROM players p
        JOIN games g ON g.id = %s
        WHERE p.team_id IN (g.home_team_id, g.away_team_id)
           OR p.id IN (g.home_probable_pitcher_id, g.away_probable_pitcher_id)
        """,
        (game_id,),
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

        # ── Cache gate: compute fresh hashes from DB inputs, compare to stored ──
        fresh_hashes = _slate_hashes(conn, game_date)
        stored_hashes = _stored_hashes(conn, game_date)
        # A game is "fresh" (skippable) only if it has been pulled before
        # (stored hash non-NULL) AND its inputs are unchanged.
        changed_game_ids = {
            gid for gid, h in fresh_hashes.items()
            if force or stored_hashes.get(gid) is None or stored_hashes[gid] != h
        }
        # Also (re)pull games still missing props before first pitch — books
        # post props after the early game-markets pull, and the hash gate alone
        # would never revisit them once lineups/weather/pitchers lock.
        changed_game_ids |= _games_needing_props(conn, game_date)

        # Slate-wide saver: if nothing changed, never touch the API.
        if not changed_game_ids:
            print(
                f"[refresh-odds] {game_date}: no slate games changed — "
                f"skipped {len(fresh_hashes)} (inputs unchanged), no API call"
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

            # Per-game gate: skip games whose inputs are unchanged. This also
            # skips the per-event player-props API call for them.
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

            # Record the gate state for this game's successful pull.
            conn.execute(
                "UPDATE games SET odds_input_hash = %s, odds_pulled_at = NOW() WHERE id = %s",
                (fresh_hashes[game_id], game_id),
            )

        # Any changed game that the provider did not return an event for stays
        # un-pulled (its stored hash is unchanged), so the next run retries it.
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(
        f"[refresh-odds] pulled {matched} game(s), skipped {skipped} (inputs unchanged); "
        f"{unmatched_events} event(s) had no slate match; "
        f"{game_rows_total} game-odds rows, {prop_rows_total} prop rows"
        + (f", {unmatched_players} prop outcome(s) skipped (unmatched player)"
           if unmatched_players else "")
    )
