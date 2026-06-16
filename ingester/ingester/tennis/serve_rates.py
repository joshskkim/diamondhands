"""Serve-outcome rates for the ace / double-fault prop model.

Per player, recency-weighted and regressed to the tour mean:
  ace_rate     = aces / serve_points          (server skill)
  df_rate      = double_faults / serve_points  (server)
  ace_against  = aces faced / return_points    (returner — how aceable they are)

A player's projected aces in a match = opponent-adjusted ace_rate × expected serve
points (derived from the projected match length). Mirrors skills.py / SPW-RPW.
"""
from __future__ import annotations

from datetime import date

SERVE_HALFLIFE_DAYS = 365.0
SERVE_PRIOR_POINTS = 300.0
# Average points per service game — converts projected games to serve points.
AVG_POINTS_PER_SERVICE_GAME = 6.1


def _decay(age_days: float) -> float:
    return 0.5 ** (age_days / SERVE_HALFLIFE_DAYS) if age_days >= 0 else 0.0


def build_serve_rates(conn, as_of: date) -> tuple[dict[str, dict], dict]:
    """Return ({player: {ace_rate, df_rate, ace_against, n}}, league_means)."""
    rows = conn.execute(
        """
        SELECT m.match_date, s.player_id,
               COALESCE(s.aces,0) AS aces, COALESCE(s.double_faults,0) AS df,
               s.serve_points AS svpt,
               COALESCE(o.aces,0) AS opp_aces, o.serve_points AS opp_svpt
        FROM tennis_player_match_stats s
        JOIN tennis_player_match_stats o
          ON o.match_id = s.match_id AND o.player_id <> s.player_id
        JOIN tennis_matches m ON m.id = s.match_id
        WHERE m.match_date <= %s AND s.serve_points > 0 AND o.serve_points > 0
        """,
        (as_of,),
    ).fetchall()

    acc: dict[str, dict] = {}
    tot_ace = tot_df = tot_sp = 0.0
    for match_date, pid, aces, df, svpt, opp_aces, opp_svpt in rows:
        w = _decay((as_of - match_date).days)
        if w <= 0:
            continue
        a = acc.setdefault(pid, {"ace": 0.0, "df": 0.0, "sp": 0.0, "faced": 0.0, "ret": 0.0, "n": 0})
        a["ace"] += w * aces
        a["df"] += w * df
        a["sp"] += w * svpt
        a["faced"] += w * opp_aces
        a["ret"] += w * opp_svpt
        a["n"] += 1
        tot_ace += w * aces
        tot_df += w * df
        tot_sp += w * svpt

    league = {
        "ace_rate": tot_ace / tot_sp if tot_sp else 0.06,
        "df_rate": tot_df / tot_sp if tot_sp else 0.03,
    }
    out: dict[str, dict] = {}
    for pid, a in acc.items():
        if a["sp"] <= 0 or a["ret"] <= 0:
            continue
        out[pid] = {
            "ace_rate": (a["ace"] + SERVE_PRIOR_POINTS * league["ace_rate"]) / (a["sp"] + SERVE_PRIOR_POINTS),
            "df_rate": (a["df"] + SERVE_PRIOR_POINTS * league["df_rate"]) / (a["sp"] + SERVE_PRIOR_POINTS),
            "ace_against": (a["faced"] + SERVE_PRIOR_POINTS * league["ace_rate"]) / (a["ret"] + SERVE_PRIOR_POINTS),
            "n": a["n"],
        }
    return out, league


def serve_points(exp_total_games: float) -> float:
    """Expected serve points for ONE player (serves ~half the games)."""
    return (exp_total_games / 2.0) * AVG_POINTS_PER_SERVICE_GAME


def project_aces(rate_server: dict, rate_returner: dict, league: dict, exp_total_games: float) -> float:
    """Opponent-adjusted expected aces for the server."""
    adj = rate_server["ace_rate"] * (rate_returner["ace_against"] / league["ace_rate"])
    return adj * serve_points(exp_total_games)


def project_dfs(rate_server: dict, exp_total_games: float) -> float:
    """Expected double faults (server-only)."""
    return rate_server["df_rate"] * serve_points(exp_total_games)
