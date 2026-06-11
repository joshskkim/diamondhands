"""ingest-steamer: load a FanGraphs Steamer projection CSV into batter_projection_prior.

Steamer (or any export in the same shape) becomes the model's true-talent prior via the
existing ProjectionPrior seam — refresh-skills regresses each player's in-season rates
toward batter_projection_prior regardless of how it was filled, so Steamer rows
(method='steamer') simply overlay the in-house Marcel rows for the players they cover.

Get the CSV from the FanGraphs projections leaderboard:
    Projections → Steamer → Batters → "Export Data".
If the export includes an MLBAMID column it is matched directly (players.id is the MLBAM
id); otherwise rows are matched by accent/punraw-stripped name.

Column mapping (case-insensitive, tolerant of the usual FanGraphs headers):
    proj_xwoba ← wOBA          (projected wOBA; same scale our model drives hit rate on)
    proj_k_rate ← SO / PA      (or a K% column if SO is absent)
    proj_iso    ← ISO          (or SLG − AVG)
    proj_pa     ← PA           (Steamer's playing-time forecast — a real PA projection)
"""
from __future__ import annotations

import argparse
import re
import unicodedata

import pandas as pd

from ingester.db import get_connection


def _norm_name(name: str) -> str:
    """Lowercase, strip accents and punctuation, collapse spaces (name matching)."""
    decomposed = unicodedata.normalize("NFKD", str(name))
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = re.sub(r"[^a-z0-9 ]", "", ascii_only.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _find_col(cols: dict[str, str], *candidates: str) -> str | None:
    """Return the real header whose lowercased name matches a candidate, else None."""
    for cand in candidates:
        if cand in cols:
            return cols[cand]
    return None


def _to_rate(value) -> float | None:
    """Parse a number that may be a fraction (0.225) or a percent ('22.5%' / 22.5)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip().replace("%", "")
    if not s:
        return None
    v = float(s)
    return v / 100.0 if v > 1.0 else v


def cmd_ingest_steamer(args: argparse.Namespace) -> None:
    season: int = args.season
    method: str = getattr(args, "method", "steamer")
    path: str = args.csv

    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}

    c_name = _find_col(cols, "name", "playername", "player")
    c_mlbam = _find_col(cols, "mlbamid", "mlbam", "mlb_id", "mlbid")
    c_woba = _find_col(cols, "woba")
    c_pa = _find_col(cols, "pa")
    c_so = _find_col(cols, "so", "k")
    c_kpct = _find_col(cols, "k%", "kpct", "k_pct")
    c_iso = _find_col(cols, "iso")
    c_slg = _find_col(cols, "slg")
    c_avg = _find_col(cols, "avg")

    if c_woba is None or c_pa is None or (c_mlbam is None and c_name is None):
        raise SystemExit(
            "[ingest-steamer] CSV missing required columns (need wOBA, PA, and "
            "MLBAMID or Name). Found: " + ", ".join(df.columns)
        )

    conn = get_connection()
    known_ids = {int(r[0]) for r in conn.execute("SELECT id FROM players").fetchall()}
    by_name: dict[str, int] = {}
    ambiguous: set[str] = set()
    for pid, full in conn.execute("SELECT id, full_name FROM players").fetchall():
        key = _norm_name(full)
        if key in by_name and by_name[key] != pid:
            ambiguous.add(key)  # same normalized name → only an MLBAMID can disambiguate
        by_name[key] = int(pid)

    rows: list[dict] = []
    unmatched = 0
    for _, r in df.iterrows():
        pid = None
        if c_mlbam is not None and not pd.isna(r[c_mlbam]):
            cand = int(r[c_mlbam])
            if cand in known_ids:
                pid = cand
        if pid is None and c_name is not None:
            key = _norm_name(r[c_name])
            if key in by_name and key not in ambiguous:
                pid = by_name[key]
        if pid is None:
            unmatched += 1
            continue

        pa = int(r[c_pa]) if not pd.isna(r[c_pa]) else 0
        woba = float(r[c_woba]) if not pd.isna(r[c_woba]) else None
        if c_so is not None and pa > 0 and not pd.isna(r[c_so]):
            k_rate = float(r[c_so]) / pa
        else:
            k_rate = _to_rate(r[c_kpct]) if c_kpct is not None else None
        if c_iso is not None and not pd.isna(r[c_iso]):
            iso = float(r[c_iso])
        elif c_slg is not None and c_avg is not None and not pd.isna(r[c_slg]):
            iso = float(r[c_slg]) - float(r[c_avg])
        else:
            iso = None
        if woba is None or k_rate is None or iso is None:
            unmatched += 1
            continue

        rows.append({
            "player_id": pid, "season": season,
            "proj_xwoba": round(woba, 4), "proj_k_rate": round(k_rate, 4),
            "proj_iso": round(iso, 4), "proj_pa": pa, "method": method,
        })

    with conn.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO batter_projection_prior
                    (player_id, season, proj_xwoba, proj_k_rate, proj_iso, proj_pa,
                     method, updated_at)
                VALUES (%(player_id)s, %(season)s, %(proj_xwoba)s, %(proj_k_rate)s,
                        %(proj_iso)s, %(proj_pa)s, %(method)s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    proj_xwoba=EXCLUDED.proj_xwoba, proj_k_rate=EXCLUDED.proj_k_rate,
                    proj_iso=EXCLUDED.proj_iso, proj_pa=EXCLUDED.proj_pa,
                    method=EXCLUDED.method, updated_at=NOW()
                """,
                row,
            )
    conn.commit()
    conn.close()
    print(
        f"[ingest-steamer] Wrote {len(rows)} '{method}' priors for {season} "
        f"({unmatched} rows unmatched/incomplete). They overlay the Marcel rows; "
        f"re-running refresh-priors would overwrite them, so ingest Steamer last."
    )
