"""Load the Tennismylife/TML-Database ATP dataset into the tennis_* tables.

Source CSVs (Sackmann-schema, maintained): one file per season, `{year}.csv`,
one row per match (winner/loser oriented) with serve lines (w_*/l_*), plus an
`indoor` flag and `winner_rank`/`loser_rank` at match time. Player ids are
official ATP player codes (e.g. 'D643'). Used because the original
JeffSackmann/tennis_atp repo is no longer public.

Design notes:
  - TML is winner/loser oriented. We store player_a/player_b with winner_id, and
    RANDOMIZE which of winner/loser becomes a vs b (seeded per match, so reruns
    are stable) so the slot carries no information about the result — important
    for an unbiased backtest. Each player's match-time rank rides along with its
    slot (player_a_rank / player_b_rank) for the ranking-favorite baseline.
  - Walkover/retired matches are kept in tennis_matches (a result is a result for
    Elo) but their serve lines are EXCLUDED from tennis_player_match_stats (an
    incomplete/forfeited match is not a clean serve/return signal).
"""
from __future__ import annotations

import io
import random
from datetime import date

import pandas as pd
import requests

from ingester.db import get_connection
from ingester.tennis.constants import TML_BASE_URL

_SURFACE_MAP = {"hard": "hard", "clay": "clay", "grass": "grass", "carpet": "carpet"}


def _norm_surface(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _SURFACE_MAP.get(raw.strip().lower())


def _parse_yyyymmdd(value: object) -> date | None:
    try:
        s = str(int(value))
    except (TypeError, ValueError):
        return None
    if len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def _status_from_score(score: object) -> str:
    """Classify match completion from the score string."""
    if not isinstance(score, str) or not score.strip():
        return "completed"
    s = score.upper()
    if "W/O" in s or s.strip() == "WALKOVER":
        return "walkover"
    if "RET" in s:
        return "retired"
    if "DEF" in s:
        return "default"
    return "completed"


def _int_or_none(value: object) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _code_or_none(value: object) -> str | None:
    """Player code as a clean string ('D875'); None for blanks/NaN."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s[:12] if s else None


def _str_or_none(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _read_csv(url: str) -> pd.DataFrame | None:
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text), low_memory=False)


def _ensure_player(cur, code, name, hand, ht, ioc) -> None:
    """Guarantee a player row exists (players are derived from match rows). Minimal
    upsert keyed by ATP code; does not clobber richer data added later."""
    h = _str_or_none(hand)
    h = h.upper()[:1] if h else None
    cur.execute(
        """INSERT INTO tennis_players (id, full_name, hand, country, height_cm)
           VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
        (code, (_str_or_none(name) or f"player {code}")[:100], h,
         _str_or_none(ioc), _int_or_none(ht)),
    )


def _serve_line(r, prefix: str) -> dict:
    g = lambda c: _int_or_none(getattr(r, f"{prefix}_{c}", None))  # noqa: E731
    return {
        "aces": g("ace"), "double_faults": g("df"), "serve_points": g("svpt"),
        "first_in": g("1stIn"), "first_won": g("1stWon"), "second_won": g("2ndWon"),
        "serve_games": g("SvGms"), "bp_saved": g("bpSaved"), "bp_faced": g("bpFaced"),
    }


