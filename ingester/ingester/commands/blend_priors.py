"""blend-priors: ensemble the per-system priors into a single method='blend' prior.

For each metric (proj_xwoba, proj_k_rate, proj_iso) we take a per-metric weighted
mean across the projection systems that cover a player, re-normalising the weights
over only the systems actually present for that player. Marcel is one ensemble
member AND the universal fallback: players no external system covers fall back to
their Marcel prior (weight renormalises to 1), and players no Marcel covers (e.g.
rookies with a Steamer line) still get the blend of whatever systems have them.

Weights come from models/prior_blend.json (written by tune-prior-blend). When that
file is absent we use provisional DEFAULT_WEIGHTS — sensible but unfitted; ISO is
tilted toward THE BAT X (Statcast power), K%/wOBA lean on the blend systems.

refresh-skills --prior-method blend then regresses in-season rates toward this row.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ingester.db import eastern_today, get_connection

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"
WEIGHTS_PATH = MODELS_DIR / "prior_blend.json"

# Provisional weights, used until tune-prior-blend fits real ones. Keys are
# batter_projection_prior.method values; only methods present for a player count
# (weights renormalize over present systems). Independent base systems (marcel,
# steamer, zips, thebatx, thebat, oopsy) carry the bulk (~0.70); the two aggregates
# (atc, fangraphsdc) split the rest (~0.30) — kept modest because they repackage the
# base systems and would otherwise double-count. ISO tilts toward THE BAT X (Statcast
# power). Each metric sums to 1.0.
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    "xwoba":  {"marcel": 0.10, "steamer": 0.18, "zips": 0.15, "thebatx": 0.12,
               "thebat": 0.05, "oopsy": 0.10, "atc": 0.15, "fangraphsdc": 0.15},
    "k_rate": {"marcel": 0.10, "steamer": 0.18, "zips": 0.15, "thebatx": 0.10,
               "thebat": 0.07, "oopsy": 0.10, "atc": 0.15, "fangraphsdc": 0.15},
    "iso":    {"marcel": 0.09, "steamer": 0.12, "zips": 0.10, "thebatx": 0.25,
               "thebat": 0.06, "oopsy": 0.08, "atc": 0.15, "fangraphsdc": 0.15},
}

# proj_pa isn't blended — take a real playing-time forecast in this priority order.
# Depth Charts leads: its manual playing-time forecasts are the strongest available.
_PA_PRIORITY = ("fangraphsdc", "atc", "steamer", "zips", "thebatx", "thebat", "oopsy", "marcel")

_METRIC_COL = {"xwoba": "proj_xwoba", "k_rate": "proj_k_rate", "iso": "proj_iso"}


def load_weights() -> dict[str, dict[str, float]]:
    if WEIGHTS_PATH.exists():
        return json.loads(WEIGHTS_PATH.read_text())
    return DEFAULT_WEIGHTS


def _weighted(values: dict[str, float], weights: dict[str, float]) -> float | None:
    """Weighted mean over methods present in both `values` and `weights`."""
    num = sum(weights[m] * v for m, v in values.items() if m in weights)
    den = sum(weights[m] for m in values if m in weights)
    return num / den if den > 0 else None


def blend_player(
    by_method: dict[str, dict[str, float | int | None]],
    weights: dict[str, dict[str, float]],
) -> dict[str, float | int] | None:
    """Blend one player's per-method rows into a single set of metrics.

    `by_method` maps method -> {xwoba, k_rate, iso, pa}. Returns the blended
    metrics + proj_pa, or None if no metric could be blended.
    """
    out: dict[str, float | int] = {}
    for metric, w in weights.items():
        present = {
            m: float(row[metric])
            for m, row in by_method.items()
            if row.get(metric) is not None
        }
        blended = _weighted(present, w)
        if blended is not None:
            out[metric] = round(blended, 4)

    if not out:
        return None

    for m in _PA_PRIORITY:
        if m in by_method and by_method[m].get("pa"):
            out["pa"] = int(by_method[m]["pa"])
            break
    out.setdefault("pa", 0)
    return out


def cmd_blend_priors(args: argparse.Namespace) -> None:
    season: int = args.season
    weights = load_weights()
    source = "models/prior_blend.json" if WEIGHTS_PATH.exists() else "DEFAULT_WEIGHTS (unfitted)"

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT player_id, method, proj_xwoba, proj_k_rate, proj_iso, proj_pa
        FROM batter_projection_prior
        WHERE season = %s AND method <> 'blend'
        """,
        (season,),
    ).fetchall()

    by_player: dict[int, dict[str, dict[str, float | int | None]]] = {}
    for pid, method, xwoba, k_rate, iso, pa in rows:
        by_player.setdefault(int(pid), {})[method] = {
            "xwoba": float(xwoba) if xwoba is not None else None,
            "k_rate": float(k_rate) if k_rate is not None else None,
            "iso": float(iso) if iso is not None else None,
            "pa": int(pa) if pa is not None else None,
        }

    blended: list[dict] = []
    for pid, by_method in by_player.items():
        b = blend_player(by_method, weights)
        if b is None or "xwoba" not in b or "k_rate" not in b or "iso" not in b:
            continue
        blended.append({
            "player_id": pid, "season": season,
            "proj_xwoba": b["xwoba"], "proj_k_rate": b["k_rate"],
            "proj_iso": b["iso"], "proj_pa": b["pa"],
        })

    with conn.cursor() as cur:
        for row in blended:
            cur.execute(
                """
                INSERT INTO batter_projection_prior
                    (player_id, season, proj_xwoba, proj_k_rate, proj_iso, proj_pa,
                     method, updated_at)
                VALUES (%(player_id)s, %(season)s, %(proj_xwoba)s, %(proj_k_rate)s,
                        %(proj_iso)s, %(proj_pa)s, 'blend', NOW())
                ON CONFLICT (player_id, season, method) DO UPDATE SET
                    proj_xwoba=EXCLUDED.proj_xwoba, proj_k_rate=EXCLUDED.proj_k_rate,
                    proj_iso=EXCLUDED.proj_iso, proj_pa=EXCLUDED.proj_pa,
                    updated_at=NOW()
                """,
                row,
            )
    conn.commit()
    conn.close()
    print(
        f"[blend-priors] Wrote {len(blended)} 'blend' priors for {season} "
        f"from {len(by_player)} players (weights: {source}). "
        f"Use refresh-skills --prior-method blend to regress toward them."
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--season", type=int, default=eastern_today().year,
        help="Target season year (default: current season)",
    )
