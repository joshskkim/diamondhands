"""record-picks / score-picks: persist the daily Model's Picks and grade them.

The home board computes Model's Picks client-side (web/components/home/
model-picks.tsx) and historically kept no record — a bad day couldn't even be
audited. `record-picks` captures the same board server-side into `model_picks`
by fetching /api/odds/best (+ /api/most-likely for the sim veto) and applying
the SAME bar; `score-picks` grades a prior slate against actuals the next
morning (game markets need final scores; props additionally need
player_game_stats, so a pick can stay pending until stats land).

KEEP THE BAR IN SYNC with model-picks.tsx — these constants are a deliberate
duplicate of the TS ones (the web computes live, this records the snapshot).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

from ingester.db import eastern_today, get_connection
from ingester.projection.constants import DEAD_GAME_STATUSES, MODEL_VERSION

# ── the bar (mirror of model-picks.tsx) ──────────────────────────────────────
# Interim tightening (Jun 2026), pending evidence-based recalibration once the
# scoring loop accrues 2–3 weeks of band data:
#   · MAX_EDGE 0.25 → 0.15 — the 0/3 day's misses were 18–21pt "edges"; at that
#     level of disagreement the smart read is model error, not free money.
#   · 'hit' excluded — backtests show H≥1 has near-zero skill signal, so
#     model−market gaps there are mostly noise. HR (where the model has a
#     validated edge) and game markets stay.
#   · HR props must not contradict the hit-rate traffic light (season clear
#     rate, n≥15): no overs on red, no unders on green.
MIN_EDGE = 0.04
MAX_EDGE = 0.15
MIN_EV = 0.05
MIN_MODEL_PROB = 0.40
LONGSHOT_EDGE = 0.08
STRONG_EDGE = 0.06
MAX_PICKS = 3
EXCLUDED_MARKETS = {"pitcher_k", "pitcher_outs", "hit"}
HIT_RATE_VETO_MIN_N = 15  # season sample needed before the traffic light can veto
# Per-market veto bands: (no OVER below, no UNDER above). Market-specific because
# clear-rate scales differ wildly — the hit bands applied to HR would veto every
# slugger alive (nobody homers in 45% of games). Markets absent here never veto.
HIT_RATE_VETO_BANDS: dict[str, tuple[float, float]] = {
    "hit": (0.45, 0.65),
    "hr": (0.08, 0.50),
}

# Resolved from the env so the dockerized nightly (where the API is the `api` compose
# service, not localhost) can reach it without daily.py threading an --api flag through.
# Mirrors the mcp-server's DIAMOND_API_URL. Local/host runs fall back to localhost. An
# explicit --api still wins (see cmd_record_picks).
DEFAULT_API = os.environ.get("DIAMOND_API_URL", "http://localhost:8080")


def _get_json(url: str) -> object:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _sim_totals_veto(play: dict, sim: dict | None) -> bool:
    """A totals lean is vetoed when the Monte-Carlo sim lands on the other side."""
    if play["market"] != "total" or play.get("line") is None or not sim:
        return False
    t = next((x for x in sim.get("totals", []) if x["gameId"] == play["gameId"]), None)
    if t is None:
        return False
    if play["side"] == "over":
        return not (t["simTotal"] > play["line"])
    return not (t["simTotal"] < play["line"])


def _sim_corroborates(play: dict, sim: dict | None) -> bool:
    """Sim agreement (totals side, or prop player on the sim leaderboard) nudges score."""
    if not sim:
        return False
    if play["market"] == "total" and play.get("line") is not None:
        t = next((x for x in sim.get("totals", []) if x["gameId"] == play["gameId"]), None)
        if t is None:
            return False
        return t["simTotal"] > play["line"] if play["side"] == "over" else t["simTotal"] < play["line"]
    if play.get("playerId") is not None and play["side"] == "over":
        key = {"hit": "hits", "hr": "homeRuns"}.get(play["market"])
        if key is None:
            return False
        return any(r["playerId"] == play["playerId"] for r in sim.get("props", {}).get(key, []))
    return False


def _hit_rate_veto(play: dict, hit_rates: dict | None) -> bool:
    """Veto a prop that contradicts the player's season clear rate (traffic light).

    Per-market bands (HIT_RATE_VETO_BANDS): an OVER on a player below the market's
    floor, or an UNDER on one above its ceiling, needs more than a model-market gap
    to justify. No band for the market, or no data → no veto.
    """
    if not hit_rates or play.get("playerId") is None:
        return False
    band = HIT_RATE_VETO_BANDS.get(play["market"])
    if band is None:
        return False
    hr = hit_rates.get(f"{play['playerId']}:{play['market']}")
    if hr is None or hr.get("season") is None or hr.get("nSeason", 0) < HIT_RATE_VETO_MIN_N:
        return False
    over_floor, under_ceiling = band
    if play["side"] == "over":
        return hr["season"] < over_floor
    if play["side"] == "under":
        return hr["season"] > under_ceiling
    return False


def build_picks(plays: list[dict], sim: dict | None,
                hit_rates: dict | None = None) -> list[dict]:
    """Apply the Model's Picks bar; returns at most MAX_PICKS plays, board order."""
    candidates: list[tuple[float, dict, float, bool]] = []
    for p in plays:
        if p["market"] in EXCLUDED_MARKETS or p.get("fairProb") is None:
            continue
        edge = p["modelProb"] - p["fairProb"]
        if edge < MIN_EDGE or edge > MAX_EDGE:
            continue
        if p["evPct"] < MIN_EV:
            continue
        if p["modelProb"] < MIN_MODEL_PROB and edge < LONGSHOT_EDGE:
            continue
        if _sim_totals_veto(p, sim):
            continue
        if _hit_rate_veto(p, hit_rates):
            continue
        corroborated = _sim_corroborates(p, sim)
        score = edge + 0.5 * p["evPct"] + (0.02 if corroborated else 0.0)
        strong = edge >= STRONG_EDGE and p["modelProb"] >= 0.5
        candidates.append((score, p, edge, strong))

    candidates.sort(key=lambda c: -c[0])
    picks: list[dict] = []
    used_games: set[int] = set()
    for score, p, edge, strong in candidates:
        if p["gameId"] in used_games:
            continue
        used_games.add(p["gameId"])
        picks.append({**p, "edge": edge, "strong": strong})
        if len(picks) == MAX_PICKS:
            break
    return picks