def _load_year(conn, year: int) -> tuple[int, int]:
    df = _read_csv(f"{TML_BASE_URL}/{year}.csv")
    if df is None:
        return (0, 0)

    tourneys: dict[str, tuple] = {}
    n_matches = 0
    n_stats = 0
    with conn.cursor() as cur:
        for r in df.itertuples(index=False):
            w_id = _code_or_none(getattr(r, "winner_id", None))
            l_id = _code_or_none(getattr(r, "loser_id", None))
            tourney_id = _str_or_none(getattr(r, "tourney_id", None))
            if tourney_id:
                tourney_id = tourney_id[:60]
            match_num = _int_or_none(getattr(r, "match_num", None))
            tdate = _parse_yyyymmdd(getattr(r, "tourney_date", None))
            if not (w_id and l_id and tourney_id and match_num is not None and tdate):
                continue

            surface = _norm_surface(getattr(r, "surface", None))
            best_of = _int_or_none(getattr(r, "best_of", None))
            w_rank = _int_or_none(getattr(r, "winner_rank", None))
            l_rank = _int_or_none(getattr(r, "loser_rank", None))

            # Upsert the tournament before its matches (FK target must exist first).
            if tourney_id not in tourneys:
                indoor_raw = _str_or_none(getattr(r, "indoor", None))
                indoor = None if indoor_raw is None else indoor_raw.upper().startswith("I")
                cur.execute(
                    """INSERT INTO tennis_tournaments
                         (id, name, surface, indoor, level, best_of, draw_size, start_date)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET
                         name = EXCLUDED.name, surface = EXCLUDED.surface,
                         indoor = EXCLUDED.indoor, level = EXCLUDED.level,
                         best_of = EXCLUDED.best_of, draw_size = EXCLUDED.draw_size,
                         start_date = EXCLUDED.start_date""",
                    (tourney_id, (_str_or_none(getattr(r, "tourney_name", None)) or tourney_id)[:120],
                     surface, indoor, (_str_or_none(getattr(r, "tourney_level", None)) or "")[:10] or None,
                     best_of, _int_or_none(getattr(r, "draw_size", None)), tdate),
                )
                tourneys[tourney_id] = True

            _ensure_player(cur, w_id, getattr(r, "winner_name", None),
                           getattr(r, "winner_hand", None), getattr(r, "winner_ht", None),
                           getattr(r, "winner_ioc", None))
            _ensure_player(cur, l_id, getattr(r, "loser_name", None),
                           getattr(r, "loser_hand", None), getattr(r, "loser_ht", None),
                           getattr(r, "loser_ioc", None))

            # Randomize a/b slot (seeded per match), carrying each player's rank along.
            rng = random.Random(f"{tourney_id}:{match_num}")
            if rng.random() < 0.5:
                a_id, b_id, a_rank, b_rank = w_id, l_id, w_rank, l_rank
            else:
                a_id, b_id, a_rank, b_rank = l_id, w_id, l_rank, w_rank

            score = _str_or_none(getattr(r, "score", None))
            status = _status_from_score(score)

            cur.execute(
                """INSERT INTO tennis_matches
                     (tourney_id, match_num, round, match_date, surface, best_of,
                      player_a_id, player_b_id, winner_id, player_a_rank, player_b_rank,
                      score, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (tourney_id, match_num) DO UPDATE SET
                     round = EXCLUDED.round, match_date = EXCLUDED.match_date,
                     surface = EXCLUDED.surface, best_of = EXCLUDED.best_of,
                     player_a_id = EXCLUDED.player_a_id, player_b_id = EXCLUDED.player_b_id,
                     winner_id = EXCLUDED.winner_id, player_a_rank = EXCLUDED.player_a_rank,
                     player_b_rank = EXCLUDED.player_b_rank, score = EXCLUDED.score,
                     status = EXCLUDED.status
                   RETURNING id""",
                (tourney_id, match_num, _str_or_none(getattr(r, "round", None)),
                 tdate, surface, best_of, a_id, b_id, w_id, a_rank, b_rank,
                 (score or "")[:60] or None, status),
            )
            match_id = cur.fetchone()[0]
            n_matches += 1

            if status == "completed":
                w_line = _serve_line(r, "w")
                l_line = _serve_line(r, "l")
                if w_line["serve_points"] is not None and l_line["serve_points"] is not None:
                    for pid, is_win, line in ((w_id, True, w_line), (l_id, False, l_line)):
                        cur.execute(
                            """INSERT INTO tennis_player_match_stats
                                 (match_id, player_id, is_winner, aces, double_faults,
                                  serve_points, first_in, first_won, second_won,
                                  serve_games, bp_saved, bp_faced)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               ON CONFLICT (match_id, player_id) DO NOTHING""",
                            (match_id, pid, is_win, line["aces"], line["double_faults"],
                             line["serve_points"], line["first_in"], line["first_won"],
                             line["second_won"], line["serve_games"], line["bp_saved"],
                             line["bp_faced"]),
                        )
                        n_stats += 1

    conn.commit()
    return (n_matches, n_stats)


def load_tml(start_year: int, end_year: int) -> dict:
    """Load matches + serve lines for each season in [start, end]. Players are
    derived from match rows (no separate players file)."""
    conn = get_connection()
    try:
        totals = {"matches": 0, "stats": 0, "years": []}
        for year in range(start_year, end_year + 1):
            m, s = _load_year(conn, year)
            totals["matches"] += m
            totals["stats"] += s
            totals["years"].append(year)
            print(f"[tennis-backfill] {year}: {m} matches, {s} serve lines")
        with conn.cursor() as cur:
            totals["players"] = cur.execute("SELECT count(*) FROM tennis_players").fetchone()[0]
        return totals
    finally:
        conn.close()
