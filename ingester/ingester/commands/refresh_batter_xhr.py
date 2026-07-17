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


def _eb_shrink(raw: float, n: int, target: float, k: int = XHR_REGRESSION_BIP) -> float:
    """Empirical-Bayes blend of a raw rate (from n samples) toward a target by weight k.

    Used for both the overall rate (target = league xHR) and each hand split (target =
    the batter's OWN overall xHR, so a thin per-hand sample reverts to his own power).
    """
    return (raw * n + target * k) / (n + k)


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
            "SELECT player_id, launch_speed, launch_angle, spray_deg, park, p_throws "
            "FROM batted_ball_events WHERE season = %s",
            (season,),
        ).fetchall()
        if not rows:
            print(f"[refresh-batter-xhr] no batted_ball_events for {season}")
            return
        df = pd.DataFrame(
            rows,
            columns=["player_id", "launch_speed", "launch_angle", "spray_deg", "park", "p_throws"],
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
        # Per-(batter, opposing-pitcher-hand) mean xHR for the hand split. Only L/R
        # balls (p_throws NULL on pre-migration rows / rare missing hands are dropped).
        hand = df[df["p_throws"].isin(["L", "R"])]
        hand_agg = (
            hand.groupby(["player_id", "p_throws"])["xhr"].agg(["mean", "count"]).reset_index()
        )
        # {player_id: {"L": (mean, n), "R": (mean, n)}}
        by_hand: dict[int, dict[str, tuple[float, int]]] = {}
        for _, hrow in hand_agg.iterrows():
            by_hand.setdefault(int(hrow["player_id"]), {})[str(hrow["p_throws"])] = (
                float(hrow["mean"]), int(hrow["count"])
            )
        known = {r[0] for r in conn.execute("SELECT id FROM players").fetchall()}

        def _shrink_hand(raw_player: float, hand_stats: tuple[float, int] | None):
            """EB-regress a hand's raw xHR toward the batter's OWN overall xHR (not
            league) so thin per-hand samples fall back to his own power. None when the
            hand is unseen."""
            if hand_stats is None:
                return None, None
            raw_h, n_h = hand_stats
            return round(_eb_shrink(raw_h, n_h, raw_player), 5), n_h

        written = skipped = 0
        for _, r in agg.iterrows():
            pid = int(r["player_id"])
            n = int(r["count"])
            if n < MIN_BIP or pid not in known:
                skipped += 1
                continue
            raw = float(r["mean"])
            shrunk = _eb_shrink(raw, n, league)
            hands = by_hand.get(pid, {})
            xhr_l, bip_l = _shrink_hand(raw, hands.get("L"))
            xhr_r, bip_r = _shrink_hand(raw, hands.get("R"))
            conn.execute(
                """
                INSERT INTO batter_xhr (player_id, season, bip, xhr_per_bb,
                                        raw_xhr_per_bb, xhr_vs_l, xhr_vs_r,
                                        bip_vs_l, bip_vs_r, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (player_id, season) DO UPDATE SET
                    bip = EXCLUDED.bip, xhr_per_bb = EXCLUDED.xhr_per_bb,
                    raw_xhr_per_bb = EXCLUDED.raw_xhr_per_bb,
                    xhr_vs_l = EXCLUDED.xhr_vs_l, xhr_vs_r = EXCLUDED.xhr_vs_r,
                    bip_vs_l = EXCLUDED.bip_vs_l, bip_vs_r = EXCLUDED.bip_vs_r,
                    updated_at = NOW()
                """,
                (pid, season, n, round(shrunk, 5), round(raw, 5),
                 xhr_l, xhr_r, bip_l, bip_r),
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
