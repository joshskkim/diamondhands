"""tune-prior-blend: fit per-metric ensemble weights from realized outcomes.

For each metric (xwoba / k_rate / iso) we fit non-negative weights summing to 1
over the projection systems, minimising squared error between the weighted-blend
projection and the player's REALIZED season metric (a convex combination — the
systems are individually ~calibrated, so no intercept). Fitting uses complete
cases (players covered by every system) so the design matrix has no holes; the
fitted weights then renormalise per-player at blend time for partial coverage.
Writes models/prior_blend.json, which blend-priors reads.

LEAKAGE CAVEAT: FanGraphs' live numbers update in-season, so fitting on the same
season's actuals leaks (the projection partly "saw" those games). The honest use
is to fit on a completed season's PRESEASON projections vs that season's actuals,
or to freeze a pull and score go-forward games. Treat a same-season fit as
directional only — confirm any winner with the end-to-end backtest before adopting.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
from scipy.optimize import minimize

from ingester.db import get_connection
from ingester.fangraphs_api import SYSTEMS
from ingester.commands.blend_priors import MODELS_DIR, WEIGHTS_PATH

ALL_SYSTEMS = ("marcel", *SYSTEMS)
_METRICS = ("xwoba", "k_rate", "iso")
_MIN_PA = 200  # realized-sample floor for a player to enter the fit


def _load_projections(conn, season: int) -> dict[int, dict[str, dict[str, float]]]:
    rows = conn.execute(
        """
        SELECT player_id, method, proj_xwoba, proj_k_rate, proj_iso
        FROM batter_projection_prior
        WHERE season = %s AND method <> 'blend'
        """,
        (season,),
    ).fetchall()
    out: dict[int, dict[str, dict[str, float]]] = {}
    for pid, method, xwoba, k_rate, iso in rows:
        out.setdefault(int(pid), {})[method] = {
            "xwoba": float(xwoba) if xwoba is not None else None,
            "k_rate": float(k_rate) if k_rate is not None else None,
            "iso": float(iso) if iso is not None else None,
        }
    return out


def _load_realized(conn, season: int) -> dict[int, dict[str, float]]:
    rows = conn.execute(
        """
        SELECT
            player_id,
            SUM(plate_appearances)                                             AS pa,
            SUM(at_bats)                                                       AS ab,
            SUM(hits)                                                          AS hits,
            SUM(total_bases)                                                   AS tb,
            SUM(strikeouts)                                                    AS k,
            SUM(xwoba * plate_appearances) / NULLIF(SUM(plate_appearances), 0) AS xwoba
        FROM player_game_stats
        WHERE EXTRACT(YEAR FROM game_date) = %s
          AND plate_appearances IS NOT NULL
        GROUP BY player_id
        HAVING SUM(plate_appearances) >= %s
        """,
        (season, _MIN_PA),
    ).fetchall()
    out: dict[int, dict[str, float]] = {}
    for pid, pa, ab, hits, tb, k, xwoba in rows:
        pa, ab = int(pa or 0), int(ab or 0)
        if pa == 0 or ab == 0 or xwoba is None:
            continue
        out[int(pid)] = {
            "xwoba": float(xwoba),
            "k_rate": int(k or 0) / pa,
            "iso": (int(tb or 0) - int(hits or 0)) / ab,
        }
    return out


def _fit_metric(A: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Min ||A w - b||^2 s.t. w >= 0, sum(w) = 1 (SLSQP, equal-weight start)."""
    n = A.shape[1]
    w0 = np.full(n, 1.0 / n)
    res = minimize(
        lambda w: float(np.sum((A @ w - b) ** 2)),
        w0,
        method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=[{"type": "eq", "fun": lambda w: float(np.sum(w) - 1.0)}],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    return res.x


def _rmse(pred: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((pred - b) ** 2)))


def cmd_tune_prior_blend(args: argparse.Namespace) -> None:
    season: int = args.season
    systems = [s.strip() for s in args.systems.split(",") if s.strip()]

    conn = get_connection()
    proj = _load_projections(conn, season)
    realized = _load_realized(conn, season)
    conn.close()

    weights: dict[str, dict[str, float]] = {}
    for metric in _METRICS:
        rows_A, rows_b = [], []
        for pid, real in realized.items():
            pp = proj.get(pid)
            if not pp:
                continue
            vals = [pp.get(s, {}).get(metric) for s in systems]
            if any(v is None for v in vals):
                continue  # complete cases only
            rows_A.append(vals)
            rows_b.append(real[metric])
        if len(rows_A) < len(systems) * 5:
            print(f"[tune-prior-blend] {metric}: too few complete cases "
                  f"({len(rows_A)}) — keeping equal weights")
            weights[metric] = {s: round(1.0 / len(systems), 4) for s in systems}
            continue

        A = np.array(rows_A, dtype=float)
        b = np.array(rows_b, dtype=float)
        w = _fit_metric(A, b)
        weights[metric] = {s: round(float(wi), 4) for s, wi in zip(systems, w)}

        blend_rmse = _rmse(A @ w, b)
        singles = {s: _rmse(A[:, i], b) for i, s in enumerate(systems)}
        best_single = min(singles, key=singles.get)
        print(
            f"[tune-prior-blend] {metric} (n={len(b)}): "
            f"blend RMSE {blend_rmse:.5f} vs best single {best_single} "
            f"{singles[best_single]:.5f} | weights "
            + ", ".join(f"{s}={weights[metric][s]:.2f}" for s in systems)
        )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps(weights, indent=2))
    print(
        f"[tune-prior-blend] Wrote {WEIGHTS_PATH}. "
        f"NOTE: same-season fits leak (see module docstring) — validate with backtest."
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--season", type=int, default=2025,
        help="Season whose projections+actuals to fit on (default: 2025)",
    )
    parser.add_argument(
        "--systems", default=",".join(ALL_SYSTEMS),
        help=f"Systems to weight (default: {','.join(ALL_SYSTEMS)})",
    )
