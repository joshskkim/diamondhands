"""tennis-odds: pull ATP match-winner (h2h) odds from The Odds API and store raw
quotes in tennis_match_odds (de-vig + EV are computed in the API). Events are
matched to scheduled tennis_matches by odds_event_id (set by tennis-slate).

Without ODDS_API_KEY the command no-ops unless --sample is given."""
from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from ingester.db import get_connection
from ingester.tennis.games_calibration import GamesCalibrator
from ingester.tennis.oddsfeed import (
    build_name_index,
    fetch_h2h,
    load_sample_h2h,
    match_player,
    parse_h2h,
    parse_totals,
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
        games_cal = GamesCalibrator.load()
        # event_id -> (match_id, a_id, b_id, best_of, exp_total_games) for scheduled matches.
        slate = {
            eid: (mid, a, b, bo, float(exp) if exp is not None else None)
            for mid, eid, a, b, bo, exp in conn.execute(
                "SELECT m.id, m.odds_event_id, m.player_a_id, m.player_b_id, m.best_of, "
                "       tp.exp_total_games "
                "FROM tennis_matches m "
                "LEFT JOIN tennis_match_projections tp ON tp.match_id = m.id "
                "WHERE m.odds_event_id IS NOT NULL"
            ).fetchall()
        }

        matched = 0
        rows_written = 0
        total_rows = 0
        skipped = 0
        with conn.cursor() as cur:
            for ev in events:
                entry = slate.get(ev.get("id"))
                if entry is None:
                    skipped += 1
                    continue
                match_id, a_id, b_id, best_of, exp_games = entry
                quotes = parse_h2h(ev)
                if quotes:
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

                # Total games (over/under): model P(side) at each book's line.
                totals = parse_totals(ev)
                if totals:
                    cur.execute("DELETE FROM tennis_total_odds WHERE match_id = %s", (match_id,))
                    for t in totals:
                        model_prob = None
                        if games_cal is not None and exp_games is not None:
                            p_over = games_cal.p_over_at_mean(exp_games, best_of or 3, t["line"])
                            if p_over is not None:
                                model_prob = round(p_over if t["side"] == "over" else 1.0 - p_over, 4)
                        cur.execute(
                            "INSERT INTO tennis_total_odds (match_id, bookmaker, side, line, "
                            "price_american, price_decimal, implied_prob, model_prob, last_update) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT (match_id, bookmaker, side, line) DO UPDATE SET "
                            "price_american=EXCLUDED.price_american, price_decimal=EXCLUDED.price_decimal, "
                            "implied_prob=EXCLUDED.implied_prob, model_prob=EXCLUDED.model_prob, "
                            "last_update=EXCLUDED.last_update, fetched_at=NOW()",
                            (match_id, t["bookmaker"], t["side"], t["line"], t["price_american"],
                             t["price_decimal"], t["implied_prob"], model_prob, t["last_update"]),
                        )
                        total_rows += 1
        conn.commit()
        print(f"[tennis-odds] {matched} matches priced, {rows_written} h2h quotes, "
              f"{total_rows} totals quotes, {skipped} events not on slate")
    finally:
        conn.close()
