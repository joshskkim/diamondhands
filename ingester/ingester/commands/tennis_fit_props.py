"""tennis-fit-props: fit the ace/DF Negative-Binomial dispersion φ on the FULL
production pipeline (fresh walk-forward win prob -> projected games -> ESTIMATED
serve points -> serve-rate means), so the stored φ reflects the variance the live
market actually faces. Saves models/tennis_props.json."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date

from ingester.db import get_connection
from ingester.tennis.elo import EloEngine
from ingester.tennis.games_calibration import GamesCalibrator
from ingester.tennis.match_model import project_from_winprob
from ingester.tennis.props import fit_market, save
from ingester.tennis.ratings import ELO_STATUSES, load_matches
from ingester.tennis.serve_rates import build_serve_rates, serve_points


def cmd_tennis_fit_props(args: argparse.Namespace) -> None:
    cutoff = args.cutoff or date(2023, 12, 31)

    conn = get_connection()
    try:
        rates, league = build_serve_rates(conn, cutoff)
        matches = load_matches(conn)
        serve_by_match: dict[int, dict[str, tuple]] = defaultdict(dict)
        for mid, pid, aces, df in conn.execute(
            "SELECT match_id, player_id, COALESCE(aces,0), COALESCE(double_faults,0) "
            "FROM tennis_player_match_stats"
        ).fetchall():
            serve_by_match[mid][pid] = (aces, df)
    finally:
        conn.close()

    games_cal = GamesCalibrator.load()
    engine = EloEngine()
    ace_samples: list[tuple[int, float]] = []
    df_samples: list[tuple[int, float]] = []

    for m in matches:
        if m["status"] not in ELO_STATUSES or not m["winner_id"]:
            continue
        a, b, surface = m["player_a_id"], m["player_b_id"], m["surface"]
        if m["date"] > cutoff and m["status"] == "completed":
            best_of = m["best_of"] or 3
            exp = project_from_winprob(engine.win_prob(a, b, surface), best_of, surface)["exp_total_games"]
            if games_cal is not None:
                exp = games_cal.mean(exp)
            sp = serve_points(exp)
            lines = serve_by_match.get(m["id"], {})
            for server, returner in ((a, b), (b, a)):
                rs, rr = rates.get(server), rates.get(returner)
                actual = lines.get(server)
                if rs is None or rr is None or actual is None:
                    continue
                ace_mean = rs["ace_rate"] * (rr["ace_against"] / league["ace_rate"]) * sp
                df_mean = rs["df_rate"] * sp
                if ace_mean > 0:
                    ace_samples.append((actual[0], ace_mean))
                if df_mean > 0:
                    df_samples.append((actual[1], df_mean))
        engine.update(m["winner_id"], m["loser_id"], surface)

    if len(ace_samples) < 500:
        print(f"[tennis-fit-props] only {len(ace_samples)} samples — too few")
        return

    raw_bias = lambda s: sum(m - a for a, m in s) / len(s)  # noqa: E731
    params = {"aces": fit_market(ace_samples), "dfs": fit_market(df_samples)}
    path = save(params)
    cal_bias = lambda s, p: sum((p["a"] + p["b"] * m) - a for a, m in s) / len(s)  # noqa: E731
    print(f"[tennis-fit-props] cutoff {cutoff}, N={len(ace_samples)}; "
          f"aces {params['aces']} (raw bias {raw_bias(ace_samples):+.2f} -> {cal_bias(ace_samples, params['aces']):+.2f}); "
          f"dfs {params['dfs']} (raw bias {raw_bias(df_samples):+.2f} -> {cal_bias(df_samples, params['dfs']):+.2f}); saved {path}")
