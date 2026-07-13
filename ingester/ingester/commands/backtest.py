"""backtest: Run a full backtesting suite comparing predictions to actuals.

Usage:
    uv run python main.py backtest --start 2025-04-01 --end 2025-09-30
    uv run python main.py backtest --start 2025-04-01 --end 2025-04-30 --csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from dataclasses import dataclass

import psycopg

from ingester.db import get_connection
from ingester.metrics import (
    average_precision,
    baseline_brier,
    brier_decomposition,
    brier_score,
    calibration_buckets,
    crps_count_mean,
    expected_calibration_error,
    log_loss,
    mae,
    mae_per_game,
    pearson,
    roc_auc,
    sharpness,
    top_k_lift,
)
from ingester.projection.constants import LEAGUE_RUNS_PER_GAME_BASE, MODEL_VERSION
from ingester.projection.prop_blend import blend_market
from ingester.projection.runner import run_backtest_projections


# ---------------------------------------------------------------------------
# Constants snapshot
# ---------------------------------------------------------------------------

def collect_model_constants() -> dict:
    """Serialize all LEAGUE_* and adjustment constants for audit."""
    import ingester.projection.constants as C
    result: dict = {}
    for k, v in vars(C).items():
        if k.startswith("_") or k == "MODEL_VERSION":
            continue
        if isinstance(v, tuple):
            result[k] = list(v)
        elif isinstance(v, (int, float, str, bool)):
            result[k] = v
    # Backtest neutralizes weather (historical games lack a live weather snapshot),
    # so tag the run to keep future runs comparable apples-to-apples.
    result["WEATHER_SKIPPED"] = True
    return result


# ---------------------------------------------------------------------------
# Metric functions live in ingester.metrics (shared with compute-accuracy):
# brier_score, baseline_brier, calibration_buckets, mae_per_game.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _insert_backtest_run(
    conn: psycopg.Connection,
    start: date,
    end: date,
    model_version: str = MODEL_VERSION,
) -> int:
    """Create a new backtest_runs row in 'running' state; returns its id."""
    row = conn.execute(
        """
        INSERT INTO backtest_runs (
            range_start, range_end, model_version, model_constants
        )
        VALUES (%s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (start, end, model_version, json.dumps(collect_model_constants())),
    ).fetchone()
    conn.commit()
    return int(row[0])


def _update_backtest_run(
    conn: psycopg.Connection,
    run_id: int,
    n_games: int,
    n_batter_projections: int,
    brier_h1: float,
    brier_h2: float,
    brier_hr: float,
    brier_k: float,
    mae: float,
    cal_json: str,
    run_corr: float = float("nan"),
    run_mae_baseline: float = float("nan"),
    ll_h1: float = float("nan"),
    ll_h2: float = float("nan"),
    ll_hr: float = float("nan"),
    ll_k: float = float("nan"),
) -> None:
    def _ll(v: float) -> float | None:
        return None if v != v else round(v, 5)  # NaN -> NULL

    conn.execute(
        """
        UPDATE backtest_runs SET
            completed_at         = NOW(),
            n_games              = %s,
            n_batter_projections = %s,
            brier_hit1plus       = %s,
            brier_hit2plus       = %s,
            brier_hr             = %s,
            brier_k1plus         = %s,
            mae_total_runs       = %s,
            run_corr             = %s,
            run_mae_baseline     = %s,
            log_loss_hit1plus    = %s,
            log_loss_hit2plus    = %s,
            log_loss_hr          = %s,
            log_loss_k1plus      = %s,
            calibration_buckets  = %s::jsonb
        WHERE id = %s
        """,
        (
            n_games, n_batter_projections,
            None if brier_h1 != brier_h1 else round(brier_h1, 5),  # NaN check
            None if brier_h2 != brier_h2 else round(brier_h2, 5),
            None if brier_hr != brier_hr else round(brier_hr, 5),
            None if brier_k != brier_k  else round(brier_k,  5),
            None if mae != mae           else round(mae, 2),
            None if run_corr != run_corr else round(run_corr, 3),
            None if run_mae_baseline != run_mae_baseline else round(run_mae_baseline, 2),
            _ll(ll_h1), _ll(ll_h2), _ll(ll_hr), _ll(ll_k),
            cal_json,
            run_id,
        ),
    )
    conn.commit()


def _latest_snapshot_before(conn: psycopg.Connection, game_date: date) -> date | None:
    """Return the most recent as_of_date <= game_date in batter_skill_snapshots, or None."""
    row = conn.execute(
        "SELECT MAX(as_of_date) FROM batter_skill_snapshots WHERE as_of_date <= %s",
        (game_date,),
    ).fetchone()
    return row[0] if row and row[0] is not None else None


@dataclass
class _Outcomes:
    p_hit1: list[float]
    p_hit2: list[float]
    p_hr:   list[float]
    p_k:    list[float]
    a_hit1: list[int]
    a_hit2: list[int]
    a_hr:   list[int]
    a_k:    list[int]
    # Total bases: the closed-form path persists only the mean → count-regression (p_tb/a_tb).
    # Under --sim-props the sim also captures a full TB pmf → a probabilistic score:
    # tb_crps = [(pmf, actual)], and 2+TB as a Brier market (tb2_p / tb2_a).
    p_tb:   list[float]  # expected_total_bases (model mean)
    a_tb:   list[int]    # actual total bases
    tb_crps: list[tuple[list[float], int]]
    tb2_p:  list[float]  # P(TB >= 2) from the sim pmf
    tb2_a:  list[int]    # 1[actual TB >= 2]
    game_hits: dict[int, tuple[float, float]]  # game_id → (exp, actual)
    n_projections: int
    n_games: int
    csv_rows: list[tuple]  # populated only when want_csv=True
    # Sim-blend weight fitting (--sim-props): the simulator's per-batter estimate aligned
    # 1:1 to p_hit1/p_hr/p_k above. None entries = no sim prob for that row.
    sim_hit1: list[float | None]
    sim_hr:   list[float | None]
    sim_k:    list[float | None]
    # Prior-season HR-ranker features (leak-free), each None when the hitter has no
    # prior-season batted-ball profile. Aligned 1:1 to p_hr/a_hr. Keyed by feature
    # name: barrel, pulled_air, sweet_spot, p90_ev. The baselines the model must beat.
    hr_rankers: dict[str, list[float | None]]
    # As-of-date season clear rates for the empirical-shrinkage blend (--clear-rate-blend),
    # aligned 1:1 to p_hit1/p_hr. Leak-free: each is the player's rate over his same-season
    # games STRICTLY BEFORE this one (None / 0 for his first game). All None when the flag
    # is off. n_season backs both markets (hit and hr are boxscore-complete columns).
    hit_season: list[float | None]
    hr_season: list[float | None]
    n_season: list[int | None]
    # Segmentation dimensions (--segment-by), aligned 1:1 to p_hit1/p_hr/p_k/a_*. Each may
    # be None when the batter's lineup row is absent (LEFT JOIN game_lineups).
    seg_month: list[int | None]
    seg_home:  list[bool | None]
    seg_slot:  list[int | None]
    seg_hand:  list[str | None]


