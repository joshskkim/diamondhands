"""tennis-odds: pull ATP match-winner (h2h) odds from The Odds API and store raw
quotes in tennis_match_odds (de-vig + EV are computed in the API). Events are
matched to scheduled tennis_matches by odds_event_id (set by tennis-slate).

Without ODDS_API_KEY the command no-ops unless --sample is given."""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from ingester.db import get_connection
from ingester.tennis.oddsfeed import (
    build_name_index,
    fetch_h2h,
    load_sample_h2h,
    match_player,
    parse_h2h,
)


def cmd_tennis_odds(args: argparse.Namespace) -> None:
    load_dotenv()
    api_key = os.getenv("ODDS_API_KEY")
    if not args.sample and not api_key:
        print("[tennis-odds] no ODDS_API_KEY and no --sample — skipping")
        return

    events = load_sample_h2h() if args.sample else fetch_h2h(api_key)
    conn = get_connection()
    try:
        index = build_name_index(conn)
        # event_id -> (match_id, player_a_id, player_b_id) for scheduled matches.
        slate = {
            eid: (mid, a, b)
            for mid, eid, a, b in conn.execute(
                "SELECT id, odds_event_id, player_a_id, player_b_id "
                "FROM tennis_matches WHERE odds_event_id IS NOT NULL"
            ).fetchall()
        }

        matched = 0
        rows_written = 0
        skipped = 0
        with conn.cursor() as cur:
            for ev in events:
                entry = slate.get(ev.get("id"))
                if entry is None:
                    skipped += 1
                    continue
                match_id, a_id, b_id = entry
                quotes = parse_h2h(ev)
                if not quotes:
                    continue
                cur.execute("DELETE FROM tennis_match_odds WHERE match_id = %s", (match_id,))
                for q in quotes:
                    pid = match_player(q["player_name"], index)
                    side = "player_a" if pid == a_id else "player_b" if pid == b_id else None
                    if side is None:
                        continue
                    cur.execute(
                        "INSERT INTO tennis_match_odds (match_id, bookmaker, side, "
                        "price_american, price_decimal, implied_prob, last_update) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (match_id, bookmaker, side) DO UPDATE SET "
                        "price_american=EXCLUDED.price_american, price_decimal=EXCLUDED.price_decimal, "
                        "implied_prob=EXCLUDED.implied_prob, last_update=EXCLUDED.last_update, "
                        "fetched_at=NOW()",
                        (match_id, q["bookmaker"], side, q["price_american"],
                         q["price_decimal"], q["implied_prob"], q["last_update"]),
                    )
                    rows_written += 1
                matched += 1
        conn.commit()
        print(f"[tennis-odds] {matched} matches priced, {rows_written} quotes, "
              f"{skipped} events not on slate")
    finally:
        conn.close()
