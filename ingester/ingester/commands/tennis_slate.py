"""tennis-slate: pull upcoming ATP matches from The Odds API events endpoint and
upsert them into tennis_matches as the live slate (status='scheduled').

Player names are fuzzy-matched to tennis_players. Surface/best_of aren't in the
events payload, so they're inferred from the tournament title (Grand Slam -> Bo5;
surface by name, fallback hard). Without ODDS_API_KEY the command no-ops unless
--sample is given (committed fixture)."""
from __future__ import annotations

import argparse
import os
from datetime import datetime

from dotenv import load_dotenv

from ingester.db import get_connection
from ingester.tennis.oddsfeed import (
    build_name_index,
    fetch_events,
    is_grand_slam,
    load_sample_events,
    match_player,
)

_SLAM_SURFACE = {
    "roland garros": "clay", "french open": "clay",
    "wimbledon": "grass", "australian open": "hard", "us open": "hard",
}


def _infer_surface(conn, title: str | None) -> str:
    t = (title or "").lower()
    for name, surface in _SLAM_SURFACE.items():
        if name in t:
            return surface
    # Strip a leading tour prefix and look the tournament up by name in history.
    token = t.replace("atp", "").strip()
    if token:
        row = conn.execute(
            "SELECT surface FROM tennis_tournaments "
            "WHERE surface IS NOT NULL AND lower(name) LIKE %s "
            "GROUP BY surface ORDER BY count(*) DESC LIMIT 1",
            (f"%{token}%",),
        ).fetchone()
        if row:
            return row[0]
    return "hard"


def cmd_tennis_slate(args: argparse.Namespace) -> None:
    load_dotenv()
    api_key = os.getenv("ODDS_API_KEY")
    if not args.sample and not api_key:
        print("[tennis-slate] no ODDS_API_KEY and no --sample — skipping")
        return

    events = load_sample_events() if args.sample else fetch_events(api_key)
    conn = get_connection()
    try:
        index = build_name_index(conn)
        upserted = 0
        unmatched = 0
        with conn.cursor() as cur:
            for ev in events:
                eid = ev.get("id")
                a_name, b_name = ev.get("home_team"), ev.get("away_team")
                if not (eid and a_name and b_name):
                    continue
                a_id = match_player(a_name, index)
                b_id = match_player(b_name, index)
                if not a_id or not b_id:
                    unmatched += 1
                    print(f"[tennis-slate] unmatched: {a_name} ({a_id}) vs {b_name} ({b_id})")
                    continue

                commence = ev.get("commence_time")
                start = datetime.fromisoformat(commence.replace("Z", "+00:00")) if commence else None
                match_date = start.date() if start else None
                surface = _infer_surface(conn, ev.get("sport_title"))
                best_of = 5 if is_grand_slam(ev.get("sport_title")) else 3

                existing = cur.execute(
                    "SELECT id FROM tennis_matches WHERE odds_event_id = %s", (eid,)
                ).fetchone()
                if existing:
                    cur.execute(
                        "UPDATE tennis_matches SET match_date=%s, start_time_utc=%s, "
                        "surface=%s, best_of=%s, player_a_id=%s, player_b_id=%s, "
                        "status='scheduled' WHERE id=%s",
                        (match_date, start, surface, best_of, a_id, b_id, existing[0]),
                    )
                else:
                    cur.execute(
                        "INSERT INTO tennis_matches (match_date, start_time_utc, surface, "
                        "best_of, player_a_id, player_b_id, status, odds_event_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,'scheduled',%s)",
                        (match_date, start, surface, best_of, a_id, b_id, eid),
                    )
                upserted += 1
        conn.commit()
        print(f"[tennis-slate] {upserted} scheduled matches upserted, {unmatched} unmatched")
    finally:
        conn.close()