def _load_outcomes(
    conn: psycopg.Connection,
    run_id: int,
    want_csv: bool = False,
    want_clear_rates: bool = False,
) -> _Outcomes:
    """
    Join backtest_projections to player_game_stats for the given run.
    Only rows with non-NULL predictions AND matching player_game_stats are included.

    When want_clear_rates, also attach each hitter's as-of-date season clear rate for hit
    and hr (the empirical-shrinkage blend's input). It's computed with an expanding window
    over player_game_stats that EXCLUDEs the current game's date group — the exact
    `game_date < slate` boundary the live ClearRateRepository uses, so the backtest scores
    the blend the site would actually have served. Gated behind the flag because the window
    scans the whole table; a normal run selects NULLs and pays nothing.
    """
    if want_clear_rates:
        clear_rate_cte = """
        WITH clear_rates AS (
            SELECT player_id, game_id,
                   COUNT(*)                  OVER w AS n_season,
                   AVG((hits > 0)::int)      OVER w AS hit_season,
                   AVG((home_runs > 0)::int) OVER w AS hr_season
            FROM player_game_stats
            WHERE plate_appearances > 0
            WINDOW w AS (
                PARTITION BY player_id, EXTRACT(YEAR FROM game_date)::int
                ORDER BY game_date
                RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW EXCLUDE GROUP
            )
        )
        """
        clear_rate_cols = "cr.hit_season, cr.hr_season, cr.n_season"
        clear_rate_join = ("LEFT JOIN clear_rates cr "
                           "ON cr.player_id = bp.player_id AND cr.game_id = bp.game_id")
    else:
        clear_rate_cte = ""
        clear_rate_cols = ("NULL::float AS hit_season, NULL::float AS hr_season, "
                           "NULL::int AS n_season")
        clear_rate_join = ""

    rows = conn.execute(
        f"""
        {clear_rate_cte}
        SELECT
            bp.p_hit_1plus, bp.p_hit_2plus, bp.p_hr, bp.p_k_1plus,
            bp.expected_hits,
            bp.game_id,
            bp.player_id,
            g.game_date,
            pgs.hits,
            CASE WHEN pgs.hits      >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.hits      >= 2 THEN 1 ELSE 0 END,
            CASE WHEN pgs.home_runs >= 1 THEN 1 ELSE 0 END,
            CASE WHEN pgs.strikeouts>= 1 THEN 1 ELSE 0 END,
            bp.sim_p_hit_1plus, bp.sim_p_hr, bp.sim_p_k_1plus,
            bbb.barrel_pct, bbb.pulled_air_pct, bbb.sweet_spot_pct, bbb.p90_ev_fbld,
            bx.xhr_per_bb,
            {clear_rate_cols},
            bp.expected_total_bases, pgs.total_bases, bp.sim_tb_pmf,
            -- Segmentation dimensions (--segment-by): month, home/away, lineup slot,
            -- and the opposing starter's throwing hand.
            EXTRACT(MONTH FROM g.game_date)::int,
            gl.is_home, gl.batting_order, opp.throws
        FROM backtest_projections bp
        JOIN games g ON g.id = bp.game_id
        JOIN player_game_stats pgs
            ON pgs.player_id = bp.player_id
            AND pgs.game_id  = bp.game_id
            AND pgs.plate_appearances > 0
            AND pgs.plate_appearances IS NOT NULL
        -- Naive-barrel-rank baseline: each hitter's PRIOR-season barrel rate (leak-free,
        -- known before the game). The yardstick the model's HR ranking must beat.
        LEFT JOIN batter_batted_ball bbb
            ON bbb.player_id = bp.player_id
            AND bbb.season = EXTRACT(YEAR FROM g.game_date)::int - 1
        -- Learned prior-season true-talent xHR/BB (Phase 2), same leak-free join.
        LEFT JOIN batter_xhr bx
            ON bx.player_id = bp.player_id
            AND bx.season = EXTRACT(YEAR FROM g.game_date)::int - 1
        {clear_rate_join}
        -- Lineup slot + side for this batter, and the opposing starter's hand.
        LEFT JOIN game_lineups gl
            ON gl.game_id = bp.game_id AND gl.player_id = bp.player_id
        LEFT JOIN players opp
            ON opp.id = CASE WHEN gl.is_home THEN g.away_probable_pitcher_id
                             ELSE g.home_probable_pitcher_id END
        WHERE bp.backtest_run_id = %s
          AND pgs.game_id IS NOT NULL
          AND bp.p_hit_1plus IS NOT NULL
        ORDER BY g.game_date, bp.game_id, bp.player_id
        """,
        (run_id,),
    ).fetchall()

    n_total = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT game_id) FROM backtest_projections WHERE backtest_run_id = %s",
        (run_id,),
    ).fetchone()

    out = _Outcomes(
        p_hit1=[], p_hit2=[], p_hr=[], p_k=[],
        a_hit1=[], a_hit2=[], a_hr=[], a_k=[],
        game_hits={},
        n_projections=int(n_total[0]),
        n_games=int(n_total[1]),
        csv_rows=[],
        p_tb=[], a_tb=[], tb_crps=[], tb2_p=[], tb2_a=[],
        sim_hit1=[], sim_hr=[], sim_k=[],
        hr_rankers={"barrel": [], "pulled_air": [], "sweet_spot": [], "p90_ev": [], "xhr": []},
        hit_season=[], hr_season=[], n_season=[],
        seg_month=[], seg_home=[], seg_slot=[], seg_hand=[],
    )

    for row in rows:
        (pred_h1, pred_h2, pred_hr, pred_k,
         exp_hits, game_id, player_id, game_date,
         actual_hits, act_h1, act_h2, act_hr, act_k,
         sim_h1, sim_hr, sim_k,
         f_barrel, f_pull_air, f_sweet, f_p90, f_xhr,
         cr_hit_season, cr_hr_season, cr_n_season,
         exp_tb, act_tb, sim_tb_pmf,
         s_month, s_home, s_slot, s_hand) = row

        out.p_hit1.append(float(pred_h1))
        out.p_hit2.append(float(pred_h2) if pred_h2 is not None else float(pred_h1))
        out.p_hr.append(float(pred_hr) if pred_hr is not None else 0.0)
        out.p_k.append(float(pred_k)  if pred_k  is not None else 0.0)
        out.a_hit1.append(int(act_h1))
        out.a_hit2.append(int(act_h2))
        out.a_hr.append(int(act_hr))
        out.a_k.append(int(act_k))
        out.sim_hit1.append(float(sim_h1) if sim_h1 is not None else None)
        out.sim_hr.append(float(sim_hr) if sim_hr is not None else None)
        out.sim_k.append(float(sim_k) if sim_k is not None else None)
        out.hr_rankers["barrel"].append(float(f_barrel) if f_barrel is not None else None)
        out.hr_rankers["pulled_air"].append(float(f_pull_air) if f_pull_air is not None else None)
        out.hr_rankers["sweet_spot"].append(float(f_sweet) if f_sweet is not None else None)
        out.hr_rankers["p90_ev"].append(float(f_p90) if f_p90 is not None else None)
        out.hr_rankers["xhr"].append(float(f_xhr) if f_xhr is not None else None)
        out.hit_season.append(float(cr_hit_season) if cr_hit_season is not None else None)
        out.hr_season.append(float(cr_hr_season) if cr_hr_season is not None else None)
        out.n_season.append(int(cr_n_season) if cr_n_season is not None else None)

        out.seg_month.append(int(s_month) if s_month is not None else None)
        out.seg_home.append(bool(s_home) if s_home is not None else None)
        out.seg_slot.append(int(s_slot) if s_slot is not None else None)
        out.seg_hand.append(str(s_hand) if s_hand is not None else None)

        # Total bases: scored independently on the subset where both the projection and
        # the actual are present, so a NULL never pollutes the count MAE/correlation.
        if exp_tb is not None and act_tb is not None:
            out.p_tb.append(float(exp_tb))
            out.a_tb.append(int(act_tb))
        # Distributional TB (sim-props only): whole-pmf CRPS + a 2+TB Brier market.
        if act_tb is not None and sim_tb_pmf is not None:
            pmf = sim_tb_pmf if isinstance(sim_tb_pmf, list) else json.loads(sim_tb_pmf)
            pmf = [float(x) for x in pmf]
            out.tb_crps.append((pmf, int(act_tb)))
            out.tb2_p.append(sum(pmf[2:]))          # P(TB >= 2)
            out.tb2_a.append(1 if int(act_tb) >= 2 else 0)

        gid = int(game_id)
        eh = float(exp_hits) if exp_hits is not None else 0.0
        ah = int(actual_hits) if actual_hits is not None else 0
        prev = out.game_hits.get(gid, (0.0, 0))
        out.game_hits[gid] = (prev[0] + eh, prev[1] + ah)

        if want_csv:
            d = str(game_date)[:10]
            pid = int(player_id)
            gid_csv = int(game_id)
            out.csv_rows.extend([
                (d, pid, gid_csv, "hit1plus", float(pred_h1), int(act_h1)),
                (d, pid, gid_csv, "hit2plus", float(pred_h2) if pred_h2 else float(pred_h1), int(act_h2)),
                (d, pid, gid_csv, "hr",       float(pred_hr) if pred_hr else 0.0, int(act_hr)),
                (d, pid, gid_csv, "k1plus",   float(pred_k)  if pred_k  else 0.0, int(act_k)),
            ])
            if exp_tb is not None and act_tb is not None:
                out.csv_rows.append(
                    (d, pid, gid_csv, "total_bases", float(exp_tb), int(act_tb)))

    return out


