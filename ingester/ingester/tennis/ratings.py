"""Orchestration: load matches, replay Elo, compute skills, snapshot ratings.

Shared by the nightly `tennis-refresh-ratings` command and the walk-forward
backtest (which replays the same EloEngine match-by-match).
"""
from __future__ import annotations

import statistics
from datetime import date

from ingester.tennis.constants import MODEL_VERSION, SURFACES
from ingester.tennis.elo import EloEngine, round_rank
from ingester.tennis.skills import build_skills

# Statuses whose result counts toward Elo (a retirement is still a result; a
# walkover/default involves no play and is excluded).
ELO_STATUSES = ("completed", "retired")


def load_matches(conn, end: date | None = None) -> list[dict]:
    """Matches in causal order (date, then round within tournament)."""
    sql = (
        "SELECT id, match_date, surface, best_of, round, status, tourney_id, "
        "       player_a_id, player_b_id, winner_id, player_a_rank, player_b_rank, score "
        "FROM tennis_matches WHERE winner_id IS NOT NULL"
    )
    params: list = []
    if end is not None:
        sql += " AND match_date <= %s"
        params.append(end)
    rows = conn.execute(sql, params).fetchall()
    matches = []
    for (mid, mdate, surface, best_of, rnd, status, tourney_id,
         a_id, b_id, w_id, a_rank, b_rank, score) in rows:
        loser_id = b_id if w_id == a_id else a_id
        matches.append({
            "id": mid, "date": mdate, "surface": surface, "best_of": best_of,
            "round": rnd, "status": status, "tourney_id": tourney_id,
            "player_a_id": a_id, "player_b_id": b_id,
            "winner_id": w_id, "loser_id": loser_id,
            "player_a_rank": a_rank, "player_b_rank": b_rank, "score": score,
        })
    matches.sort(key=lambda m: (m["date"], round_rank(m["round"]), m["id"]))
    return matches


def walk_forward_predictions(conn, start: date, end: date, min_matches: int = 10) -> list[tuple]:
    """Walk-forward, leak-free match-winner predictions in [start, end].

    Returns (match_date, surface, p_win_a, y) for each eval match where both players
    have >= min_matches of prior history. Shared by calibration fitting and the
    accuracy/score loop so the replay logic isn't duplicated."""
    matches = load_matches(conn)
    engine = EloEngine()
    out: list[tuple] = []
    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        n_a = engine.n_overall.get(a, 0)
        n_b = engine.n_overall.get(b, 0)
        if start <= m["date"] <= end and n_a >= min_matches and n_b >= min_matches:
            y = 1 if m["winner_id"] == a else 0
            out.append((m["date"], surface, engine.win_prob(a, b, surface), y))
        engine.update(m["winner_id"], m["loser_id"], surface)
    return out


def replay_elo(matches: list[dict]) -> EloEngine:
    """Replay results through a fresh EloEngine (only ELO_STATUSES count)."""
    engine = EloEngine()
    for m in matches:
        if m["status"] in ELO_STATUSES:
            engine.update(m["winner_id"], m["loser_id"], m["surface"])
    return engine


def compute_court_speed(conn, min_matches: int = 10) -> int:
    """Per-tournament serve environment (mean SPW), z-scored WITHIN surface so it
    captures venue speed *beyond* the surface bucket (a fast hard court vs a slow
    one), and write it to tennis_tournaments.court_speed_index. A venue property,
    so full-history aggregation is leak-safe."""
    rows = conn.execute(
        """
        SELECT t.id, t.surface,
               avg((COALESCE(s.first_won,0)+COALESCE(s.second_won,0))::numeric
                   / NULLIF(s.serve_points,0)) AS mean_spw,
               count(*) AS n
        FROM tennis_tournaments t
        JOIN tennis_matches m ON m.tourney_id = t.id
        JOIN tennis_player_match_stats s ON s.match_id = m.id
        WHERE s.serve_points > 0
        GROUP BY t.id, t.surface
        HAVING count(*) >= %s
        """,
        (min_matches,),
    ).fetchall()

    by_surface: dict[str, list[float]] = {}
    for _tid, surface, mean_spw, _n in rows:
        if mean_spw is not None:
            by_surface.setdefault(surface, []).append(float(mean_spw))
    stats = {
        s: (statistics.fmean(v), statistics.pstdev(v) or 1.0)
        for s, v in by_surface.items() if len(v) >= 3
    }

    updates = []
    for tid, surface, mean_spw, _n in rows:
        if mean_spw is None or surface not in stats:
            continue
        mu, sd = stats[surface]
        z = (float(mean_spw) - mu) / sd
        z = max(-3.5, min(3.5, z))
        updates.append((round(z, 3), tid))

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE tennis_tournaments SET court_speed_index = %s WHERE id = %s", updates
        )
    conn.commit()
    return len(updates)


def refresh_ratings(conn, as_of: date) -> dict:
    """Compute final Elo + skills as of `as_of` and snapshot them into
    tennis_player_ratings (replacing any existing rows for that date)."""
    matches = load_matches(conn, end=as_of)
    engine = replay_elo(matches)
    skills = build_skills(conn, as_of)

    players = set(engine.overall) | set(skills)
    rows = []
    for pid in players:
        elo_snap = engine.snapshot(pid)              # {'all':(elo,n), surface:(elo,n)}
        skill_snap = skills.get(pid, {})             # {'all':(spw,rpw,n), surface:...}
        for key in ("all", *SURFACES):
            elo = elo_snap.get(key)
            sk = skill_snap.get(key)
            if elo is None and sk is None:
                continue
            n = (elo[1] if elo else 0) or (sk[2] if sk else 0)
            rows.append((
                pid, as_of, key,
                round(elo[0], 2) if elo else None,
                round(sk[0], 4) if sk else None,
                round(sk[1], 4) if sk else None,
                n,
            ))

    with conn.cursor() as cur:
        cur.execute("DELETE FROM tennis_player_ratings WHERE as_of_date = %s", (as_of,))
        cur.executemany(
            """INSERT INTO tennis_player_ratings
                 (player_id, as_of_date, surface, elo, serve_skill, return_skill, matches_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            rows,
        )
    conn.commit()
    return {
        "as_of": as_of, "model_version": MODEL_VERSION,
        "players": len(players), "rating_rows": len(rows),
        "elo_matches": sum(1 for m in matches if m["status"] in ELO_STATUSES),
    }
