"""Orchestration: load matches, replay Elo, compute skills, snapshot ratings.

Shared by the nightly `tennis-refresh-ratings` command and the walk-forward
backtest (which replays the same EloEngine match-by-match).
"""
from __future__ import annotations

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
        "SELECT id, match_date, surface, best_of, round, status, "
        "       player_a_id, player_b_id, winner_id, player_a_rank, player_b_rank, score "
        "FROM tennis_matches WHERE winner_id IS NOT NULL"
    )
    params: list = []
    if end is not None:
        sql += " AND match_date <= %s"
        params.append(end)
    rows = conn.execute(sql, params).fetchall()
    matches = []
    for (mid, mdate, surface, best_of, rnd, status, a_id, b_id, w_id, a_rank, b_rank, score) in rows:
        loser_id = b_id if w_id == a_id else a_id
        matches.append({
            "id": mid, "date": mdate, "surface": surface, "best_of": best_of,
            "round": rnd, "status": status, "player_a_id": a_id, "player_b_id": b_id,
            "winner_id": w_id, "loser_id": loser_id,
            "player_a_rank": a_rank, "player_b_rank": b_rank, "score": score,
        })
    matches.sort(key=lambda m: (m["date"], round_rank(m["round"]), m["id"]))
    return matches


def replay_elo(matches: list[dict]) -> EloEngine:
    """Replay results through a fresh EloEngine (only ELO_STATUSES count)."""
    engine = EloEngine()
    for m in matches:
        if m["status"] in ELO_STATUSES:
            engine.update(m["winner_id"], m["loser_id"], m["surface"])
    return engine


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