def cmd_record_picks(args: argparse.Namespace) -> None:
    slate = args.date if getattr(args, "date", None) is not None else eastern_today()
    api = getattr(args, "api", None) or DEFAULT_API

    plays = _get_json(f"{api}/api/odds/best?date={slate}&limit=200")
    try:
        sim = _get_json(f"{api}/api/most-likely?date={slate}")
    except Exception as exc:  # noqa: BLE001 — sim is a corroborator, not a requirement
        print(f"[record-picks] sim unavailable ({exc}); recording without the sim veto")
        sim = None
    try:
        hit_rates = {f"{h['playerId']}:{h['market']}": h
                     for h in _get_json(f"{api}/api/odds/hit-rates?date={slate}")}
    except Exception as exc:  # noqa: BLE001 — like the sim, a veto source, not a requirement
        print(f"[record-picks] hit-rates unavailable ({exc}); recording without that veto")
        hit_rates = None

    picks = build_picks(plays, sim, hit_rates)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM model_picks WHERE slate_date = %s", (slate,))
        for rank, p in enumerate(picks, start=1):
            conn.execute(
                """
                INSERT INTO model_picks (
                    slate_date, rank, game_id, market, side, line, player_id,
                    player_name, matchup, model_prob, fair_prob, edge, ev_pct,
                    price_american, book, strong, model_version, recorded_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    slate, rank, p["gameId"], p["market"], p["side"], p.get("line"),
                    p.get("playerId"), p.get("playerName"), p.get("matchup"),
                    p["modelProb"], p["fairProb"], p["edge"], p["evPct"],
                    p["priceAmerican"], p.get("bestBook"), p["strong"],
                    MODEL_VERSION, datetime.now(timezone.utc),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[record-picks] {slate}: recorded {len(picks)} pick(s) "
          f"(from {len(plays)} priced plays).")
    for i, p in enumerate(picks, 1):
        who = p.get("playerName") or p.get("matchup")
        print(f"  #{i} {who} {p['market']} {p['side']} {p.get('line')} "
              f"model={p['modelProb']:.3f} fair={p['fairProb']:.3f} edge={p['edge']:+.3f}")


# ── CLV (closing-line value) ────────────────────────────────────────────────

# Opposite side per market, needed to de-vig the closing two-sided price.
_OPPOSITE_SIDE = {"over": "under", "under": "over", "home": "away", "away": "home"}


def _devig_two_way(side_decimal: float, opp_decimal: float) -> float | None:
    """De-vig a two-sided market to this side's fair probability (matches OddsService).

        fair = side_implied / (side_implied + opp_implied),   implied = 1 / decimal
    Returns None for non-positive prices.
    """
    if side_decimal <= 0 or opp_decimal <= 0:
        return None
    side_implied = 1.0 / side_decimal
    opp_implied = 1.0 / opp_decimal
    if side_implied + opp_implied <= 0:
        return None
    return side_implied / (side_implied + opp_implied)


def _closing_quote(
    conn, game_id: int, market: str, side: str, line: float | None,
    book: str | None, start_time,
) -> tuple[int | None, float | None, float | None, object]:
    """Find the closing quote for a pick's selection and its de-vigged fair prob.

    "Closing" = the last odds_snapshots pull strictly before first pitch
    (start_time_utc). We match the SAME book + line the pick was taken at, then read
    both sides from that same pull (one refresh-odds run shares a captured_at, so the
    opposite side is present at the same timestamp) and de-vig exactly like OddsService:
        fair = side_implied / (side_implied + opp_implied),  implied = 1/decimal.
    Returns (close_american, close_decimal, close_fair_prob, captured_at); any field is
    None when the selection or its opposite side can't be found at close.
    """
    scope = "prop" if market in ("hit", "hr") else "game"
    # Latest pull for THIS selection before first pitch.
    ts_row = conn.execute(
        """
        SELECT MAX(captured_at) FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND market = %s AND side = %s
          AND line IS NOT DISTINCT FROM %s AND bookmaker = %s
          AND captured_at < %s
        """,
        (game_id, scope, market, side, line, book, start_time),
    ).fetchone()
    captured_at = ts_row[0] if ts_row else None
    if captured_at is None:
        return None, None, None, None

    # Both sides at that pull (same book, same line).
    rows = conn.execute(
        """
        SELECT side, price_american, price_decimal FROM odds_snapshots
        WHERE game_id = %s AND scope = %s AND market = %s AND bookmaker = %s
          AND line IS NOT DISTINCT FROM %s AND captured_at = %s
        """,
        (game_id, scope, market, book, line, captured_at),
    ).fetchall()
    prices = {r[0]: (int(r[1]), float(r[2])) for r in rows}
    if side not in prices:
        return None, None, None, captured_at
    close_american, close_decimal = prices[side]

    opp = _OPPOSITE_SIDE.get(side)
    fair = None
    if opp is not None and opp in prices:
        fair = _devig_two_way(close_decimal, prices[opp][1])
    return close_american, close_decimal, fair, captured_at


# ── scoring ───────────────────────────────────────────────────────────────────

def _grade(market: str, side: str, line: float | None,
           home: int, away: int, prop_value: int | None) -> tuple[float | None, bool | None]:
    """(result_value, won) for a settled pick; won=None means push (still scored)."""
    if market == "total":
        total = home + away
        if line is None or float(total) == line:
            return float(total), None
        won = total > line if side == "over" else total < line
        return float(total), won
    if market == "moneyline":
        won = home > away if side == "home" else away > home
        return float(home - away if side == "home" else away - home), won
    if market == "run_line":
        margin = (home - away) if side == "home" else (away - home)
        if line is None or margin + line == 0:
            return float(margin), None
        return float(margin), margin + line > 0
    if market in ("hit", "hr"):
        if prop_value is None or line is None:
            return None, None
        won = prop_value > line if side == "over" else prop_value < line
        return float(prop_value), won
    return None, None


def cmd_score_picks(args: argparse.Namespace) -> None:
    slate = args.date if getattr(args, "date", None) is not None \
        else eastern_today() - timedelta(days=1)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT mp.slate_date, mp.rank, mp.game_id, mp.market, mp.side, mp.line,
                   mp.player_id, g.home_score, g.away_score, g.detailed_status,
                   CASE mp.market WHEN 'hit' THEN pgs.hits WHEN 'hr' THEN pgs.home_runs END,
                   mp.fair_prob, mp.book, g.start_time_utc
            FROM model_picks mp
            JOIN games g ON g.id = mp.game_id
            LEFT JOIN player_game_stats pgs
                   ON pgs.player_id = mp.player_id AND pgs.game_id = mp.game_id
            WHERE mp.slate_date = %s AND mp.scored_at IS NULL
            ORDER BY mp.rank
            """,
            (slate,),
        ).fetchall()

        scored = pending = voided = clv_n = 0
        record: list[str] = []
        for (slate_date, rank, game_id, market, side, line, player_id,
             home, away, detailed_status, prop_val,
             fair_prob, book, start_time) in rows:
            if detailed_status in DEAD_GAME_STATUSES:
                # The game won't be played — settle the pick as voided (no win/loss)
                # rather than leaving it pending forever. record-picks normally rebuilds
                # the slate off a board that already excludes dead games, so this only
                # catches a pick recorded before the postponement landed.
                conn.execute(
                    "UPDATE model_picks SET result_value=NULL, won=NULL, scored_at=NOW() "
                    "WHERE slate_date=%s AND rank=%s",
                    (slate_date, rank),
                )
                voided += 1
                record.append(f"  #{rank} {market} {side} {line}: VOID ({detailed_status.lower()})")
                continue
            if home is None or away is None:
                pending += 1
                continue  # final score not ingested yet (run backfill-scores first)
            if market in ("hit", "hr") and prop_val is None and player_id is not None:
                pending += 1
                continue  # player stats not ingested yet (or DNP — retried next run)
            value, won = _grade(
                market, side, float(line) if line is not None else None,
                int(home), int(away), int(prop_val) if prop_val is not None else None,
            )
            # CLV: compare our bet-time de-vigged prob to the closing line. Captured at
            # scoring (the close exists by now); independent of win/loss. Isolated in a
            # SAVEPOINT + try/except: CLV is a measurement nicety and must never roll back
            # or block the pick's grade (a bad closing-odds read would otherwise poison the
            # whole scoring transaction). On any failure we record the grade with CLV NULL.
            close_am = close_dec = close_fair = clv = captured_at = None
            try:
                with conn.transaction():  # SAVEPOINT — a read error rolls back only this
                    close_am, close_dec, close_fair, captured_at = _closing_quote(
                        conn, game_id, market, side,
                        float(line) if line is not None else None, book, start_time,
                    )
                if close_fair is not None and fair_prob is not None:
                    clv = round(close_fair - float(fair_prob), 4)
                    clv_n += 1
            except Exception as exc:  # noqa: BLE001 — never let CLV break grading
                close_am = close_dec = close_fair = clv = captured_at = None
                print(f"[score-picks] CLV capture failed for rank {rank} "
                      f"(grade still recorded): {exc}", file=sys.stderr)
            conn.execute(
                "UPDATE model_picks SET result_value=%s, won=%s, scored_at=NOW(), "
                "close_price_american=%s, close_price_decimal=%s, close_fair_prob=%s, "
                "clv=%s, clv_captured_at=%s "
                "WHERE slate_date=%s AND rank=%s",
                (value, won, close_am,
                 round(close_dec, 3) if close_dec is not None else None,
                 round(close_fair, 4) if close_fair is not None else None,
                 clv, captured_at, slate_date, rank),
            )
            scored += 1
            outcome = "PUSH" if won is None else ("WON" if won else "LOST")
            clv_str = f" clv={clv:+.4f}" if clv is not None else ""
            record.append(f"  #{rank} {market} {side} {line}: {outcome} (actual {value}){clv_str}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[score-picks] {slate}: scored {scored} ({clv_n} with CLV), voided {voided}, "
          f"pending {pending} (voided = game postponed/cancelled; "
          f"pending = missing final score or player stats; re-run after backfills).")
    for line_ in record:
        print(line_)