# ---------------------------------------------------------------------------
# Pretty-print
# ---------------------------------------------------------------------------

_SEP = "═" * 50


def _cal_flag(bucket: dict) -> str:
    diff = bucket["actual_rate"] - bucket["predicted_mean"]
    if abs(diff) <= 0.02:
        return "✓"
    return "⚠ underconfident" if diff > 0 else "⚠ overconfident"


def _load_run_totals(
    conn: psycopg.Connection, run_id: int
) -> tuple[list[float], list[float]]:
    """(predicted, actual) game-total runs for games in this run that have a final score."""
    rows = conn.execute(
        """
        SELECT bgr.expected_total_runs, (g.home_score + g.away_score)
        FROM backtest_game_runs bgr
        JOIN games g ON g.id = bgr.game_id
        WHERE bgr.backtest_run_id = %s
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    preds = [float(r[0]) for r in rows]
    actuals = [float(r[1]) for r in rows]
    return preds, actuals


def _load_run_line_outcomes(
    conn: psycopg.Connection, run_id: int
) -> tuple[list[float], list[int]]:
    """(P(home covers -1.5), actual home-cover) for --sim-props games with a final score.

    Home covers -1.5 iff it wins by 2+ runs; integer margins never push a .5 line. Rows
    without a sim cover prob (non --sim-props runs) are excluded by the NOT NULL filter.
    """
    rows = conn.execute(
        """
        SELECT bgr.p_home_cover_1_5, g.home_score, g.away_score
        FROM backtest_game_runs bgr
        JOIN games g ON g.id = bgr.game_id
        WHERE bgr.backtest_run_id = %s
          AND bgr.p_home_cover_1_5 IS NOT NULL
          AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    preds = [float(r[0]) for r in rows]
    actuals = [1 if (int(r[1]) - int(r[2])) >= 2 else 0 for r in rows]
    return preds, actuals


def _vs_close_summary(
    model: list[float], fair: list[float], actual: list[int]
) -> dict:
    """Summarize the model's edge vs the de-vigged closing line (the 'beat the close' read).

    edge = model − fair. Splits the sample by edge sign and reports each side's realized
    win rate vs the average market-fair prob it faced: if the model has real edge, the rows
    it likes (edge > 0) should win MORE than the market implied, and vice versa. Returns
    {n, mean_edge, corr_edge_actual, fav_*}. NaN-safe.
    """
    n = len(model)
    if n == 0:
        return {"n": 0, "mean_edge": float("nan"), "corr_edge_actual": float("nan"),
                "fav_n": 0, "fav_realized": float("nan"), "fav_fair": float("nan"),
                "dog_n": 0, "dog_realized": float("nan"), "dog_fair": float("nan")}
    edge = [m - f for m, f in zip(model, fair)]
    fav = [i for i in range(n) if edge[i] > 0]
    dog = [i for i in range(n) if edge[i] <= 0]
    def _rate(idx, xs):
        return sum(xs[i] for i in idx) / len(idx) if idx else float("nan")
    return {
        "n": n,
        "mean_edge": sum(edge) / n,
        "corr_edge_actual": pearson(edge, [float(a) for a in actual]),
        "fav_n": len(fav), "fav_realized": _rate(fav, actual), "fav_fair": _rate(fav, fair),
        "dog_n": len(dog), "dog_realized": _rate(dog, actual), "dog_fair": _rate(dog, fair),
    }


def _print_vs_close(model: list[float], fair: list[float], actual: list[int]) -> None:
    """Print the batter-hit edge-vs-close read (I3): does the model beat the market?"""
    def _n(v: float, p: int = 3) -> str:
        return f"{v:.{p}f}" if v == v else "N/A"

    s = _vs_close_summary(model, fair, actual)
    print(f"\nEdge vs closing line — batter 1+ hit ({s['n']:,} rows w/ a close):")
    if not s["n"]:
        print("  (no closing quotes on this run — needs stored odds_snapshots for the range)")
        return
    # Model log-loss vs the market's own log-loss: does the model's prob beat the close?
    mkt_ll = log_loss(fair, actual)
    mdl_ll = log_loss(model, actual)
    print(f"  model log-loss={_n(mdl_ll, 4)}  vs market(close) log-loss={_n(mkt_ll, 4)}  "
          f"(lower wins)")
    print(f"  mean model edge (model−fair): {s['mean_edge']:+.4f}   "
          f"corr(edge, actual): {_n(s['corr_edge_actual'])}")
    print(f"  model-favored (edge>0): n={s['fav_n']:,}  realized={_n(s['fav_realized'])}  "
          f"vs fair={_n(s['fav_fair'])}")
    print(f"  market-favored (edge≤0): n={s['dog_n']:,}  realized={_n(s['dog_realized'])}  "
          f"vs fair={_n(s['dog_fair'])}")
    print("  (beat-the-close = model-favored rows realize ABOVE their market-fair prob)")


def _load_vs_close_hit(
    conn: psycopg.Connection, run_id: int
) -> tuple[list[float], list[float], list[int]]:
    """(model P(1+ hit), de-vigged closing fair prob, actual 1+ hit) for batter-hit rows.

    The close = the last odds_snapshots pull at/before first pitch (per game+player, most
    recent book); both over/under 0.5 come from that same pull and are de-vigged like
    OddsService. Rows without a paired closing quote are dropped.
    """
    from ingester.commands.picks import _devig_two_way
    rows = conn.execute(
        """
        WITH closes AS (
            SELECT DISTINCT ON (o.game_id, o.player_id)
                   o.game_id, o.player_id, o.bookmaker, o.captured_at,
                   o.price_decimal AS over_dec
            FROM odds_snapshots o
            JOIN games g ON g.id = o.game_id
            WHERE o.market = 'hit' AND o.side = 'over' AND o.line = 0.5
              AND o.captured_at <= g.start_time_utc
            ORDER BY o.game_id, o.player_id, o.captured_at DESC
        ),
        paired AS (
            SELECT c.game_id, c.player_id, c.over_dec, u.price_decimal AS under_dec
            FROM closes c
            JOIN odds_snapshots u
              ON u.game_id = c.game_id AND u.player_id = c.player_id
             AND u.bookmaker = c.bookmaker AND u.captured_at = c.captured_at
             AND u.market = 'hit' AND u.side = 'under' AND u.line = 0.5
        )
        SELECT bp.p_hit_1plus, p.over_dec, p.under_dec,
               CASE WHEN pgs.hits >= 1 THEN 1 ELSE 0 END
        FROM backtest_projections bp
        JOIN paired p ON p.game_id = bp.game_id AND p.player_id = bp.player_id
        JOIN player_game_stats pgs
          ON pgs.player_id = bp.player_id AND pgs.game_id = bp.game_id
        WHERE bp.backtest_run_id = %s AND bp.p_hit_1plus IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    model, fair, actual = [], [], []
    for m, over_dec, under_dec, hit in rows:
        f = _devig_two_way(float(over_dec), float(under_dec))
        if f is not None:
            model.append(float(m))
            fair.append(f)
            actual.append(int(hit))
    return model, fair, actual


# ---------------------------------------------------------------------------
# T3 — run-line isotonic calibration (fit on one range, apply to another)
# ---------------------------------------------------------------------------

def _fit_runline_cal(preds: list[float], actuals: list[int], path: str) -> None:
    """Fit an isotonic map for the run-line cover prob and save it to `path`."""
    from ingester.projection.calibration import fit_isotonic
    y = fit_isotonic(preds, actuals)
    with open(path, "w") as f:
        json.dump({"runline": y}, f)
    print(f"[backtest] Run-line calibration map fit on {len(preds):,} games → {path}")


def _apply_runline_cal(preds: list[float], path: str) -> list[float]:
    """Apply a saved run-line isotonic map (101-pt grid) to `preds` via linear interp."""
    with open(path) as f:
        y = json.load(f)["runline"]
    out = []
    for p in preds:
        p = min(1.0, max(0.0, p))
        lo = min(int(p * 100), 99)
        frac = p * 100 - lo
        out.append(y[lo] + frac * (y[lo + 1] - y[lo]))
    return out


def _load_nrfi_outcomes(
    conn: psycopg.Connection, run_id: int
) -> tuple[list[float], list[int]]:
    """(P(YRFI), actual YRFI) for games with V53 first-inning actuals.

    YRFI = a run scores in the first inning by either team (home_score_1st + away_score_1st
    > 0). p_yrfi is the closed-form served number; NRFI is its complement. Graded as YRFI so
    the stored prob maps directly to the outcome.
    """
    rows = conn.execute(
        """
        SELECT bgr.p_yrfi, g.home_score_1st, g.away_score_1st
        FROM backtest_game_runs bgr
        JOIN games g ON g.id = bgr.game_id
        WHERE bgr.backtest_run_id = %s
          AND bgr.p_yrfi IS NOT NULL
          AND g.home_score_1st IS NOT NULL AND g.away_score_1st IS NOT NULL
        """,
        (run_id,),
    ).fetchall()
    preds = [float(r[0]) for r in rows]
    actuals = [1 if (int(r[1]) + int(r[2])) > 0 else 0 for r in rows]
    return preds, actuals


# ---------------------------------------------------------------------------
# Pitcher props (V79): count-regression MAE + canonical-line Brier vs pitcher_starts
# ---------------------------------------------------------------------------

# Count markets: (label, projection col, pitcher_starts actual col). `runs` is the
# model's expected runs-allowed graded against actual EARNED runs — a known small
# approximation (the model has no unearned-run notion), flagged in the printout.
_PITCH_COUNTS = (
    ("outs", "expected_outs", "outs"),
    ("K",    "expected_k",    "strikeouts"),
    ("BB",   "expected_bb",   "walks"),
    ("H",    "expected_h",    "hits_allowed"),
    ("HR",   "expected_hr",   "hr_allowed"),
    ("ER≈R", "expected_runs", "earned_runs"),
    ("BF",   "expected_bf",   "batters_faced"),
)

# Canonical-line prop markets: (label, workload key, line, actual col). The workload
# jsonb stores P(stat > line); we grade it as a Brier/log-loss market vs 1[actual > line].
_PITCH_LINES = (
    ("K>5.5",     "p_k",    "5.5",  "strikeouts"),
    ("outs>17.5", "p_outs", "17.5", "outs"),
    ("BB>1.5",    "p_bb",   "1.5",  "walks"),
)


def _load_pitcher_outcomes(
    conn: psycopg.Connection, run_id: int
) -> tuple[dict[str, dict[str, list[float]]], dict[str, dict[str, list]],
           list[tuple[list[float], int]]]:
    """Join backtest_pitcher_projections to pitcher_starts (V31) for the given run.

    Returns (counts, lines, outs_crps):
      counts[label] = {"pred": [...], "act": [...]}  for the count-regression markets
      lines[label]  = {"p": [...], "a": [...]}       for the canonical-line Brier markets
      outs_crps     = [(outs pmf, actual outs), ...] for the whole-distribution CRPS
    Only rows with a matching pitcher_starts actual are included; NULLs are skipped per
    market so a missing column never pollutes another market's score.
    """
    rows = conn.execute(
        """
        SELECT
            bpp.expected_outs, bpp.expected_k, bpp.expected_bb, bpp.expected_h,
            bpp.expected_hr, bpp.expected_runs, bpp.expected_bf,
            ps.outs, ps.strikeouts, ps.walks, ps.hits_allowed, ps.hr_allowed,
            ps.earned_runs, ps.batters_faced,
            bpp.workload
        FROM backtest_pitcher_projections bpp
        JOIN pitcher_starts ps
            ON ps.player_id = bpp.pitcher_id AND ps.game_id = bpp.game_id
        WHERE bpp.backtest_run_id = %s
        """,
        (run_id,),
    ).fetchall()

    counts = {label: {"pred": [], "act": []} for label, *_ in _PITCH_COUNTS}
    lines = {label: {"p": [], "a": []} for label, *_ in _PITCH_LINES}
    outs_crps: list[tuple[list[float], int]] = []
    for row in rows:
        (e_outs, e_k, e_bb, e_h, e_hr, e_runs, e_bf,
         a_outs, a_k, a_bb, a_h, a_hr, a_er, a_bf, workload) = row
        preds = {"outs": e_outs, "K": e_k, "BB": e_bb, "H": e_h,
                 "HR": e_hr, "ER≈R": e_runs, "BF": e_bf}
        acts = {"outs": a_outs, "K": a_k, "BB": a_bb, "H": a_h,
                "HR": a_hr, "ER≈R": a_er, "BF": a_bf}
        for label, *_ in _PITCH_COUNTS:
            p, a = preds[label], acts[label]
            if p is not None and a is not None:
                counts[label]["pred"].append(float(p))
                counts[label]["act"].append(float(a))
        if workload:
            wl = workload if isinstance(workload, dict) else json.loads(workload)
            act_by_col = {"strikeouts": a_k, "outs": a_outs, "walks": a_bb}
            for label, wkey, lkey, acol in _PITCH_LINES:
                p_over = (wl.get(wkey) or {}).get(lkey)
                actual = act_by_col[acol]
                if p_over is not None and actual is not None:
                    lines[label]["p"].append(float(p_over))
                    lines[label]["a"].append(1 if float(actual) > float(lkey) else 0)
            pmf = wl.get("p_outs_pmf")
            if pmf and a_outs is not None:
                outs_crps.append(([float(x) for x in pmf], int(a_outs)))
    return counts, lines, outs_crps


def _print_pitcher_results(
    counts: dict[str, dict[str, list[float]]],
    lines: dict[str, dict[str, list]],
    outs_crps: list[tuple[list[float], int]],
) -> None:
    """Print the pitcher-prop scorecard: count MAE/corr/bias + canonical-line Brier + CRPS."""
    def _n(v: float, p: int = 3) -> str:
        return f"{v:.{p}f}" if v == v else "N/A"

    n_graded = len(counts["K"]["pred"]) if counts["K"]["pred"] else 0
    print(f"\nPitcher props ({n_graded:,} graded starts vs pitcher_starts):")
    if not n_graded:
        print("  (no matched starts — ensure backfill-pitcher-starts covers the range)")
        return
    print("  Count markets — MAE vs naive mean-baseline (ER≈R grades runs-allowed vs earned):")
    print(f"    {'market':<7}{'n':>6}{'MAE':>8}{'base':>8}{'corr':>7}{'bias':>8}")
    for label, *_ in _PITCH_COUNTS:
        pred, act = counts[label]["pred"], counts[label]["act"]
        if not pred:
            continue
        mkt_mae = mae(pred, act)
        mean_a = sum(act) / len(act)
        base = mae([mean_a] * len(act), act)
        bias = sum(pred) / len(pred) - mean_a
        print(f"    {label:<7}{len(pred):>6,}{mkt_mae:>8.3f}{base:>8.3f}"
              f"{_n(pearson(pred, act)):>7}{bias:>+8.3f}")
    print("  Canonical-line props — Brier / log-loss vs base rate (from workload ladders):")
    print(f"    {'market':<11}{'n':>6}{'Brier':>9}{'log-loss':>10}{'base-rate':>11}")
    for label, *_ in _PITCH_LINES:
        p, a = lines[label]["p"], lines[label]["a"]
        if not p:
            continue
        base_rate = sum(a) / len(a)
        print(f"    {label:<11}{len(p):>6,}{brier_score(p, a):>9.4f}"
              f"{log_loss(p, a):>10.4f}{base_rate:>11.3f}")
    if outs_crps:
        # Whole-distribution score: CRPS over the full outs pmf vs actual outs (the only
        # market with a stored pmf), alongside the naive "always the mean-outs point" RPS.
        mean_o = sum(a for _, a in outs_crps) / len(outs_crps)
        naive = [([0.0] * int(mean_o) + [1.0], a) for _, a in outs_crps]
        print(f"  Outs distribution — CRPS vs naive point forecast ({len(outs_crps):,}):")
        print(f"    outs CRPS={crps_count_mean(outs_crps):.4f}  "
              f"naive(point@{mean_o:.0f})={crps_count_mean(naive):.4f}  (lower=better)")


# ---------------------------------------------------------------------------
# Segmentation (--segment-by): where is the batter model strong / weak?
# ---------------------------------------------------------------------------

def _segment_groups(out: _Outcomes, key: str) -> list[tuple[str, list[int]]]:
    """(label, row-indices) groups for the chosen dimension, in a sensible order.

    Rows whose segment value is NULL (no lineup row) are dropped from the breakdown.
    ``confidence`` buckets by the model's own P(H≥1) decile — the calibration lens.
    """
    n = len(out.p_hit1)
    groups: dict[str, list[int]] = {}
    if key == "confidence":
        for i in range(n):
            b = min(9, int(out.p_hit1[i] * 10))
            groups.setdefault(f"{b * 10}-{b * 10 + 10}%", []).append(i)
        return [(lbl, groups[lbl]) for lbl in sorted(groups, key=lambda s: int(s.split("-")[0]))]
    labelers = {
        "month": lambda i: f"{out.seg_month[i]:02d}" if out.seg_month[i] is not None else None,
        "home":  lambda i: (None if out.seg_home[i] is None else ("home" if out.seg_home[i] else "away")),
        "slot":  lambda i: str(out.seg_slot[i]) if out.seg_slot[i] is not None else None,
        "hand":  lambda i: out.seg_hand[i],
    }
    labeler = labelers[key]
    for i in range(n):
        lbl = labeler(i)
        if lbl is not None:
            groups.setdefault(lbl, []).append(i)
    # slot sorts numerically; the rest lexically.
    keyfn = (lambda s: int(s)) if key == "slot" else (lambda s: s)
    return [(lbl, groups[lbl]) for lbl in sorted(groups, key=keyfn)]


def _print_segmented(out: _Outcomes, key: str) -> None:
    """Per-segment Brier for the batter markets + HR ranking (AUC), to localize strength."""
    def _n(v: float, p: int = 4) -> str:
        return f"{v:.{p}f}" if v == v else "N/A"

    groups = _segment_groups(out, key)
    print(f"\nSegmented by {key} (batter markets; Brier lower=better, HR-AUC higher=better):")
    print(f"  {'group':<10}{'n':>8}{'H≥1':>9}{'HR':>9}{'K≥1':>9}{'HR-AUC':>9}")
    for lbl, idx in groups:
        if not idx:
            continue
        b_h1 = brier_score([out.p_hit1[i] for i in idx], [out.a_hit1[i] for i in idx])
        b_hr = brier_score([out.p_hr[i] for i in idx],   [out.a_hr[i] for i in idx])
        b_k  = brier_score([out.p_k[i] for i in idx],    [out.a_k[i] for i in idx])
        auc  = roc_auc([out.p_hr[i] for i in idx],       [out.a_hr[i] for i in idx])
        print(f"  {lbl:<10}{len(idx):>8,}{_n(b_h1):>9}{_n(b_hr):>9}{_n(b_k):>9}{_n(auc, 3):>9}")


def _print_results(
    run_id: int,
    start: date,
    end: date,
    out: _Outcomes,
    b_h1: float,
    b_h2: float,
    b_hr: float,
    b_k:  float,
    base_h1: float,
    base_h2: float,
    base_hr: float,
    base_k:  float,
    mae: float,
    cal: dict[str, list[dict]],
) -> None:
    def _f(v: float, places: int = 4) -> str:
        return f"{v:.{places}f}" if v == v else "N/A"

    print(_SEP)
    print(f"Backtest Run #{run_id}  |  {MODEL_VERSION}  |  {start} → {end}")
    print(_SEP)
    print(f"Games:               {out.n_games:>6,}")
    print(f"Batter projections: {out.n_projections:>6,}")
    print(f"Matched to actuals: {len(out.p_hit1):>6,}")
    print()
    print("Brier scores:")
    print(f"  P(H≥1):    {_f(b_h1)}    (baseline {_f(base_h1)})")
    print(f"  P(H≥2):    {_f(b_h2)}    (baseline {_f(base_h2)})")
    print(f"  P(HR):     {_f(b_hr)}    (baseline {_f(base_hr)})")
    print(f"  P(K≥1):    {_f(b_k)}    (baseline {_f(base_k)})")
    print()
    print(f"MAE expected vs actual hits/game:  {_f(mae, 2)}  (proxy for runs MAE)")
    print()
    print("Calibration P(HR):")
    for bucket in cal.get("hr", []):
        flag = _cal_flag(bucket)
        lo_pct = f"{bucket['lo']*100:.0f}%"
        hi_pct = f"{bucket['hi']*100:.0f}%"
        print(
            f"  {lo_pct:>4}-{hi_pct:<4}  n={bucket['n']:>5}  "
            f"pred={bucket['predicted_mean']:.3f}  actual={bucket['actual_rate']:.3f}  {flag}"
        )
    print(_SEP)


# ---------------------------------------------------------------------------
# Sim-blend weight sweep (--sim-props)
# ---------------------------------------------------------------------------

# Blend weights to try: 0% .. 100% sim in 5-pt steps. w=0 is the current closed-form
# board, so it's always in the grid and the sweep can never look worse than baseline.
_SWEEP_GRID = [i / 100 for i in range(0, 101, 5)]


def _sweep_sim_weights(out: _Outcomes) -> None:
    """Per market, sweep the sim-blend weight w over w*sim + (1-w)*closed_form and report
    the Brier-minimizing w vs the w=0 baseline. Scored on the rows that actually have a
    sim prob, so the baseline is recomputed on that same subset (not the global Brier)."""
    markets = [
        ("hit1plus", out.p_hit1, out.sim_hit1, out.a_hit1),
        ("hr",       out.p_hr,   out.sim_hr,   out.a_hr),
        ("k1plus",   out.p_k,    out.sim_k,    out.a_k),
    ]
    n_with_sim = sum(1 for s in out.sim_hit1 if s is not None)
    print(f"\nSim-blend weight sweep ({n_with_sim:,} rows with sim props):")
    if n_with_sim == 0:
        print("  (no sim props on this run — re-run with --sim-props)")
        return
    print(f"  {'market':<10}{'base(w=0)':>12}{'best w':>9}{'best Brier':>13}{'Δ Brier':>22}")
    for name, model, sim, actual in markets:
        rows = [(mp, sp, a) for mp, sp, a in zip(model, sim, actual) if sp is not None]
        if not rows:
            continue
        mp = [r[0] for r in rows]
        sp = [r[1] for r in rows]
        a = [r[2] for r in rows]
        base = brier_score(mp, a)
        best_w, best_b = 0.0, base
        for w in _SWEEP_GRID:
            blended = [w * s + (1.0 - w) * p for p, s in zip(mp, sp)]
            b = brier_score(blended, a)
            if b < best_b:
                best_b, best_w = b, w
        delta = best_b - base
        pct = (delta / base * 100.0) if base else 0.0
        print(f"  {name:<10}{base:>12.5f}{best_w:>9.2f}{best_b:>13.5f}"
              f"{delta:>+13.5f} ({pct:+.2f}%)")
    print("  NOTE: best w is IN-SAMPLE. Confirm on a held-out range before setting "
          "DIAMOND_SIM_PROP_BLEND_WEIGHT_{HIT,HR,K}.")


# ---------------------------------------------------------------------------
# Clear-rate blend validation (--clear-rate-blend)
# ---------------------------------------------------------------------------

# A raw prob of (effectively) 0 or 1 is the "not really projected" sentinel — the serving
# path drops it before the blend rather than regress it toward a base rate (see
# OddsService.sane). Mirror that here so the blend is scored on the same population.
_PROB_EPS = 1e-6


def _report_clear_rate_blend(out: _Outcomes) -> None:
    """A/B the empirical-shrinkage blend against the raw model on the two markets it both
    transforms (at their canonical line) AND the harness scores: hit(>=1) and hr(>=1).

    Unlike the sim-weight sweep there is no free parameter — SHRINK_K/PRIOR_N are fixed —
    so this is a straight before/after, not an in-sample fit. The blend is a CALIBRATION
    move, so the load-bearing metrics are log-loss and reliability (ECE + the top buckets
    where the model is most overconfident), not the rank-blind AUC family."""
    markets = [
        ("hit", out.p_hit1, out.hit_season, out.a_hit1),
        ("hr",  out.p_hr,   out.hr_season,  out.a_hr),
    ]
    n_with_rate = sum(1 for n in out.n_season if n)
    print(f"\nClear-rate blend A/B ({sum(1 for n in out.n_season if n is not None):,} rows, "
          f"{n_with_rate:,} with a prior-game rate; canonical line only):")
    if not any(s is not None for s in out.n_season):
        print("  (no clear rates loaded — this run wasn't scored with --clear-rate-blend)")
        return

    for name, raw, season, actual in markets:
        # Blend at the canonical 0.5 line; keep the raw prob where it's the degenerate
        # sentinel (blending it would launder a 0 into a plausible base rate).
        blended = [
            r if (r is None or r <= _PROB_EPS or r >= 1.0 - _PROB_EPS)
            else blend_market(name, 0.5, r, s, n)
            for r, s, n in zip(raw, season, out.n_season)
        ]
        b_raw, b_bl = brier_score(raw, actual), brier_score(blended, actual)
        ll_raw, ll_bl = log_loss(raw, actual), log_loss(blended, actual)
        cal_raw = calibration_buckets(raw, actual)
        cal_bl = calibration_buckets(blended, actual)
        ece_raw, ece_bl = expected_calibration_error(cal_raw), expected_calibration_error(cal_bl)

        def _delta(before: float, after: float) -> str:
            d = after - before
            pct = (d / before * 100.0) if before else 0.0
            flag = "better" if d < 0 else "worse" if d > 0 else "flat"
            return f"{before:.5f} -> {after:.5f}  ({d:+.5f}, {pct:+.1f}%, {flag})"

        print(f"\n  [{name}]  (lower is better for all three)")
        print(f"    Brier    {_delta(b_raw, b_bl)}")
        print(f"    log-loss {_delta(ll_raw, ll_bl)}")
        print(f"    ECE      {_delta(ece_raw, ece_bl)}")
        # The thesis is upper-bucket overconfidence, so show the top prediction buckets:
        # predicted mean vs realized rate, before and after. The blend should pull an
        # over-predicting bucket's mean down toward its realized rate.
        # Buckets are per-prediction-range, so raw and blended don't share bins; index each
        # by its [lo,hi) range and show the top raw buckets alongside the blended bucket at
        # the same range (— when the blend emptied that range by pulling predictions out).
        bl_by_range = {(b["lo"], b["hi"]): b for b in cal_bl}
        print(f"    {'bucket':<12}{'raw: pred->act (n)':>24}{'blended: pred->act (n)':>26}")
        for br in cal_raw[-3:]:
            rng = f"{br['lo']:.1f}-{br['hi']:.1f}"
            bb = bl_by_range.get((br["lo"], br["hi"]))
            raw_cell = f"{br['predicted_mean']:.3f}->{br['actual_rate']:.3f} ({br['n']})"
            bl_cell = (f"{bb['predicted_mean']:.3f}->{bb['actual_rate']:.3f} ({bb['n']})"
                       if bb else "—")
            print(f"    {rng:<12}{raw_cell:>24}{bl_cell:>26}")
    print("\n  Calibration verdict is aggregate-safe (fixed constants, no fit); still worth "
          "a held-out range before moving the blend into the projection engine.")


# ---------------------------------------------------------------------------
# Command entrypoint
# ---------------------------------------------------------------------------

def cmd_backtest(args: argparse.Namespace) -> None:
    start: date = args.start
    end: date   = args.end
    want_csv: bool = getattr(args, "csv", False)
    model: str = getattr(args, "model", "mechanistic")

    if start > end:
        print("[backtest] ERROR: --start must be <= --end", file=sys.stderr)
        sys.exit(1)

    bundle = None
    model_version = MODEL_VERSION
    if model in ("xgb", "blend"):
        from ingester.ml.infer import ModelBundle  # lazy: keeps xgboost off the default path
        from ingester.ml.train import resolve_models_dir
        bundle = ModelBundle.load(resolve_models_dir(getattr(args, "models_dir", None)), blend=(model == "blend"))
        if bundle is None:
            need = "train-xgb --target all --save" + (" then tune-blend" if model == "blend" else "")
            print(f"[backtest] ERROR: --model {model} but models/weights missing; run {need} first",
                  file=sys.stderr)
            sys.exit(1)
        model_version = f"{MODEL_VERSION}-{model}"

    if getattr(args, "calibrate", False):
        from ingester.projection.runner import set_calibrator
        from ingester.projection.calibration import Calibrator
        from ingester.ml.train import resolve_models_dir
        cal = Calibrator.load(f"{resolve_models_dir(getattr(args, 'models_dir', None))}/calibration.json")
        set_calibrator(cal)
        model_version = f"{model_version}-cal"
        print(f"[backtest] Calibration: {'ON' if cal else 'requested but calibration.json missing'}")

    if getattr(args, "park_personalized", False):
        from ingester.projection.runner import set_backtest_park_personalized
        set_backtest_park_personalized(True)
        model_version = f"{model_version}-parkgeo"
        print("[backtest] Park personalization: ON (prior-season batted-ball profile)")

    if getattr(args, "weather_carry", False):
        from ingester.projection.runner import set_backtest_weather_carry
        set_backtest_weather_carry(True)
        model_version = f"{model_version}-windspray"
        print("[backtest] Weather carry HR: ON (trajectory model, spray-weighted wind, "
              "prior-season profiles)")

    sim_props = getattr(args, "sim_props", False)
    if sim_props:
        from ingester.projection.runner import set_backtest_sim_props
        set_backtest_sim_props(True)
        print("[backtest] Sim props: ON (Monte-Carlo per-batter capture; will sweep "
              "sim-blend weight per market)")

    if getattr(args, "team_defense", False):
        from ingester.projection.runner import set_team_defense
        set_team_defense(True)
        model_version = f"{model_version}-teamdef"
        print("[backtest] Team defense: ON (leak-free xBA hit-suppression factor)")

    clear_rate_blend = getattr(args, "clear_rate_blend", False)
    if clear_rate_blend:
        # Purely a scoring-time transform on the raw hit/hr probs — projection is unchanged,
        # so this only loads clear rates and prints an A/B (no model_version suffix).
        print("[backtest] Clear-rate blend: ON (A/B the empirical-shrinkage blend on hit/hr)")

    print(f"[backtest] Range {start} → {end}  |  Model {model_version}")

    conn = get_connection()
    try:
        # Step a: create the run row.
        run_id = _insert_backtest_run(conn, start, end, model_version)
        print(f"[backtest] Run #{run_id} created")

        # Step b: project each date in the range.
        total_days = 0
        current = start
        while current <= end:
            as_of = _latest_snapshot_before(conn, current)
            if as_of is None:
                current += timedelta(days=1)
                continue

            summary = run_backtest_projections(conn, current, as_of, run_id, bundle=bundle)
            conn.commit()

            if summary.games_projected > 0:
                total_days += 1
                print(
                    f"  {current}: {summary.games_projected} games, "
                    f"{summary.batter_rows} batter rows  (snapshot {as_of})"
                )
            current += timedelta(days=1)

        print(f"[backtest] Projections done — {total_days} game-days projected")

        # Step c+d: load outcomes and compute metrics.
        out = _load_outcomes(conn, run_id, want_csv=want_csv, want_clear_rates=clear_rate_blend)
        if not out.p_hit1:
            print(
                "[backtest] WARN: No matched batter rows found. "
                "Ensure player_game_stats covers the backtest range.",
                file=sys.stderr,
            )

        b_h1 = brier_score(out.p_hit1, out.a_hit1)
        b_h2 = brier_score(out.p_hit2, out.a_hit2)
        b_hr = brier_score(out.p_hr,   out.a_hr)
        b_k  = brier_score(out.p_k,    out.a_k)

        base_h1 = baseline_brier(out.a_hit1)
        base_h2 = baseline_brier(out.a_hit2)
        base_hr = baseline_brier(out.a_hr)
        base_k  = baseline_brier(out.a_k)

        # Log-loss: strictly-proper, sharper than Brier on the rare-event markets.
        ll_h1 = log_loss(out.p_hit1, out.a_hit1)
        ll_h2 = log_loss(out.p_hit2, out.a_hit2)
        ll_hr = log_loss(out.p_hr,   out.a_hr)
        ll_k  = log_loss(out.p_k,    out.a_k)

        mae_hits = mae_per_game(out.game_hits)  # legacy hits proxy (printed for continuity)

        # Real run-total scoring: predicted game total vs actual final score, plus a
        # naive "always predict the league mean total" baseline and the correlation.
        run_pred, run_act = _load_run_totals(conn, run_id)
        run_mae = mae(run_pred, run_act)
        run_corr = pearson(run_pred, run_act)
        baseline_total = 2 * LEAGUE_RUNS_PER_GAME_BASE
        run_mae_baseline = (
            mae([baseline_total] * len(run_act), run_act) if run_act else float("nan")
        )

        cal = {
            "hit1plus": calibration_buckets(out.p_hit1, out.a_hit1),
            "hit2plus": calibration_buckets(out.p_hit2, out.a_hit2),
            "hr":       calibration_buckets(out.p_hr,   out.a_hr),
            "k1plus":   calibration_buckets(out.p_k,    out.a_k),
        }

        # Pitcher props + run line (V79) — loaded while the connection is open, printed below.
        pitch_counts, pitch_lines, pitch_outs_crps = _load_pitcher_outcomes(conn, run_id)
        rl_p, rl_a = _load_run_line_outcomes(conn, run_id)
        nrfi_p, nrfi_a = _load_nrfi_outcomes(conn, run_id)
        vc = (_load_vs_close_hit(conn, run_id)
              if getattr(args, "vs_close", False) else ([], [], []))

        # Step e: persist metrics (mae_total_runs now holds the REAL run MAE).
        _update_backtest_run(
            conn, run_id,
            out.n_games, out.n_projections,
            b_h1, b_h2, b_hr, b_k, run_mae,
            json.dumps(cal),
            run_corr=run_corr,
            run_mae_baseline=run_mae_baseline,
            ll_h1=ll_h1, ll_h2=ll_h2, ll_hr=ll_hr, ll_k=ll_k,
        )

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # Step f: pretty-print.
    _print_results(
        run_id, start, end, out,
        b_h1, b_h2, b_hr, b_k,
        base_h1, base_h2, base_hr, base_k,
        mae_hits, cal,
    )

    # Real run-total accuracy (V19): predicted game total vs final score.
    print(f"\nGame run totals ({len(run_pred)} scored games):")
    print(f"  run MAE:            {run_mae:.3f}")
    print(f"  league-mean MAE:    {run_mae_baseline:.3f}  (always {2 * LEAGUE_RUNS_PER_GAME_BASE:.1f})")
    print(f"  corr(pred, actual): {run_corr:+.3f}")

    # Run line (V79): P(home covers -1.5) vs actual, from the sim margin distribution.
    # Only present on --sim-props runs; Brier/log-loss + ECE, plus the base cover rate.
    if rl_p:
        rl_base = sum(rl_a) / len(rl_a)
        rl_ece = expected_calibration_error(calibration_buckets(rl_p, rl_a))
        print(f"\nRun line — P(home covers -1.5) ({len(rl_p):,} sim'd games):")
        print(f"  Brier:              {brier_score(rl_p, rl_a):.4f}  (baseline {baseline_brier(rl_a):.4f})")
        print(f"  log-loss:           {log_loss(rl_p, rl_a):.4f}")
        print(f"  ECE:                {rl_ece:.4f}")
        print(f"  home-cover rate:    {rl_base:.3f}")
        # T3: fit a calibration map from this run, and/or apply one and show the delta.
        if getattr(args, "fit_runline_cal", None):
            _fit_runline_cal(rl_p, rl_a, args.fit_runline_cal)
        if getattr(args, "runline_cal", None):
            rl_c = _apply_runline_cal(rl_p, args.runline_cal)
            c_ece = expected_calibration_error(calibration_buckets(rl_c, rl_a))
            print(f"  calibrated Brier:   {brier_score(rl_c, rl_a):.4f}  "
                  f"(ECE {c_ece:.4f}) [T3 map: {args.runline_cal}]")

    # NRFI (V80): P(YRFI) vs the V53 first-inning actuals. Closed-form, so always present.
    if nrfi_p:
        nrfi_base = sum(nrfi_a) / len(nrfi_a)
        nrfi_ece = expected_calibration_error(calibration_buckets(nrfi_p, nrfi_a))
        print(f"\nNRFI — P(run scores in 1st, either team) ({len(nrfi_p):,} games):")
        print(f"  Brier:              {brier_score(nrfi_p, nrfi_a):.4f}  (baseline {baseline_brier(nrfi_a):.4f})")
        print(f"  log-loss:           {log_loss(nrfi_p, nrfi_a):.4f}")
        print(f"  ECE:                {nrfi_ece:.4f}")
        print(f"  YRFI rate:          {nrfi_base:.3f}")

    # Total bases (V5 stores only the expected count, so this is a count-regression read,
    # not a probability market): MAE + correlation vs the naive "always predict the mean"
    # baseline, plus mean bias to catch a systematically high/low TB projection.
    if out.p_tb:
        a_tb_f = [float(a) for a in out.a_tb]
        tb_mae = mae(out.p_tb, a_tb_f)
        mean_tb = sum(a_tb_f) / len(a_tb_f)
        tb_base_mae = mae([mean_tb] * len(a_tb_f), a_tb_f)
        tb_bias = sum(out.p_tb) / len(out.p_tb) - mean_tb
        print(f"\nTotal bases ({len(out.p_tb):,} batter rows):")
        print(f"  TB MAE:             {tb_mae:.3f}")
        print(f"  mean-TB MAE:        {tb_base_mae:.3f}  (always {mean_tb:.2f})")
        print(f"  corr(pred, actual): {pearson(out.p_tb, a_tb_f):+.3f}")
        print(f"  mean bias:          {tb_bias:+.3f}  (pred − actual; >0 = over-projecting)")
        # Distributional TB from the sim pmf (--sim-props only): 2+TB Brier + whole-pmf CRPS.
        if out.tb2_p:
            print(f"  2+TB Brier:         {brier_score(out.tb2_p, out.tb2_a):.4f}  "
                  f"(baseline {baseline_brier(out.tb2_a):.4f}, rate {sum(out.tb2_a)/len(out.tb2_a):.3f})")
            print(f"  TB CRPS:            {crps_count_mean(out.tb_crps):.4f}  ({len(out.tb_crps):,} sim'd)")

    # Pitcher props (V79): count-regression + canonical-line Brier + outs CRPS vs pitcher_starts.
    _print_pitcher_results(pitch_counts, pitch_lines, pitch_outs_crps)

    # Log-loss (sharper than Brier on rare events; lower is better).
    print("\nLog-loss (proper scoring, rewards sharp+correct):")
    print(f"  hit1plus={ll_h1:.5f}  hit2plus={ll_h2:.5f}  hr={ll_hr:.5f}  k1plus={ll_k:.5f}")

    # Discrimination + lift (ranking quality Brier is blind to on the rare HR event).
    # ROC-AUC = P(rank a homer above a non-homer); PR-AUC concentrates on the top of
    # the list where our picks live; top-decile lift = realized rate of the top 10%
    # ranked vs the base rate (1.0 = no skill). These are what "getting HR right" means.
    _disc_markets = [
        ("hit1plus", out.p_hit1, out.a_hit1),
        ("hit2plus", out.p_hit2, out.a_hit2),
        ("hr",       out.p_hr,   out.a_hr),
        ("k1plus",   out.p_k,    out.a_k),
    ]
    def _n(v: float, p: int = 3) -> str:
        return f"{v:.{p}f}" if v == v else "N/A"
    print("\nDiscrimination (rank quality; AUC/PR-AUC higher=better; lift 1.0=no skill):")
    print(f"  {'market':<10}{'ROC-AUC':>9}{'PR-AUC':>9}{'base':>8}"
          f"{'top10% rate':>13}{'lift':>8}")
    for name, preds, acts in _disc_markets:
        auc = roc_auc(preds, acts)
        ap = average_precision(preds, acts)
        lift = top_k_lift(preds, acts, max(1, len(preds) // 10))
        print(f"  {name:<10}{_n(auc):>9}{_n(ap):>9}{_n(lift['base_rate']):>8}"
              f"{_n(lift['top_k_rate']):>13}{_n(lift['lift']):>8}")

    # Calibration quality: ECE = sample-weighted |predicted - actual| across the
    # calibration buckets (lower=better); sharpness = variance of the forecasts (higher
    # is better, but ONLY meaningful when ECE is low — a sharp+miscalibrated model is
    # confidently wrong). Reported together per Gneiting: maximize sharpness s.t. calibration.
    print("\nCalibration quality — ECE/reliability lower=better, resolution higher=better;")
    print("  Brier ≈ reliability − resolution + uncertainty (Murphy decomposition):")
    print(f"  {'market':<10}{'ECE':>8}{'sharp':>8}{'reliab':>9}{'resol':>9}{'uncert':>9}")
    for name, preds, acts in _disc_markets:
        ece = expected_calibration_error(cal[name])
        base = sum(acts) / len(acts) if acts else float("nan")
        dec = brier_decomposition(cal[name], base)
        print(f"  {name:<10}{_n(ece):>8}{_n(sharpness(preds)):>8}"
              f"{_n(dec['reliability']):>9}{_n(dec['resolution']):>9}{_n(dec['uncertainty']):>9}")

    # HR gate: does the model out-rank prior-season HR rankers (naive batted-ball
    # features + the learned xHR)? Scored on the shared subset where EVERY ranker is
    # present, so the comparison is apples-to-apples and no metric sees a NULL.
    _rk_names = list(out.hr_rankers.keys())
    idx = [i for i in range(len(out.p_hr))
           if all(out.hr_rankers[nm][i] is not None for nm in _rk_names)]
    print(f"\nHR gate — model vs prior-season rankers "
          f"({len(idx)}/{len(out.p_hr)} rows w/ all profiles; higher=better):")
    if idx:
        a_hr = [out.a_hr[i] for i in idx]
        k = max(1, len(idx) // 10)
        rankers = [("model", [out.p_hr[i] for i in idx])]
        rankers += [(name, [vals[i] for i in idx])
                    for name, vals in out.hr_rankers.items()]
        print(f"  {'ranker':<12}{'ROC-AUC':>9}{'PR-AUC':>9}{'top10%-lift':>13}")
        for label, scores in rankers:
            lift = top_k_lift(scores, a_hr, k)
            print(f"  {label:<12}{_n(roc_auc(scores, a_hr)):>9}"
                  f"{_n(average_precision(scores, a_hr)):>9}{_n(lift['lift']):>13}")
    else:
        print("  (no rows with a prior-season profile — load a prior season w/ refresh-batted-ball)")

    # Sim-blend weight fitting (only when --sim-props captured the simulator's estimate).
    if sim_props:
        _sweep_sim_weights(out)

    # Empirical-shrinkage blend A/B (scores the serving-layer PropBlend on hit/hr).
    if clear_rate_blend:
        _report_clear_rate_blend(out)

    # Segmentation breakdown (--segment-by): localize where the model is strong/weak.
    segment_by = getattr(args, "segment_by", None)
    if segment_by:
        _print_segmented(out, segment_by)

    # Edge vs closing line (--vs-close): the model-beats-market read (I3).
    if getattr(args, "vs_close", False):
        _print_vs_close(*vc)

    # Step g: optional CSV.
    if want_csv and out.csv_rows:
        csv_path = f"/tmp/backtest_{run_id}.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["game_date", "player_id", "game_id", "market", "predicted", "actual"])
            writer.writerows(out.csv_rows)
        print(f"\n[backtest] CSV written → {csv_path}  ({len(out.csv_rows):,} rows)")
