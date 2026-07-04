"""Layer 3 — outcome-grounded aggregation.

Once agent recommendations are graded (score_recs.py), this aggregates the agent's REAL decision
quality against the app's built-in ground truth: hit rate, average CLV, fractional-unit ROI, and —
the key one — a Brier score on the JUDGE'S stated confidence vs the realized outcome. Brier asks
"does the agent know when it's right?", which a fluent-but-miscalibrated agent fails. This is the
metric most portfolio agents can't produce, because their domain has no ground truth; Diamond's
does.
"""
from __future__ import annotations


def _american_to_decimal(american: int) -> float:
    return 1.0 + (american / 100.0 if american >= 0 else 100.0 / -american)


def aggregate(conn, since_days: int | None = None) -> dict:
    """Aggregate graded agent_recommendations. since_days limits to a recent window (None = all)."""
    where = "WHERE scored_at IS NOT NULL"
    params: tuple = ()
    if since_days is not None:
        where += " AND slate_date >= (CURRENT_DATE - %s::int)"
        params = (since_days,)
    rows = conn.execute(
        f"""
        SELECT won, clv, confidence, price_american, stake_units
        FROM agent_recommendations {where}
        """,
        params,
    ).fetchall()

    graded = [r for r in rows if r[0] is not None]  # exclude pushes/voids from win/ROI
    n = len(graded)
    wins = sum(1 for r in graded if r[0])

    # ROI in units: won -> +stake*(dec-1), lost -> -stake. Default 1 unit when stake unset.
    staked = profit = 0.0
    for won, _clv, _conf, price, stake in graded:
        s = float(stake) if stake is not None else 1.0
        staked += s
        if price is None:
            continue
        profit += s * (_american_to_decimal(int(price)) - 1.0) if won else -s

    clvs = [float(r[1]) for r in rows if r[1] is not None]
    avg_clv = sum(clvs) / len(clvs) if clvs else None

    # Brier on the judge's confidence vs realized win (lower is better; 0.25 = coin flip).
    briers = [(float(c) - (1.0 if w else 0.0)) ** 2
              for w, _clv, c, _p, _s in graded if c is not None]
    brier = sum(briers) / len(briers) if briers else None

    return {
        "graded": n,
        "hit_rate": round(wins / n, 4) if n else None,
        "avg_clv": round(avg_clv, 4) if avg_clv is not None else None,
        "roi": round(profit / staked, 4) if staked else None,
        "brier": round(brier, 4) if brier is not None else None,
        "clv_n": len(clvs),
        "brier_n": len(briers),
    }
