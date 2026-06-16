"""tennis-refresh-ratings: replay Elo + recompute serve/return skills and snapshot
them into tennis_player_ratings. Prints top players per surface as a sanity check."""
from __future__ import annotations

import argparse

from ingester.db import eastern_today, get_connection
from ingester.tennis.constants import SURFACES
from ingester.tennis.ratings import compute_court_speed, refresh_ratings


def _print_top(conn, as_of, surface: str, limit: int = 15, min_matches: int = 20) -> None:
    rows = conn.execute(
        """SELECT p.full_name, r.elo, r.serve_skill, r.matches_count
           FROM tennis_player_ratings r JOIN tennis_players p ON p.id = r.player_id
           WHERE r.as_of_date = %s AND r.surface = %s AND r.matches_count >= %s
           ORDER BY r.elo DESC NULLS LAST LIMIT %s""",
        (as_of, surface, min_matches, limit),
    ).fetchall()
    print(f"\n  Top {limit} — {surface} (min {min_matches} matches)")
    print(f"  {'player':<26}{'elo':>7}{'spw':>7}{'n':>6}")
    for name, elo, spw, n in rows:
        spw_s = f"{spw:.3f}" if spw is not None else "  -  "
        print(f"  {name[:25]:<26}{elo:>7.0f}{spw_s:>7}{n:>6}")


def cmd_tennis_refresh_ratings(args: argparse.Namespace) -> None:
    as_of = args.as_of or eastern_today()
    conn = get_connection()
    try:
        result = refresh_ratings(conn, as_of)
        n_courts = compute_court_speed(conn)
        print(
            f"[tennis-refresh-ratings] as_of={result['as_of']} "
            f"players={result['players']} rating_rows={result['rating_rows']} "
            f"elo_matches={result['elo_matches']} court_speed={n_courts} "
            f"({result['model_version']})"
        )
        for surface in ("all", *SURFACES):
            _print_top(conn, as_of, surface)
    finally:
        conn.close()
