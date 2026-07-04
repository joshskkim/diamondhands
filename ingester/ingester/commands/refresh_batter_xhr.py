"""refresh-batter-xhr: aggregate the learned xHR model to a per-batter true-talent rate.

Scores every batter's balls in play (batted_ball_events) with the xHR model
PARK-NEUTRAL (park held constant so a hitter's home park can't inflate his true
power — and so the projection's park.hr multiplier isn't double-counted later),
averages to expected-HR-per-batted-ball, and empirical-Bayes regresses toward the
league xHR rate by sample size. Writes batter_xhr, keyed by the season measured FROM
(prior-season semantics applied at read time, like batter_batted_ball).
"""
from __future__ import annotations

import argparse

import pandas as pd

from ingester.db import eastern_today, get_connection

MIN_BIP = 50            # below this a batter's xHR rate is too noisy to store
XHR_REGRESSION_BIP = 50  # EB prior weight (matches the barrel loader)
_DEFAULT_MODEL = "models/xhr_gbm.pkl"


def cmd_refresh_batter_xhr(args: argparse.Namespace) -> None:
    import joblib

    season = getattr(args, "season", None) or eastern_today().year
    model_path = getattr(args, "model", None) or _DEFAULT_MODEL
    art = joblib.load(model_path)
    gbm = art["model"]

    print(f"[refresh-batter-xhr] Scoring {season} batted balls with {model_path}…")
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT player_id, launch_speed, launch_angle, spray_deg, park "
            "FROM batted_ball_events WHERE season = %s",
            (season,),
        ).fetchall()
        if not rows:
            print(f"[refresh-batter-xhr] no batted_ball_events for {season}")
            return
        df = pd.DataFrame(
            rows, columns=["player_id", "launch_speed", "launch_angle", "spray_deg", "park"]
        )
        # Park-neutral: hold park at a single constant so it can't differentiate batters.
        neutral_park = df["park"].mode(dropna=True)
        neutral_park = neutral_park.iloc[0] if len(neutral_park) else None
        X = pd.DataFrame({
            "launch_speed": pd.to_numeric(df["launch_speed"], errors="coerce"),
            "launch_angle": pd.to_numeric(df["launch_angle"], errors="coerce"),
            "spray_deg": pd.to_numeric(df["spray_deg"], errors="coerce"),
            "park": pd.Series([neutral_park] * len(df)).astype("category"),
        })
        # Raw GBM score: it's already better-calibrated than the isotonic re-fit (P2.2).
        df["xhr"] = gbm.predict_proba(X)[:, 1]
        league = float(df["xhr"].mean())

        agg = df.groupby("player_id")["xhr"].agg(["mean", "count"]).reset_index()
        known = {r[0] for r in conn.execute("SELECT id FROM players").fetchall()}

        written = skipped = 0
        for _, r in agg.iterrows():
            pid = int(r["player_id"])
            n = int(r["count"])
            if n < MIN_BIP or pid not in known:
                skipped += 1
                continue
            raw = float(r["mean"])
            shrunk = (raw * n + league * XHR_REGRESSION_BIP) / (n + XHR_REGRESSION_BIP)
            conn.execute(
                """
                INSERT INTO batter_xhr (player_id, season, bip, xhr_per_bb,
                                        raw_xhr_per_bb, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    bip = EXCLUDED.bip, xhr_per_bb = EXCLUDED.xhr_per_bb,
                    raw_xhr_per_bb = EXCLUDED.raw_xhr_per_bb, updated_at = NOW()
                """,
                (pid, season, n, round(shrunk, 5), round(raw, 5)),
            )
            written += 1
        conn.commit()
        print(f"[refresh-batter-xhr] wrote {written} batters (min {MIN_BIP} BIP); "
              f"{skipped} below threshold / unknown. League xHR/BB={league:.4f}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
