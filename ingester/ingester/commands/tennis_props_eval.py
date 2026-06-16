"""tennis-props-eval: validation gate for the ace / double-fault prop model.

Build serve rates as-of a cutoff, then on later matches predict each player's aces
(opponent-adjusted) and double faults from their ACTUAL serve points (isolating the
rate model from the match-length estimate) and compare to actuals. Reports MAE/bias
and PIT calibration under a Poisson count (to expose over/under-dispersion) — so we
only build the prop market if the projection is trustworthy."""
from __future__ import annotations

import argparse
from datetime import date

from scipy.stats import nbinom, poisson

from ingester.db import eastern_today, get_connection
from ingester.tennis.serve_rates import build_serve_rates


def _poisson_pit(actual: int, mean: float) -> float:
    return float(poisson.cdf(actual - 1, mean) + 0.5 * poisson.pmf(actual, mean))


def _nbinom_pit(actual: int, mean: float, phi: float) -> float:
    # NB with mean μ and variance φμ -> size r = μ/(φ−1), prob p = r/(r+μ)
    r = mean / (phi - 1.0)
    p = r / (r + mean)
    return float(nbinom.cdf(actual - 1, r, p) + 0.5 * nbinom.pmf(actual, r, p))


def _hist(pits: list[float]) -> tuple[list[int], int, int]:
    bins = [0] * 10
    c50 = c80 = 0
    for pit in pits:
        bins[min(int(pit * 10), 9)] += 1
        if 0.25 <= pit < 0.75:
            c50 += 1
        if 0.10 <= pit < 0.90:
            c80 += 1
    return bins, c50, c80


def _report(name: str, samples: list[tuple[int, float]]) -> None:
    n = len(samples)
    if n == 0:
        print(f"  {name}: no samples")
        return
    mae = sum(abs(m - a) for a, m in samples) / n
    bias = sum(m - a for a, m in samples) / n
    # dispersion φ = E[(actual−mean)²/mean]  (>1 means overdispersed vs Poisson)
    phi = max(1.05, sum((a - m) ** 2 / m for a, m in samples) / n)
    pois = [_poisson_pit(a, m) for a, m in samples]
    nb = [_nbinom_pit(a, m, phi) for a, m in samples]
    pb, pc50, pc80 = _hist(pois)
    nbb, nc50, nc80 = _hist(nb)
    print(f"  {name}: N={n}  MAE={mae:.2f}  bias={bias:+.2f}  phi={phi:.2f}")
    print(f"    Poisson PIT central50={pc50/n:.3f} central80={pc80/n:.3f}  "
          + " ".join(f"{c/n:.2f}" for c in pb))
    print(f"    NB(phi)  PIT central50={nc50/n:.3f} central80={nc80/n:.3f}  "
          + " ".join(f"{c/n:.2f}" for c in nbb))


def cmd_tennis_props_eval(args: argparse.Namespace) -> None:
    cutoff = args.cutoff or date(2024, 12, 31)
    end = args.end or eastern_today()

    conn = get_connection()
    try:
        rates, league = build_serve_rates(conn, cutoff)
        rows = conn.execute(
            """
            SELECT s.player_id AS server, o.player_id AS returner,
                   COALESCE(s.aces,0) AS aces, COALESCE(s.double_faults,0) AS df,
                   s.serve_points AS svpt
            FROM tennis_player_match_stats s
            JOIN tennis_player_match_stats o
              ON o.match_id = s.match_id AND o.player_id <> s.player_id
            JOIN tennis_matches m ON m.id = s.match_id
            WHERE m.match_date > %s AND m.match_date <= %s AND s.serve_points > 0
            """,
            (cutoff, end),
        ).fetchall()
    finally:
        conn.close()

    samples: dict[str, list[tuple[int, float]]] = {"aces": [], "dfs": []}
    for server, returner, aces, df, svpt in rows:
        rs = rates.get(server)
        rr = rates.get(returner)
        if rs is None or rr is None:
            continue
        ace_mean = rs["ace_rate"] * (rr["ace_against"] / league["ace_rate"]) * svpt
        df_mean = rs["df_rate"] * svpt
        if ace_mean > 0:
            samples["aces"].append((aces, ace_mean))
        if df_mean > 0:
            samples["dfs"].append((df, df_mean))

    print(f"[tennis-props-eval] rates as-of {cutoff}; eval {cutoff}..{end} "
          f"(league ace_rate={league['ace_rate']:.3f} df_rate={league['df_rate']:.3f})")
    for key in ("aces", "dfs"):
        _report(key, samples[key])
