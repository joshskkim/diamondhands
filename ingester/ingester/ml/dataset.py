"""build-training-data: turn each historical batter-game into a leakage-safe feature row.

Reads batter-games from player_game_stats (PA>0), derives the opposing starter and the
confirmed lineup slot, builds point-in-time features via ml.features.build_feature_row
(as-of the game date), attaches the four market labels plus raw counts, and writes
ingester/models/training_<season>.parquet.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from ingester.db import get_connection
from ingester.ml.features import FEATURE_COLUMNS, build_feature_row
from ingester.projection.park_adj import ParkFactors

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

_ROWS_SQL = """
    SELECT
        pgs.player_id, pgs.game_id, pgs.game_date, pgs.is_home,
        pgs.hits, pgs.home_runs, pgs.strikeouts, pgs.total_bases,
        pgs.plate_appearances, pgs.walks,
        COALESCE(b.bats, 'R') AS bats,
        CASE WHEN pgs.is_home THEN g.away_probable_pitcher_id
             ELSE g.home_probable_pitcher_id END AS opp_pid,
        gl.batting_order AS lineup_position,
        COALESCE(s.park_factor_hits, 1.0)  AS pf_hits,
        COALESCE(s.park_factor_hr_lhb, 1.0) AS pf_hr_lhb,
        COALESCE(s.park_factor_hr_rhb, 1.0) AS pf_hr_rhb
    FROM player_game_stats pgs
    JOIN games g    ON g.id = pgs.game_id
    JOIN players b  ON b.id = pgs.player_id
    LEFT JOIN stadiums s ON s.id = g.stadium_id
    LEFT JOIN game_lineups gl ON gl.game_id = pgs.game_id AND gl.player_id = pgs.player_id
    WHERE EXTRACT(YEAR FROM pgs.game_date) = %s
      AND pgs.plate_appearances > 0
    ORDER BY pgs.game_date
"""

_LABEL_COLUMNS = ("h1", "h2", "hr", "k", "hits", "total_bases", "game_date",
                  "pa", "n_k", "n_bb", "n_hr", "n_hit")


def build_dataset(conn, season: int) -> pd.DataFrame:
    throws = {
        int(r[0]): (r[1] or "R")
        for r in conn.execute("SELECT id, throws FROM players").fetchall()
    }
    raw = conn.execute(_ROWS_SQL, (season,)).fetchall()
    rows: list[dict] = []
    skipped_no_pitcher = skipped_no_snapshot = 0

    for i, r in enumerate(raw, 1):
        (player_id, game_id, game_date, is_home, hits, home_runs, strikeouts,
         total_bases, plate_appearances, walks, bats, opp_pid, lineup_position,
         pf_hits, pf_hr_lhb, pf_hr_rhb) = r
        if opp_pid is None:
            skipped_no_pitcher += 1
            continue
        feat = build_feature_row(
            conn,
            batter_id=int(player_id), bats=str(bats),
            opposing_pitcher_id=int(opp_pid), pitcher_throws=throws.get(int(opp_pid), "R"),
            lineup_position=(int(lineup_position) if lineup_position is not None else None),
            is_home=bool(is_home),
            park=ParkFactors(float(pf_hits), float(pf_hr_lhb), float(pf_hr_rhb)),
            as_of_date=game_date, season=season,
        )
        if feat is None:
            skipped_no_snapshot += 1
            continue
        feat.update(
            h1=int(hits >= 1), h2=int(hits >= 2), hr=int(home_runs >= 1),
            k=int(strikeouts >= 1), hits=int(hits), total_bases=int(total_bases),
            game_date=pd.Timestamp(game_date),
            pa=int(plate_appearances), n_k=int(strikeouts), n_bb=int(walks or 0),
            n_hr=int(home_runs), n_hit=int(hits),
        )
        rows.append(feat)
        if i % 5000 == 0:
            print(f"  …{i}/{len(raw)} scanned, {len(rows)} rows built")

    print(
        f"[build-training-data] {season}: {len(rows)} rows "
        f"(skipped {skipped_no_pitcher} no-probable-pitcher, {skipped_no_snapshot} no-snapshot)"
    )
    df = pd.DataFrame(rows, columns=list(FEATURE_COLUMNS) + list(_LABEL_COLUMNS))
    return df


def cmd_build_training_data(args: argparse.Namespace) -> None:
    seasons = args.season or [2025]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        for season in seasons:
            print(f"[build-training-data] Building feature rows for {season}…")
            df = build_dataset(conn, season)
            out = MODELS_DIR / f"training_{season}.parquet"
            df.to_parquet(out, index=False)
            base = {lbl: round(df[lbl].mean(), 4) for lbl in ("h1", "h2", "hr", "k")}
            print(f"  → wrote {out}  ({len(df)} rows)  base rates: {base}")
    finally:
        conn.close()
